#!/usr/bin/env python3
"""Desk tests for Gemini Pupper: no robot, no ROS, no Gemini needed.

Run them after every change to prompt.md, tools.py or behaviors.py:

    python3 robot/test_tools.py            # everything
    python3 robot/test_tools.py todo3      # one TODO (todo1 ... todo11)
    python3 robot/test_tools.py part2      # one part of the lab (part1 ... part6)
    python3 robot/test_tools.py robot      # the provided robot (should always pass)
    python3 robot/test_tools.py optional_jump   # the optional jump

A fake robot stands in for ROS. It keeps track of which controllers are on,
records every message the robot sends, and plays trick clips instantly. Time
is fake too, so a 10 s walk takes no real time.

The tests check what each tool does and what Gemini is told, not how you wrote
the code. When a test fails, it prints what was asked and what happened.

Passing these tests does not mean the robot is ready. That is what the real
Pupper, the e-stop and a TA are for.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


# ----------------------------------------------------------------------------- fake ROS
class _Msg:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _Vec:
    def __init__(self, x=0.0, y=0.0, z=0.0):
        self.x, self.y, self.z = x, y, z


class _Quat:
    def __init__(self, x=0.0, y=0.0, z=0.0, w=1.0):
        self.x, self.y, self.z, self.w = x, y, z, w


class _Twist:
    def __init__(self):
        self.linear, self.angular = _Vec(), _Vec()


class _DataMsg:
    def __init__(self, data=None):
        self.data = data


class _Srv:
    Request = _Msg


class _SwitchController:
    class Request(_Msg):
        STRICT = 2
        BEST_EFFORT = 1

        def __init__(self):
            super().__init__(activate_controllers=[], deactivate_controllers=[], strictness=1)


class FakeRobot:
    """The controller manager, the topics and the person follower, all in one."""

    def __init__(self, clock: "VirtualClock"):
        self.clock = clock
        self.controllers: dict[str, str] = {}
        self.published: list[tuple[float, str, object]] = []  # (time, topic, msg)
        self.switches: list[tuple[float, list[str], list[str]]] = []  # (time, deactivated, activated)
        self.subs: dict[str, list] = {}
        self.follower_on = False
        self.follow_calls: list[str] = []

    def active(self) -> set[str]:
        return {n for n, s in self.controllers.items() if s == "active"}

    def twists(self) -> list[tuple[float, _Twist]]:
        return [(t, m) for t, topic, m in self.published if topic == "/llm_cmd_vel"]

    def clips(self, controller: str) -> list[str]:
        return [m.data for _, topic, m in self.published if topic == f"/{controller}/clip"]

    def activations(self, controller: str) -> list[float]:
        return [t for t, _, on in self.switches if controller in on]

    def deactivations(self, controller: str) -> list[float]:
        return [t for t, off, _ in self.switches if controller in off]

    def send(self, topic: str, msg) -> None:
        """Deliver a message to the robot's subscribers."""
        for cb in self.subs.get(topic, []):
            cb(msg)

    def handle(self, service: str, req):
        if service.endswith("list_controllers"):
            return _Msg(controller=[_Msg(name=n, state=s) for n, s in self.controllers.items()])
        if service.endswith("switch_controller"):
            for c in req.deactivate_controllers:
                self.controllers[c] = "inactive"
            for c in req.activate_controllers:
                self.controllers[c] = "active"
            self.switches.append((self.clock.now, list(req.deactivate_controllers), list(req.activate_controllers)))
            return _Msg(ok=True)
        if service == "activate_person_following":
            self.follower_on = True
            self.follow_calls.append("on")
            return _Msg(success=True)
        if service == "deactivate_person_following":
            self.follower_on = False
            self.follow_calls.append("off")
            return _Msg(success=True)
        raise AssertionError(f"unexpected service {service}")

    def publish(self, topic: str, msg) -> None:
        self.published.append((self.clock.now, topic, msg))
        if topic.endswith("/clip"):
            controller = topic.split("/")[1]
            if self.controllers.get(controller) == "active":  # a stopped controller hears nothing
                self.send(f"/{controller}/clip_status", _DataMsg(f"{msg.data} holding frame 0 queued 0"))


ROBOT: FakeRobot | None = None


class _Future:
    def __init__(self, result):
        self._result = result

    def done(self):
        return True

    def result(self):
        return self._result


class _Client:
    def __init__(self, name):
        self.name = name

    def wait_for_service(self, timeout_sec=None):
        return True

    def call_async(self, req):
        return _Future(ROBOT.handle(self.name, req))


class _Pub:
    def __init__(self, topic):
        self.topic = topic

    def publish(self, msg):
        ROBOT.publish(self.topic, msg)


class _Node:
    def __init__(self, name):
        pass

    def create_client(self, srv_type, name):
        return _Client(name)

    def create_publisher(self, msg_type, topic, qos):
        return _Pub(topic)

    def create_subscription(self, msg_type, topic, cb, qos):
        ROBOT.subs.setdefault(topic, []).append(cb)


class _Executor:
    def add_node(self, node):
        pass

    def spin(self):
        pass


def _install_fake_ros() -> None:
    def mod(name, **attrs):
        m = types.ModuleType(name)
        m.__dict__.update(attrs)
        sys.modules[name] = m

    mod("rclpy", ok=lambda: True, init=lambda: None)
    mod("rclpy.node", Node=_Node)
    mod("rclpy.executors", SingleThreadedExecutor=_Executor)
    mod("controller_manager_msgs")
    mod("controller_manager_msgs.srv", ListControllers=_Srv, SwitchController=_SwitchController)
    mod("geometry_msgs")
    mod("geometry_msgs.msg", Twist=_Twist)
    mod("rcl_interfaces")
    mod("rcl_interfaces.msg", Log=_Msg)
    mod("sensor_msgs")
    mod("sensor_msgs.msg", CompressedImage=_Msg, Imu=_Msg, JointState=_Msg)
    mod("std_msgs")
    mod("std_msgs.msg", Empty=_DataMsg, Float32MultiArray=_DataMsg, Float64MultiArray=_DataMsg, String=_DataMsg)
    mod("std_srvs")
    mod("std_srvs.srv", Trigger=_Srv)


