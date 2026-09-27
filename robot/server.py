"""Gemini Pupper robot server: HTTP + WebSocket API on port 8000, and the web app.

Run on the Pupper after the robot stack is up (see start.sh):
    python3 robot/server.py

Every command endpoint returns {"success": bool, "message": str}. The browser
passes that straight back to Gemini as the tool result, so Gemini hears about
refused speeds, unknown tricks and failed controller switches.

(Provided: the endpoints only translate HTTP into ToolServer calls. The tool
logic you write lives in tool_server.py; the tools Gemini sees live in
services/geminiLive.ts.)
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

import psutil
import uvicorn
from fastapi import FastAPI, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tool_server import LIMITS, ToolServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("server")

REPO = Path(__file__).resolve().parent.parent
WEB_DIST = REPO / "dist"
BATTERY_SCRIPT = Path("/home/pi/pupperv3-monorepo/robot/utils/check_batt_voltage.py")

# Friendly trick names Gemini sees -> recording file stem, with what each looks like.
# Only tricks whose recording is installed are offered (see /animations).
TRICKS = {
    "twerk": ("twerk_recording_2025-09-04_16-14-51_0", "From standing, wiggles its hips in a rhythmic dance"),
    "lie_sit_lie": ("lie_sit_lie_recording_2025-09-03_12-44-08_0", "From lying down, sits up and lies back down"),
    "stand_sit_shake_sit_stand": ("stand_sit_shake_sit_stand_recording_2025-09-03_12-47-18_0", "From standing, sits, shakes a paw, sits, stands back up"),
    "stand_sit_stand": ("stand_sit_stand_recording_2025-09-03_12-46-36_0", "From standing, sits down and stands back up"),
    "upward_dog": ("upward_dog_recording_2025-10-22_17-17-07", "From lying down, yoga upward dog and back down"),
    "lie_downward_dog": ("lie_downward_dog_recording_2025-09-04_16-08-00_0", "From lying down, yoga downward dog"),
    "stand_downward_dog": ("stand_downward_dog_recording_2025-09-04_16-09-51_0", "From standing, yoga downward dog"),
    "superman": ("superman_recording_2025-10-22_17-47-41", "From lying down, lifts legs off the ground like flying"),
    "pee": ("pee2_recording_2025-10-22_17-41-45", "From standing, lifts a back leg to pee"),
    "push_up": ("push_up_recording_2025-09-04_16-11-34_0", "From standing, lowers and raises its body"),
    "sneeze": ("sneeze_recording_2025-09-04_16-13-54_0", "From standing, a sneezing head and body jerk"),
    "spider": ("spider_recording_2025-09-04_16-12-38_0", "From lying down, silly spider legs"),
    "swim": ("swim_recording_2025-09-04_16-10-45_0", "From lying down, paddles its legs like swimming"),
}

tools: ToolServer | None = None


class Detections:
    """Forwards Hailo person detections (ZMQ on localhost:5556) to browser WebSockets."""

    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def run(self) -> None:
        try:
            import zmq
            import zmq.asyncio
        except ImportError:
            log.warning("pyzmq missing; eye tracking from robot detections disabled")
            return
        sock = zmq.asyncio.Context().socket(zmq.SUB)
        sock.connect("tcp://127.0.0.1:5556")
        sock.subscribe(b"")
        while True:
            payload = (await sock.recv_multipart())[-1].decode("utf-8", errors="ignore")
            if payload.startswith("{"):
                for ws in list(self.clients):
                    try:
                        await ws.send_text(payload)
                    except Exception:
                        self.clients.discard(ws)


detections = Detections()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global tools
    tools = ToolServer()
    task = asyncio.create_task(detections.run())
    yield
    task.cancel()


app = FastAPI(title="Gemini Pupper robot server", lifespan=lifespan)
# The web app is served from this same origin; also allow a dev server on the laptop.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


def T() -> ToolServer:
    if tools is None:
        raise HTTPException(503, "tool server not ready")
    return tools


# ------------------------------------------------------------------ models
class MoveVelocity(BaseModel):
    forward_backward_velocity: float = Field(..., description="m/s, positive = forward")
    right_left_velocity: float = Field(..., description="m/s, positive = right")
    turning_velocity: float = Field(..., description="deg/s, positive = turn right")
    duration: float = Field(..., description="seconds")


class MoveDirection(BaseModel):
    heading: float = Field(..., description="degrees, 0 = forward, 90 = right")
    speed: float
    duration: float


class Trick(BaseModel):
    animation_name: str


class TrickAction(BaseModel):
    action: str


class DanceStep(BaseModel):
    """Part 3: one move of a dance. Change these fields if your dance tool needs
    different ones (keep services/geminiLive.ts and ToolServer.dance in step)."""

    move: str = Field(..., description="a move of your dance trick")
    hold_s: float = Field(0.0, description="seconds to rest after the move")


class Dance(BaseModel):
    moves: list[DanceStep]


class Wait(BaseModel):
    duration: float


class Volume(BaseModel):
    volume: int = Field(..., ge=0, le=150)


# ------------------------------------------------------------------ commands
@app.post("/walking/activate")
async def walking_activate():
    return (await T().activate_walking()).as_dict()


@app.post("/walking/deactivate")
async def walking_deactivate():
    return (await T().deactivate()).as_dict()


@app.post("/move/velocity")
async def move_velocity(req: MoveVelocity):
    # The browser uses right/clockwise-positive; ROS uses left/counter-clockwise-positive.
    res = await T().move(req.forward_backward_velocity, -req.right_left_velocity, -req.turning_velocity, req.duration)
    return res.as_dict()


@app.post("/move/direction")
async def move_direction(req: MoveDirection):
    turn = await T().move(0.0, 0.0, -90.0 if req.heading > 0 else 90.0, abs(req.heading) / 90.0) if req.heading else None
    if turn and not turn.ok:
        return turn.as_dict()
    return (await T().move(req.speed, 0.0, 0.0, req.duration)).as_dict()


@app.post("/animation")
async def animation(req: Trick):
    name = req.animation_name
    if name in T().tricks:  # custom tricks in <repo>/tricks
        return (await T().custom_trick(name)).as_dict()
    if name not in TRICKS:
        return {"success": False, "message": f"unknown trick '{name}'; available: {list(available_tricks())}"}
    return (await T().animation(TRICKS[name][0])).as_dict()


@app.post("/trick_action")
async def trick_action(req: TrickAction):
    return (await T().trick_action(req.action)).as_dict()


@app.post("/dance")
async def dance(req: Dance):
    return (await T().dance([dict(step) for step in req.moves])).as_dict()


@app.get("/trick_actions")
def trick_actions():
    """Actions of clip tricks (e.g. shake a paw while sitting): id -> trick and description."""
    return {aid: {"trick": t.name, "description": t.actions[clip]} for aid, (t, clip) in T().action_ids().items()}


@app.get("/animations")
def animations():
    return available_tricks()


def available_tricks() -> dict:
    """Built-in tricks (monorepo recordings) plus custom tricks from <repo>/tricks."""
    installed = T().animations
    out = {
        name: {"description": desc, "duration_s": round(installed[stem], 1), "kind": "built-in"}
        for name, (stem, desc) in TRICKS.items()
        if stem in installed
    }
    for name, t in T().tricks.items():
        out[name] = {"description": t.description, "duration_s": round(t.total_time, 1),
                     "kind": f"custom {t.kind}"}
    return out


@app.post("/queue/wait")
async def queue_wait(req: Wait):
    return (await T().wait(req.duration)).as_dict()


@app.post("/queue/reset")
async def queue_reset():
    return (await T().clear_queue()).as_dict()


@app.post("/queue/stop")
@app.post("/stop/immediate")
async def stop_immediate():
    return (await T().immediate_stop()).as_dict()


@app.get("/queue/status")
def queue_status():
    return T().status()


@app.post("/following/activate")
async def following_on():
    return (await T().set_following(True)).as_dict()


@app.post("/following/deactivate")
async def following_off():
    return (await T().set_following(False)).as_dict()


@app.get("/system/mode")
async def system_mode():
    return (await T().mode()).as_dict()


@app.get("/limits")
def limits():
    return LIMITS.__dict__


# ------------------------------------------------------------------ sensing
@app.get("/camera/image")
def camera_image():
    try:
        msg = T().latest_image.get_nowait()
    except Exception:
        return Response(status_code=503, content="no camera frame yet")
    T().latest_image.put_nowait(msg)  # keep it for the next poll
    return Response(content=bytes(msg.data), media_type="image/jpeg")


@app.websocket("/ws/detections")
async def ws_detections(ws: WebSocket):
    await ws.accept()
    detections.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        detections.clients.discard(ws)


@app.get("/system/status")
def system_status():
    pct = volts = None
    if BATTERY_SCRIPT.exists():
        try:
            out = subprocess.run(["python3", str(BATTERY_SCRIPT)], capture_output=True, text=True, timeout=2).stdout
            m = re.search(r"(\d+(?:\.\d+)?)V", out)
            volts = float(m.group(1)) if m else None
            out = subprocess.run(["python3", str(BATTERY_SCRIPT), "--percentage_only"], capture_output=True, text=True, timeout=2).stdout
            pct = float(out.strip())
        except Exception:
            pass
    temps = psutil.sensors_temperatures()
    cpu_temp = temps["cpu_thermal"][0].current if "cpu_thermal" in temps else None
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=1).close()
        internet = "online"
    except OSError:
        internet = "offline"
    return {
        "battery": {"percentage": pct, "is_charging": False, "voltage": volts},
        "cpu": {"usage": psutil.cpu_percent(), "temperature": cpu_temp},
        "services": {"robot": "active" if tools else "inactive", "internet": internet},
    }


@app.post("/system/volume")
def system_volume(req: Volume):
    level = max(0.0, min(req.volume / 100.0, 1.5))
    r = subprocess.run(["wpctl", "set-volume", "@DEFAULT_SINK@", str(level)], capture_output=True, text=True)
    return {"success": r.returncode == 0, "message": f"volume set to {req.volume}%" if r.returncode == 0 else r.stderr}


@app.get("/health")
def health():
    return {"status": "running", "tools": tools is not None}


# The built web app (npm run build -> dist/) is served at /, so the robot's own
# browser, or a laptop through an SSH tunnel, opens everything from one address.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")))