_install_fake_ros()
import behaviors  # noqa: E402
import robot_api  # noqa: E402
import tools  # noqa: E402
from behaviors import check_move  # noqa: E402
from robot_api import LIMITS, LLM_CMD_RATE, WALK_READY_S, WALKING_CONTROLLER, Robot  # noqa: E402
from tricks import Trick  # noqa: E402

_real_sleep = asyncio.sleep


class VirtualClock:
    """The robot's time.monotonic() and asyncio.sleep(), with no real waiting."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds, result=None):
        self.now += max(0.0, float(seconds))
        await _real_sleep(0)
        return result


class _AsyncioShim(types.ModuleType):
    def __init__(self, clock):
        super().__init__("asyncio")
        self._clock = clock

    def __getattr__(self, name):
        return getattr(asyncio, name)

    async def sleep(self, seconds, result=None):
        return await self._clock.sleep(seconds, result)


# ----------------------------------------------------------------------------- fixtures
def _clip(name, start, end, loop=False, next=None):
    return {"name": name, "start": start, "end": end, "loop": loop, "next": next}


_REFERENCE = Path(tempfile.gettempdir()) / "gemini_pupper_test_hop.json"


def fixture_tricks() -> dict[str, Trick]:
    """Made-up tricks: a policy that ends standing, one that ends lying down, a clip
    trick that holds a pose, and a reference trick. Clip lengths are in frames at 50 fps."""
    _REFERENCE.write_text(json.dumps({"playback_s": 1.0, "active_s": 0.8, "cross_fade_s": 0.1,
                                      "table": [[0.0] * 12] * 3}))
    return {
        "bow": Trick(name="bow", description="Bows.", kind="policy", path=Path("bow.json"), duration=4.0),
        "roll_over": Trick(name="roll_over", description="Rolls over and stays lying down.", kind="policy",
                           path=Path("roll_over.json"), duration=6.0, start_pose="lying", end_pose="lying"),
        "hold_pose": Trick(
            name="hold_pose", description="Gets into a pose and holds it.", kind="policy",
            path=Path("hold_pose.json"), duration=12.0, end_pose="sitting",
            clips=[
                _clip("enter", 0, 150, next="idle"),
                _clip("idle", 149, 200, loop=True),
                _clip("wave_left", 199, 300, next="idle"),
                _clip("wave_right", 299, 400, next="idle"),
                _clip("leave", 399, 550),
            ],
            actions={"wave_left": "Waves the left paw.", "wave_right": "Waves the right paw.",
                     "leave": "Stands back up."},
            exit_clip="leave",
        ),
        "hop": Trick(name="hop", description="Hops in place.", kind="reference", path=_REFERENCE, duration=1.0),
    }


class Rig:
    """A fresh Robot wired to a fresh fake robot, standing on the walking policy."""

    def __init__(self, tricks=None):
        global ROBOT
        self.clock = VirtualClock()
        ROBOT = self.robot = FakeRobot(self.clock)
        made = tricks or fixture_tricks
        robot_api.time = types.SimpleNamespace(monotonic=self.clock.monotonic)
        robot_api.asyncio = _AsyncioShim(self.clock)
        robot_api.load_tricks = made
        names = set(robot_api.LEG_CONTROLLERS) | {t.controller for t in made().values()}
        self.robot.controllers = {n: "inactive" for n in names}
        self.robot.controllers[WALKING_CONTROLLER] = "active"
        self.records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = self.records.append
        for name in ("robot_api", "tools", "behaviors"):
            lg = logging.getLogger(name)
            lg.handlers[:] = [handler]
            lg.setLevel(logging.INFO)
            lg.propagate = False
        self.ts = Robot()

    async def settle(self, limit: int = 200_000) -> bool:
        """Let the queue run until it is empty. False if it never empties."""
        for _ in range(limit):
            await _real_sleep(0)
            if self.ts.commands.empty() and self.ts.current is None:
                await _real_sleep(0)
                if self.ts.commands.empty() and self.ts.current is None:
                    return True
        return False

    async def call(self, name: str, **args):
        """Call a tool the way Gemini does, and let the queue run it."""
        res = await tools.call(self.ts, name, args)
        await self.settle()
        return res

    def outcomes(self, start: int = 0) -> list[str]:
        """What each queued job ended with, as the queue logged it."""
        out = []
        for r in self.records[start:]:
            msg = r.getMessage()
            if r.exc_info:
                exc = r.exc_info[1]
                msg += f" -- raised {type(exc).__name__}: {exc}"
            out.append(msg)
        return out

    def failures(self, start: int = 0) -> list[str]:
        return [r.getMessage() for r in self.records[start:] if r.levelno >= logging.WARNING]

    def imu(self, tilt_deg: float, spin: float = 0.0, seconds: float = 1.5) -> None:
        """Feed IMU readings: tilted tilt_deg about x, turning at spin rad/s."""
        h = math.radians(tilt_deg) / 2
        for _ in range(int(seconds * 100)):
            self.robot.send("/imu_sensor_broadcaster/imu", _Msg(
                orientation=_Quat(x=math.sin(h), w=math.cos(h)), angular_velocity=_Vec(x=spin)))
            self.clock.now += 0.01

    def close(self):
        self.ts.worker.cancel()


# ----------------------------------------------------------------------------- checks
PASS = FAIL = TODO = 0


def check(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name}" + (f": {detail}" if detail else ""))
    return ok


def unwritten(res) -> str | None:
    """'TODO n' if a result (or a check_move reason) says that TODO isn't written yet."""
    text = res.message if hasattr(res, "message") else str(res or "")
    m = re.search(r"(TODO \d+) is not written yet", text)
    return m.group(1) if m else None


def skip(what: str) -> None:
    global TODO
    TODO += 1
    print(f"  --   {what}")


def walk_twists(rig: Rig):
    return [m for _, m in rig.robot.twists() if abs(m.linear.x) + abs(m.linear.y) + abs(m.angular.z) > 1e-9]


def described(rig: Rig, names: list[str], todo: str) -> bool:
    """Check the declarations of some tools. False (and a skip) if one still says TODO."""
    decls = {d["name"]: d for d in tools.declarations(rig.ts)}
    missing = [n for n in names if n not in decls]
    if missing:
        check(f"tools.py declares {', '.join(names)}", False, f"missing {missing}; declared: {sorted(decls)}")
        return False
    if any("TODO" in json.dumps(decls[n]) for n in names):
        skip(f"{todo}: the descriptions of {', '.join(names)} still say TODO")
        return False
    for n in names:
        d = decls[n]
        check(f"{n} has a real description", len(d.get("description", "")) >= 20,
              f"description: {d.get('description')!r}")
        params = d.get("parameters", {}).get("properties", {})
        no_doc = [p for p, s in params.items() if len(s.get("description", "")) < 3]
        check(f"... and every parameter of {n} is described", not no_doc, f"missing: {no_doc}")
    return True


def system_prompt() -> str:
    text = (HERE / "prompt.md").read_text()
    return re.sub(r"<!--.*?-->", "", text, flags=re.S).strip()


# ----------------------------------------------------------------------------- Part 1
def prompt_sections(*headings: str) -> str:
    """The text under some of prompt.md's '# ' headings."""
    parts, keep = [], False
    for line in system_prompt().splitlines():
        if line.startswith("# "):
            keep = line[2:].strip().lower() in {h.lower() for h in headings}
        elif keep:
            parts.append(line)
    return "\n".join(parts).strip()


async def todo1() -> None:
    print("TODO 1: prompt.md, first pass")
    text = prompt_sections("Who you are", "How you move", "When a tool says no")
    if "TODO" in text or not text:
        skip("TODO 1: prompt.md still says TODO under its first three headings")
        return
    words = len(text.split())
    check("the prompt says who Pupper is and how it moves (at least 60 words)", words >= 60, f"{words} words")
    check("it tells Gemini it moves only by calling tools", "tool" in text.lower())


# ----------------------------------------------------------------------------- Part 2
async def todo2() -> None:
    print("TODO 2: check_move refuses what the robot can't or shouldn't do")
    probe = check_move(0.4, 0.0, 0.0, 2.0)
    if unwritten(probe):
        skip("TODO 2 (check_move) is not written yet")
        return
    L = LIMITS
    fine = [
        ("walk forward 0.4 m/s for 2 s", (0.4, 0.0, 0.0, 2.0)),
        ("walk backward 0.4 m/s for 2 s", (-0.4, 0.0, 0.0, 2.0)),
        ("sidestep 0.3 m/s", (0.0, 0.3, 0.0, 2.0)),
        ("turn in place 60 deg/s", (0.0, 0.0, 60.0, 1.5)),
        ("run 1.2 m/s for 4 s (4.8 m)", (1.2, 0.0, 0.0, 4.0)),
        ("the fastest allowed forward speed", (L.vx_max, 0.0, 0.0, 1.0)),
    ]
    for name, args in fine:
        got = check_move(*args)
        check(f"allows: {name}", got is None, f"check_move{args} refused it: {got!r}")
    bad = [
        ("forward faster than vx_max", (L.vx_max + 1.0, 0.0, 0.0, 1.0), str(L.vx_max)),
        ("backward faster than vx_max", (-(L.vx_max + 1.0), 0.0, 0.0, 1.0), str(L.vx_max)),
        ("sideways faster than vy_max", (0.0, L.vy_max + 0.3, 0.0, 1.0), str(L.vy_max)),
        ("turning faster than wz_max", (0.0, 0.0, L.wz_max + 50, 1.0), str(L.wz_max)),
        ("too slow to move at all", (0.05, 0.05, 5.0, 2.0), None),
        ("a zero duration", (0.4, 0.0, 0.0, 0.0), None),
        ("a negative duration", (0.4, 0.0, 0.0, -1.0), None),
        ("longer than duration_max", (0.4, 0.0, 0.0, L.duration_max + 1), str(L.duration_max)),
        ("farther than distance_max in one move", (1.5, 0.0, 0.0, 4.0), str(L.distance_max)),
    ]
    for name, args, limit in bad:
        got = check_move(*args)
        if check(f"refuses: {name}", isinstance(got, str) and got != "", f"check_move{args} returned {got!r}"):
            if limit is not None:
                check(f"  ... and the reason names the limit ({limit})", limit in got, f"reason was {got!r}")


async def todo3() -> None:
    print("TODO 3: walk sends the speed for the whole move, then stands still")
    rig = Rig()
    try:
        res = await behaviors.walk(rig.ts, 5.0, 0.0, 0.0, 1.0)
        if unwritten(res):
            skip(f"{unwritten(res)} is not written yet")
            return
        check("an impossible speed comes back as a failure", res.ok is False, f"got {res}")
        check("... with check_move's reason", "1.5" in res.message, f"got {res.message!r}")
        check("... and nothing was queued or published",
              rig.ts.commands.empty() and not rig.robot.twists(), f"published {len(rig.robot.twists())} commands")

        rig.robot.controllers[WALKING_CONTROLLER] = "inactive"  # lying down
        start = len(rig.records)
        res = await behaviors.walk(rig.ts, 0.4, 0.0, 0.0, 2.0)
        check("a good move is accepted right away (queued)", res.ok is True and "queued" in res.message, f"got {res}")
        if not await rig.settle():
            check("the queue finishes", False, "the move never ended")
            return
        crashed = [o for o in rig.outcomes(start) if "raised" in o]
        check("the job ran without crashing", not crashed, "; ".join(crashed))
        check("the walking policy took the legs", WALKING_CONTROLLER in rig.robot.active())
        twists = rig.robot.twists()
        moving = [m for _, m in twists if abs(m.linear.x) > 1e-6]
        check("it sent the forward speed", bool(moving) and all(abs(m.linear.x - 0.4) < 1e-6 for m in moving),
              f"forward speeds sent: {sorted({round(m.linear.x, 3) for m in moving})}")
        if twists:
            span = twists[-1][0] - twists[0][0]
            check("for about the requested 2 s", 1.8 <= span <= 2.5, f"commands spanned {span:.2f} s")
            gaps = [b[0] - a[0] for a, b in zip(twists, twists[1:])]
            check("often enough that cmd_vel_mux never drops it (every < 0.5 s)",
                  bool(gaps) and max(gaps) < 0.5, f"longest gap {max(gaps) if gaps else 'n/a'} s")
            last = twists[-1][1]
            check("and ends with a zero command (stand still)",
                  abs(last.linear.x) + abs(last.linear.y) + abs(last.angular.z) < 1e-9)
            check("at roughly LLM_CMD_RATE", len(twists) >= 0.8 * 2.0 * LLM_CMD_RATE, f"{len(twists)} commands in 2 s")
        check("the outcome (in the debug log) says what it did", any("moved" in o for o in rig.outcomes(start)),
              f"log: {rig.outcomes(start)}")
        rig.robot.published.clear()
        await behaviors.walk(rig.ts, 0.0, 0.0, 60.0, 1.0)
        await rig.settle()
        turns = [m for _, m in rig.robot.twists() if abs(m.angular.z) > 1e-6]
        check("a turn sends its turn rate in rad/s", bool(turns) and abs(turns[0].angular.z - 60 / 57.2958) < 1e-3,
              f"turn rates sent: {sorted({round(m.angular.z, 3) for m in turns})}")

        # Falling over in the middle of a walk.
        rig.robot.published.clear()
        start = len(rig.records)
        await behaviors.walk(rig.ts, 0.4, 0.0, 0.0, 4.0)
        t0 = rig.clock.now
        while rig.clock.now < t0 + 1.0:
            await _real_sleep(0)
        rig.ts.fallen = WALKING_CONTROLLER  # as if the tilt e-stop had just tripped
        await rig.settle()
        twists = rig.robot.twists()
        check("if the robot falls while walking, it stops sending the speed",
              bool(twists) and twists[-1][0] - t0 < 2.0, f"kept sending until {twists[-1][0] - t0 if twists else 0:.1f} s")
        check("... ends on a zero command", bool(twists) and abs(twists[-1][1].linear.x) < 1e-9)
        check("... and the outcome says it fell", any("fell" in o for o in rig.outcomes(start)),
              f"log: {rig.outcomes(start)}")
        res = await behaviors.walk(rig.ts, 0.4, 0.0, 0.0, 1.0)
        check("a walk asked for while fallen is refused right away, saying so",
              not res.ok and "fell" in res.message, f"got {res}")
    finally:
        rig.close()


async def todo4() -> None:
    print("TODO 4: the turn tool, then the move tool")
    rig = Rig()
    try:
        # turn first: the warm-up.
        described(rig, ["turn"], "TODO 4 (turn)")
        res = await rig.call("turn", direction="left", angle=90)
        if unwritten(res):
            skip(f"{unwritten(res)} is not written yet (the turn tool needs TODO 3 and TODO 4)")
            return
        twists = rig.robot.twists()
        yaw = sum(m.angular.z * (b[0] - a[0]) for (a, b), m in zip(zip(twists, twists[1:]), (t[1] for t in twists)))
        check("turn left turns counter-clockwise (+z)", any(m.angular.z > 0 for _, m in twists),
              f"result {res}; turn rates sent: {sorted({round(m.angular.z, 2) for _, m in twists})}")
        check("... by about the angle asked for (90 deg)", 70 <= math.degrees(yaw) <= 110,
              f"turned about {math.degrees(yaw):.0f} deg")
        check("... in place (no forward or sideways speed)",
              all(abs(m.linear.x) + abs(m.linear.y) < 1e-9 for _, m in twists))
        rig.robot.published.clear()
        await rig.call("turn", direction="right", angle=90)
        twists = rig.robot.twists()
        check("turn right turns clockwise (-z)", any(m.angular.z < 0 for _, m in twists),
              f"turn rates sent: {sorted({round(m.angular.z, 2) for _, m in twists})}")

        # move: the real challenge.
        if described(rig, ["move"], "TODO 4 (move)"):
            text = json.dumps({d["name"]: d for d in tools.declarations(rig.ts)}["move"])
            check("move's words give the real speed limit (LIMITS.vx_max)", str(LIMITS.vx_max) in text)
            check("... and say that it ends follow mode", "follow" in text.lower())
        rig.robot.published.clear()
        res = await rig.call("move", direction="forward", duration=1.0)
        if unwritten(res):
            skip(f"{unwritten(res)} is not written yet (the move tool)")
            return

        async def sent(**args):
            rig.robot.published.clear()
            res = await rig.call("move", duration=1.0, **args)
            return res, walk_twists(rig)

        res, ts = await sent(direction="forward")
        check('move("forward") walks forward at the default 0.4 m/s',
              bool(ts) and all(abs(m.linear.x - 0.4) < 1e-6 and abs(m.linear.y) < 1e-9 for m in ts),
              f"result {res}; sent vx {sorted({round(m.linear.x, 2) for m in ts})}")
        res, ts = await sent(direction="backward", speed=0.3)
        check('move("backward", speed=0.3) sends vx = -0.3', bool(ts) and all(abs(m.linear.x + 0.3) < 1e-6 for m in ts),
              f"sent vx {sorted({round(m.linear.x, 2) for m in ts})}")
        res, ts = await sent(direction="left", speed=0.3)
        check('move("left", speed=0.3) sends vy = +0.3 (the robot\'s left is +y)',
              bool(ts) and all(abs(m.linear.y - 0.3) < 1e-6 and abs(m.linear.x) < 1e-9 for m in ts),
              f"sent vy {sorted({round(m.linear.y, 2) for m in ts})}")
        res, ts = await sent(direction="backward", run=True)
        check('move("backward", run=True) runs at RUN_DEFAULT_SPEED (vx = -1.2)',
              bool(ts) and all(abs(m.linear.x + 1.2) < 1e-6 for m in ts), f"sent vx {sorted({round(m.linear.x, 2) for m in ts})}")
        res, ts = await sent(direction="forward", run=True, speed=0.6)
        check('move("forward", run=True, speed=0.6) still runs: at least 1.0 m/s',
              bool(ts) and min(m.linear.x for m in ts) >= 1.0 - 1e-9, f"sent vx {sorted({round(m.linear.x, 2) for m in ts})}")
        res, ts = await sent(direction="right", run=True)
        check('move("right", run=True) sidesteps at walking speed (vy = -0.4): sideways never runs',
              bool(ts) and all(abs(m.linear.y + 0.4) < 1e-6 for m in ts), f"result {res}; sent vy {sorted({round(m.linear.y, 2) for m in ts})}")
        res = await rig.call("move", direction="forward", speed=1.5, duration=10.0)
        check("a move the robot refuses comes back as a failure with the reason",
              res.ok is False and "m" in res.message, f"got {res}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- Part 3
async def todo5() -> None:
    print("TODO 5: any motion ends follow mode right away, and Gemini hears about it")
    rig = Rig()
    try:
        res = await rig.ts.set_following(True)
        await rig.settle()
        check("(provided) following starts", rig.ts.following and rig.robot.follower_on, f"got {res}")
        res = await behaviors.stand_up(rig.ts)
        stopped_now = not rig.ts.following and not rig.robot.follower_on
        if not stopped_now and rig.robot.follow_calls == ["on"] and "follow" not in res.message.lower():
            skip("TODO 5 (leave_follow_mode) is not written yet")
            return
        check("standing up ends follow mode right away (before the queue reaches it)", stopped_now)
        check("the tool result tells Gemini it stopped following", "follow" in res.message.lower(),
              f"result was {res.message!r}")
        await rig.settle()
        await rig.ts.set_following(True)
        await rig.settle()
        res = await behaviors.lie_down(rig.ts)
        check("lying down ends follow mode too", not rig.ts.following and not rig.robot.follower_on)
        check("... and says so", "follow" in res.message.lower(), f"result was {res.message!r}")
        await rig.settle()
        await rig.ts.set_following(True)
        await rig.settle()
        res = await behaviors.walk(rig.ts, 0.4, 0.0, 0.0, 1.0)
        if unwritten(res):
            print(f"  --   (skipping the walking case: {unwritten(res)} is not written yet)")
        else:
            check("walking ends follow mode", not rig.ts.following and not rig.robot.follower_on)
            check("... and says so", "follow" in res.message.lower(), f"result was {res.message!r}")
        await rig.settle()
        res = await behaviors.stand_up(rig.ts)
        check("with follow mode off, results don't mention following", "follow" not in res.message.lower(),
              f"result was {res.message!r}")
        await rig.settle()
        await rig.ts.set_following(True)
        await rig.settle()
        await rig.ts.mode()
        check("asking what mode it is in keeps following", rig.ts.following and rig.robot.follower_on)
    finally:
        rig.close()


async def todo6() -> None:
    print("TODO 6: the follow tool")
    rig = Rig()
    try:
        if described(rig, ["follow"], "TODO 6"):
            text = json.dumps({d["name"]: d for d in tools.declarations(rig.ts)}["follow"]).lower()
            check("follow's description says what ends follow mode", "end" in text or "stop" in text)
        follow_text = prompt_sections("Follow mode")
        if "TODO" in follow_text or not follow_text:
            skip("TODO 6: prompt.md still says TODO under Follow mode")
        else:
            check("the prompt's Follow mode section says what ends following", "end" in follow_text.lower()
                  or "stop" in follow_text.lower(), follow_text)
        res = await rig.call("follow", enabled=True)
        if unwritten(res):
            skip(f"{unwritten(res)} is not written yet")
            return
        check("follow(enabled=True) starts following", rig.robot.follower_on, f"got {res}")
        res = await rig.call("follow", enabled=False)
        check("follow(enabled=False) stops it", not rig.robot.follower_on, f"got {res}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- Part 4
async def todo7() -> None:
    print("TODO 7: play_trick (the fake tricks: bow, roll_over, hold_pose)")
    rig = Rig()
    try:
        res = await behaviors.play_trick(rig.ts, "backflip")
        await rig.settle()
        if unwritten(res):
            skip("TODO 7 (play_trick) is not written yet")
            return
        check("an unknown trick fails", not res.ok, f"got {res}")
        check("... and the message lists the tricks that exist", "bow" in res.message, f"got {res.message!r}")

        bow = rig.ts.tricks["bow"]
        start = len(rig.records)
        res = await behaviors.play_trick(rig.ts, "bow")
        check("a trick is accepted right away (queued)", res.ok and "queued" in res.message, f"got {res}")
        await rig.settle()
        if any(unwritten(_Msg(message=o)) for o in rig.outcomes(start)):
            skip("TODO 7 (play_policy_trick, the job) is not written yet")
            return
        on, off = rig.robot.activations(bow.controller), rig.robot.deactivations(bow.controller)
        check("the trick's controller took the legs", bool(on), f"switches: {rig.robot.switches}")
        check("... for the whole trick (trick.total_time)", bool(on and off) and off[-1] - on[-1] >= bow.total_time,
              f"held it {off[-1] - on[-1] if on and off else 0:.1f} s of {bow.total_time:.1f} s")
        check("a trick that ends standing hands the legs back to walking",
              WALKING_CONTROLLER in rig.robot.active() and bow.controller not in rig.robot.active(),
              f"active: {sorted(rig.robot.active())}")
        check("... and the outcome says so", any("walk" in o for o in rig.outcomes(start)), f"log: {rig.outcomes(start)}")

        roll = rig.ts.tricks["roll_over"]
        start = len(rig.records)
        await behaviors.play_trick(rig.ts, "roll_over")
        await rig.settle()
        check("a trick that ends lying down keeps its controller holding the pose",
              roll.controller in rig.robot.active() and WALKING_CONTROLLER not in rig.robot.active(),
              f"active: {sorted(rig.robot.active())}")
        check("... and the outcome says it holds the final pose",
              any("hold" in o or "pose" in o for o in rig.outcomes(start)), f"log: {rig.outcomes(start)}")
        n_on = len(rig.robot.activations(roll.controller))
        await behaviors.play_trick(rig.ts, "roll_over")
        await rig.settle()
        check("playing it again restarts its controller (relax, then switch to it)",
              len(rig.robot.activations(roll.controller)) == n_on + 1 and len(rig.robot.deactivations(roll.controller)) >= 1,
              f"switches: {rig.robot.switches[-3:]}")

        hold = rig.ts.tricks["hold_pose"]
        start = len(rig.records)
        res = await behaviors.play_trick(rig.ts, "hold_pose")
        await rig.settle()
        check("a clip trick ends holding its pose", hold.controller in rig.robot.active() and rig.ts.holding_now is hold,
              f"active: {sorted(rig.robot.active())}; holding_now: {rig.ts.holding_now}")
        out = " ".join(rig.outcomes(start))
        check("... and the outcome lists its actions and its exit clip", "wave_left" in out and "leave" in out,
              f"log: {rig.outcomes(start)}")
        n_switches = len(rig.robot.switches)
        start = len(rig.records)
        await behaviors.play_trick(rig.ts, "hold_pose")
        await rig.settle()
        check("asking for the clip trick it is already holding does nothing, and says so",
              len(rig.robot.switches) == n_switches and any("already" in o for o in rig.outcomes(start)),
              f"log: {rig.outcomes(start)}")

    finally:
        rig.close()

    rig = Rig()
    try:
        await rig.ts.set_following(True)
        await rig.settle()
        res = await behaviors.play_trick(rig.ts, "bow")
        await rig.settle()
        check("a trick ends follow mode (TODO 5's rule)", not rig.ts.following and "follow" in res.message.lower(),
              f"got {res}")
    finally:
        rig.close()


async def todo8() -> None:
    print("TODO 8: the play_trick tool")
    rig = Rig()
    try:
        if not described(rig, ["play_trick"], "TODO 8"):
            return
        decl = {d["name"]: d for d in tools.declarations(rig.ts)}["play_trick"]
        check("its description lists every trick with its own description ({tricks})",
              all(t.description in decl["description"] for t in rig.ts.tricks.values()), decl["description"])
        params = decl.get("parameters", {}).get("properties", {})
        enums = [v for p in params.values() for v in p.get("enum", [])]
        check("its choices are the installed tricks", set(rig.ts.tricks) <= set(enums), f"choices: {enums}")
        check("... and it says a trick keeps its final pose",
              "pose" in decl["description"].lower(), decl["description"])
    finally:
        rig.close()


async def optional_jump() -> None:
    print("Optional: the jump (the fake reference trick 'hop')")
    rig = Rig()
    try:
        res = await behaviors.play_trick(rig.ts, "hop")
        await rig.settle()
        if unwritten(res):
            skip("TODO 7 (play_trick) is not written yet")
            return
        refs = [m for _, topic, m in rig.robot.published if topic.endswith("/reference_trick")]
        check("a reference trick plays through the walking policy (robot.play_reference_trick)",
              bool(refs) and WALKING_CONTROLLER in rig.robot.active(),
              f"got {res}; log: {rig.outcomes()}; active: {sorted(rig.robot.active())}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- Part 5
async def todo9() -> None:
    print("TODO 9: trick actions (the fake clip trick 'hold_pose': wave_left, wave_right, leave)")
    rig = Rig()
    try:
        ctrl = rig.ts.tricks["hold_pose"].controller
        res = await behaviors.trick_action(rig.ts, "wave_left")
        await rig.settle()
        if unwritten(res):
            skip("TODO 9 (trick_action) is not written yet")
            return
        probe = await behaviors.play_trick(rig.ts, "bow")
        await rig.settle()
        if unwritten(probe) or any(unwritten(_Msg(message=o)) for o in rig.outcomes()):
            skip("these checks need TODO 7 (play_trick) first")
            return

        start = len(rig.records)
        res = await behaviors.trick_action(rig.ts, "fetch_the_ball")
        await rig.settle()
        fails = ([] if res.ok else [res.message]) + rig.failures(start)
        check("an unknown action fails", bool(fails), f"got {res}")
        check("... and the message lists the actions that exist", any("wave_left" in f for f in fails),
              f"messages: {fails}")

        start = len(rig.records)
        rig.robot.published.clear()
        res = await behaviors.trick_action(rig.ts, "wave_left")  # hold_pose is not running
        await rig.settle()
        check("an action while its trick is not running fails right away", not res.ok, f"got {res}")
        check("... the message says which trick has to run first", "hold_pose" in res.message, f"got {res.message!r}")
        check("... and nothing was sent to the trick", not rig.robot.clips(ctrl))

        await behaviors.play_trick(rig.ts, "hold_pose")
        await rig.settle()
        start = len(rig.records)
        res = await behaviors.trick_action(rig.ts, "wave_left")
        await rig.settle()
        check("an action while the trick holds its pose is accepted", res.ok, f"got {res}")
        check("... and plays that clip", rig.robot.clips(ctrl)[-1:] == ["wave_left"], f"clips sent: {rig.robot.clips(ctrl)}")
        check("... without a failure in the queue", not rig.failures(start), f"{rig.failures(start)}")
        check("... and the trick keeps holding its pose afterwards",
              ctrl in rig.robot.active() and WALKING_CONTROLLER not in rig.robot.active())

        await behaviors.trick_action(rig.ts, "leave")
        await rig.settle()
        check("the exit clip plays", rig.robot.clips(ctrl)[-1:] == ["leave"], f"clips sent: {rig.robot.clips(ctrl)}")
        check("... then the walking policy takes the legs back",
              WALKING_CONTROLLER in rig.robot.active() and ctrl not in rig.robot.active(),
              f"active: {sorted(rig.robot.active())}")
        check("... and nothing is holding a pose any more", rig.ts.holding_now is None)
        res = await behaviors.trick_action(rig.ts, "wave_left")
        check("after the exit clip, actions are refused again", not res.ok, f"got {res}")
    finally:
        rig.close()

    rig = Rig()
    try:
        ctrl = rig.ts.tricks["hold_pose"].controller
        # "Sit and give me your paw", in one breath: two tool calls, back to back.
        await behaviors.play_trick(rig.ts, "hold_pose")
        start = len(rig.records)
        res = await behaviors.trick_action(rig.ts, "wave_right")
        await rig.settle()
        check("an action queued right behind its trick is accepted and plays",
              res.ok and "wave_right" in rig.robot.clips(ctrl),
              f"result {res}; queue: {rig.failures(start)}; clips sent: {rig.robot.clips(ctrl)}")

        # Queued behind the trick, but the trick was relaxed before the queue got there.
        await behaviors.play_trick(rig.ts, "hold_pose")
        await rig.settle()
        await behaviors.lie_down(rig.ts)  # queued: relaxes the motors
        rig.ts.holding_after_queue = rig.ts.tricks["hold_pose"]  # as if it were still coming
        rig.robot.published.clear()
        start = len(rig.records)
        res = await behaviors.trick_action(rig.ts, "wave_left")
        await rig.settle()
        check("when the queue gets to an action, it checks again that its trick is running",
              not rig.robot.clips(ctrl) and bool(rig.failures(start)),
              f"clips sent: {rig.robot.clips(ctrl)}; log: {rig.outcomes(start)}")
    finally:
        rig.close()


async def todo10() -> None:
    print("TODO 10: the trick_action tool")
    rig = Rig()
    try:
        if described(rig, ["trick_action"], "TODO 10"):
            decl = {d["name"]: d for d in tools.declarations(rig.ts)}["trick_action"]
            check("its description lists the actions ({actions})", "Waves the left paw." in decl["description"],
                  decl["description"])
            params = decl.get("parameters", {}).get("properties", {})
            enums = [v for p in params.values() for v in p.get("enum", [])]
            check("its choices are the installed actions", {"wave_left", "wave_right", "leave"} <= set(enums),
                  f"choices: {enums}")
        ctrl = rig.ts.tricks["hold_pose"].controller
        await behaviors.play_trick(rig.ts, "hold_pose")
        await rig.settle()
        res = await rig.call("trick_action", action="wave_left")
        if unwritten(res):
            skip(f"{unwritten(res)} is not written yet")
            return
        check("calling the trick_action tool plays the clip", res.ok and rig.robot.clips(ctrl)[-1:] == ["wave_left"],
              f"result {res}; clips sent: {rig.robot.clips(ctrl)}")
    finally:
        rig.close()
    shake = HERE.parent / "tricks" / "sit_stay_shake" / "trick.yaml"
    if shake.exists():
        import yaml

        spec = yaml.safe_load(shake.read_text()) or {}
        text = json.dumps(spec)
        if "TODO" in text:
            skip("TODO 10: tricks/sit_stay_shake/trick.yaml still says TODO")
        else:
            check("sit_stay_shake/trick.yaml describes the trick", len(str(spec.get("description", ""))) >= 20)
            check("... and each of its actions", all(len(str(v)) >= 10 for v in (spec.get("actions") or {}).values())
                  and bool(spec.get("actions")), f"actions: {spec.get('actions')}")
    else:
        print("  --   (no tricks/sit_stay_shake yet: fetch your policy with get_trick.py, Part 5)")


# ----------------------------------------------------------------------------- Part 6
async def todo11() -> None:
    print("TODO 11: prompt.md, second pass")
    text = prompt_sections("Tricks", "Safety").lower()
    if "todo" in text or not text:
        skip("TODO 11: prompt.md still says TODO under Tricks or Safety")
        return
    check("the prompt says what to do when someone says stop", "stop" in text)
    check("... and when Pupper falls over", "fall" in text or "fell" in text)
    check("... and how to handle several requests in a row", "order" in text or "row" in text or "sequence" in text)


# ----------------------------------------------------------------------------- provided
async def provided() -> None:
    print("The provided robot (these should pass before you change anything)")
    rig = Rig()
    try:
        bad = await tools.call(rig.ts, "stand_up", {"speed": 3})
        check("a tool call with a parameter the tool doesn't have is refused", not bad.ok, f"got {bad}")
        bad = await tools.call(rig.ts, "play_trick", {"name": "backflip"})
        check("a value outside a tool's choices is refused, listing the choices",
              not bad.ok and "bow" in bad.message, f"got {bad}")

        rig.robot.controllers[WALKING_CONTROLLER] = "inactive"
        rig.ts.walk_since = None
        await behaviors.stand_up(rig.ts)
        on_at = rig.clock.now
        await rig.settle()
        check("stand_up hands the legs to the walking policy", WALKING_CONTROLLER in rig.robot.active())
        check("... and waits until the policy is ready before the next job starts",
              rig.clock.now - on_at >= WALK_READY_S - 0.01, f"ready after {rig.clock.now - on_at:.2f} s")
        await behaviors.lie_down(rig.ts)
        await rig.settle()
        check("lie_down relaxes every leg controller", not (rig.robot.active() & rig.ts.leg_controllers),
              f"active: {sorted(rig.robot.active())}")
        await behaviors.stand_up(rig.ts)
        await rig.settle()

        # A tilt e-stop: the controller says so on /rosout.
        rig.robot.send("/rosout", _Msg(name="gemini_walk", msg=robot_api.ESTOP_LOG))
        await rig.settle()
        res = await tools.call(rig.ts, "robot_status", {})
        check("after a fall, robot_status says it fell over", "fall" in res.message.lower() or "fell" in res.message.lower(),
              f"got {res.message!r}")
        rig.imu(tilt_deg=70)
        res = await rig.ts.switch_to(WALKING_CONTROLLER)
        check("standing up while still tipped over is refused, asking for help",
              not res.ok and "upright" in res.message, f"got {res}")
        rig.imu(tilt_deg=3)
        res = await rig.ts.switch_to(WALKING_CONTROLLER)
        check("once upright and still, standing up works again", res.ok and rig.ts.fallen is None, f"got {res}")

        await rig.ts.wait(5.0)
        res = await tools.call(rig.ts, "stop", {})
        check("stop clears the queue", rig.ts.commands.empty() and "stopped" in res.message, f"got {res}")
    finally:
        rig.close()

    # The server restarted while the robot sat in a clip trick.
    rig = Rig()
    try:
        hold = fixture_tricks()["hold_pose"]
        rig.robot.controllers[WALKING_CONTROLLER] = "inactive"
        rig.robot.controllers[hold.controller] = "active"
        rig.ts.worker.cancel()
        rig.ts = Robot()  # a fresh server, the robot still sitting
        await rig.settle()
        check("a restarted server notices the robot is still holding a clip trick's pose",
              rig.ts.holding_now is not None and rig.ts.holding_now.name == "hold_pose", f"holding_now: {rig.ts.holding_now}")
        await behaviors.stand_up(rig.ts)
        await rig.settle()
        check("... so standing up plays the trick's exit clip first",
              rig.robot.clips(hold.controller)[-1:] == ["leave"] and WALKING_CONTROLLER in rig.robot.active(),
              f"clips sent: {rig.robot.clips(hold.controller)}; active: {sorted(rig.robot.active())}")
    finally:
        rig.close()

    def no_clip_tricks():
        return {k: v for k, v in fixture_tricks().items() if not v.clips}

    rig = Rig(no_clip_tricks)
    try:
        decls = {d["name"]: d for d in tools.declarations(rig.ts)}
        check("trick_action is offered to Gemini even before a clip trick is installed", "trick_action" in decls,
              f"declared: {sorted(decls)}")
        res = await tools.call(rig.ts, "trick_action", {"action": "shake_left"})
        check("... and says nothing is installed yet", not res.ok and "installed" in res.message, f"got {res}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- main
GROUPS = {
    "todo1": todo1, "todo2": todo2, "todo3": todo3, "todo4": todo4, "todo5": todo5, "todo6": todo6,
    "todo7": todo7, "todo8": todo8, "todo9": todo9, "todo10": todo10, "todo11": todo11, "robot": provided,
    "optional_jump": optional_jump,
}
OPT_IN = {"optional_jump"}  # run only when asked for by name
PARTS = {
    "part1": ["todo1"],
    "part2": ["todo2", "todo3", "todo4"],
    "part3": ["todo5", "todo6"],
    "part4": ["todo7", "todo8"],
    "part5": ["todo9", "todo10"],
    "part6": ["todo11"],
}


def main() -> None:
    chosen: list[str] = []
    for arg in sys.argv[1:] or ["robot", *(g for g in GROUPS if g not in OPT_IN)]:
        for name in PARTS.get(arg, [arg]):
            if name not in GROUPS:
                sys.exit(f"unknown test group {arg!r}; choose from {list(GROUPS)} or {list(PARTS)}")
            if name not in chosen:
                chosen.append(name)
    for name in chosen:
        asyncio.run(GROUPS[name]())
        print()
    if FAIL:
        print(f"{FAIL} check(s) failed, {PASS} passed.")
        raise SystemExit(1)
    if TODO:
        print(f"All {PASS} checks that ran passed; {TODO} TODO(s) not written yet. Keep going!")
        raise SystemExit(1)
    print(f"All {PASS} checks passed. Now try it on the robot (with a TA's OK for new policies).")


if __name__ == "__main__":
    main()
