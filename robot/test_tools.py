#!/usr/bin/env python3
"""Desk tests for Gemini's tools: no robot, no ROS, no Gemini needed.

Run them after every change to robot/tools.py or robot/tool_server.py:

    python3 robot/test_tools.py            # everything
    python3 robot/test_tools.py part1      # just one part: part1, part2 or robot

A fake robot stands in for ROS. It keeps track of which controllers are on,
records every message the tool server sends, and plays trick clips instantly.
Time is fake too, so a 10 s walk takes no real time.

The tests check what each tool does and what Gemini is told, not how you wrote
the code. When a test fails, it prints what was asked and what happened.

Passing these tests does not mean the robot is ready. That is what the real
Pupper, the e-stop and a TA are for.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sys
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
        self.subs: dict[str, list] = {}
        self.follower_on = False
        self.follow_calls: list[str] = []

    def active(self) -> set[str]:
        return {n for n, s in self.controllers.items() if s == "active"}

    def twists(self) -> list[tuple[float, _Twist]]:
        return [(t, m) for t, topic, m in self.published if topic == "/llm_cmd_vel"]

    def clips(self, controller: str) -> list[str]:
        return [m.data for _, topic, m in self.published if topic == f"/{controller}/clip"]

    def send(self, topic: str, msg) -> None:
        """Deliver a message to the tool server's subscribers."""
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
import tool_server  # noqa: E402
import tools  # noqa: E402
from tool_server import LIMITS, LLM_CMD_RATE, WALK_READY_S, WALKING_CONTROLLER, ToolServer, check_move  # noqa: E402
from tricks import Trick  # noqa: E402

_real_sleep = asyncio.sleep


class VirtualClock:
    """tool_server's time.monotonic() and asyncio.sleep(), with no real waiting."""

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


def fixture_tricks() -> dict[str, Trick]:
    """Made-up tricks: a one-motion policy, and a clip trick that holds a pose.
    Clip lengths are in frames at 50 fps."""
    return {
        "bow": Trick(name="bow", description="Bows.", kind="policy", path=Path("bow.json"), duration=4.0),
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
    }


class Rig:
    """A fresh ToolServer wired to a fresh fake robot, standing on the walking policy."""

    def __init__(self):
        global ROBOT
        self.clock = VirtualClock()
        ROBOT = self.robot = FakeRobot(self.clock)
        tool_server.time = types.SimpleNamespace(monotonic=self.clock.monotonic)
        tool_server.asyncio = _AsyncioShim(self.clock)
        tool_server.load_tricks = fixture_tricks
        names = set(tool_server.LEG_CONTROLLERS) | {t.controller for t in fixture_tricks().values()}
        self.robot.controllers = {n: "inactive" for n in names}
        self.robot.controllers[WALKING_CONTROLLER] = "active"
        self.records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = self.records.append
        for name in ("tool_server", "tools"):
            lg = logging.getLogger(name)
            lg.handlers[:] = [handler]
            lg.setLevel(logging.INFO)
            lg.propagate = False
        self.ts = ToolServer()

    async def settle(self, limit: int = 200_000) -> bool:
        """Let the command queue run until it is empty. False if it never empties."""
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

    def outcomes(self) -> list[str]:
        """What each queued command ended with, as the queue logged it."""
        out = []
        for r in self.records:
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


def not_implemented(res) -> bool:
    text = res.message if hasattr(res, "message") else str(res or "")
    return "not implemented yet" in text


def skip_part(what: str) -> None:
    global TODO
    TODO += 1
    print(f"  --   {what} is not implemented yet; skipping the rest of this part")


def walk_twists(rig: Rig):
    return [m for _, m in rig.robot.twists() if abs(m.linear.x) + abs(m.linear.y) + abs(m.angular.z) > 1e-9]


# ----------------------------------------------------------------------------- part 1
async def part1() -> None:
    await part1a()
    await part1b()
    await part1c()
    await part1d()


async def part1a() -> None:
    print("Part 1a: check_move refuses what the robot can't or shouldn't do")
    probe = check_move(0.4, 0.0, 0.0, 2.0)
    if probe and "not implemented yet" in probe:
        skip_part("check_move")
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
        ("longer than duration_max", (0.4, 0.0, 0.0, L.duration_max + 1), None),
        ("farther than distance_max in one move", (1.5, 0.0, 0.0, 4.0), None),
    ]
    for name, args, limit in bad:
        got = check_move(*args)
        if check(f"refuses: {name}", isinstance(got, str) and got != "", f"check_move{args} returned {got!r}"):
            if limit is not None:
                check(f"  ... and the reason names the limit ({limit})", limit in got, f"reason was {got!r}")


async def part1b() -> None:
    print("Part 1b: the robot side of move walks, then stands still")
    rig = Rig()
    try:
        res = await rig.ts.move(5.0, 0.0, 0.0, 1.0)
        check("an impossible speed comes back as a failure", res.ok is False, f"got {res}")
        check("... and nothing was queued or published",
              rig.ts.commands.empty() and not rig.robot.twists(), f"published {len(rig.robot.twists())} commands")
        if not_implemented(res):
            skip_part("move")
            return
        rig.robot.controllers[WALKING_CONTROLLER] = "inactive"  # lying down
        res = await rig.ts.move(0.4, 0.0, 0.0, 2.0)
        check("a good move is accepted", res.ok is True, f"got {res}")
        if not await rig.settle():
            check("the queue finishes", False, "the move never ended")
            return
        crashed = [o for o in rig.outcomes() if "raised" in o]
        if crashed and "NotImplementedError" in crashed[0]:
            skip_part("move's walking loop")
            return
        check("the move ran without crashing", not crashed, "; ".join(crashed))
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
        rig.robot.published.clear()
        await rig.ts.move(0.0, 0.0, 60.0, 1.0)
        await rig.settle()
        turns = [m for _, m in rig.robot.twists() if abs(m.angular.z) > 1e-6]
        check("a turn sends its turn rate in rad/s", bool(turns) and abs(turns[0].angular.z - 60 / 57.2958) < 1e-3,
              f"turn rates sent: {sorted({round(m.angular.z, 3) for m in turns})}")
    finally:
        rig.close()


async def part1c() -> None:
    print("Part 1c: follow mode ends on motion, and Gemini hears about it")
    rig = Rig()
    try:
        res = await rig.ts.set_following(True)
        await rig.settle()
        check("(provided) following starts", rig.ts.following and rig.robot.follower_on, f"got {res}")
        res = await rig.ts.activate_walking()
        stopped_now = not rig.ts.following and not rig.robot.follower_on
        if not stopped_now and rig.robot.follow_calls == ["on"] and "follow" not in res.message.lower():
            skip_part("_leave_follow_mode")
            return
        check("standing up ends follow mode right away (before the queue reaches it)", stopped_now)
        check("the tool result tells Gemini it stopped following", "follow" in res.message.lower(),
              f"result was {res.message!r}")
        await rig.settle()
        await rig.ts.set_following(True)
        await rig.settle()
        res = await rig.ts.deactivate()
        check("lying down ends follow mode too", not rig.ts.following and not rig.robot.follower_on)
        check("... and says so", "follow" in res.message.lower(), f"result was {res.message!r}")
        await rig.settle()
        await rig.ts.set_following(True)
        await rig.settle()
        res = await rig.ts.move(0.4, 0.0, 0.0, 1.0)
        if not_implemented(res):
            print("  --   (skipping the walking case: move is not implemented yet)")
        else:
            check("walking ends follow mode", not rig.ts.following and not rig.robot.follower_on)
            check("... and says so", "follow" in res.message.lower(), f"result was {res.message!r}")
        await rig.settle()
        res = await rig.ts.activate_walking()
        check("with follow mode off, results don't mention following", "follow" not in res.message.lower(),
              f"result was {res.message!r}")
        await rig.settle()
        await rig.ts.set_following(True)
        await rig.settle()
        await rig.ts.mode()
        check("asking what mode it is in keeps following", rig.ts.following and rig.robot.follower_on)
    finally:
        rig.close()


async def part1d() -> None:
    print("Part 1d: your motion tools in tools.py (move, turn, follow)")
    rig = Rig()
    try:
        decls = {d["name"]: d for d in tools.declarations(rig.ts)}
        for name in ("move", "turn", "follow"):
            if name not in decls:
                check(f"tools.py declares {name}", False, f"declared: {sorted(decls)}")
        todo = sorted({n for n, d in decls.items() if "TODO" in str(d)})
        if todo:
            global TODO
            TODO += 1
            print(f"  --   descriptions still say TODO in: {todo}")
        else:
            bare = [n for n, d in decls.items() if len(d.get("description", "")) < 20]
            check("every tool has a real description", not bare, f"too short or empty: {bare}")
            no_doc = [f"{n}.{p}" for n, d in decls.items()
                      for p, s in d.get("parameters", {}).get("properties", {}).items() if not s.get("description")]
            check("every parameter has a description", not no_doc, f"missing: {no_doc}")
        if "move" not in decls:
            return

        res = await rig.call("move", direction="forward", speed=0.4, duration=1.0)
        if not_implemented(res):
            skip_part("the move tool")
            return
        sent = walk_twists(rig)
        check("move forward sends +x", bool(sent) and all(m.linear.x > 0 and abs(m.linear.y) < 1e-9 for m in sent),
              f"result {res}; sent {[(round(m.linear.x, 2), round(m.linear.y, 2)) for m in sent[:3]]}")
        rig.robot.published.clear()
        await rig.call("move", direction="left", speed=0.3, duration=1.0)
        sent = walk_twists(rig)
        check("move left sends +y (the robot's left)", bool(sent) and all(m.linear.y > 0 for m in sent),
              f"y speeds sent: {sorted({round(m.linear.y, 2) for m in sent})}")
        rig.robot.published.clear()
        res = await rig.call("move", direction="forward", run=True, speed=0.6, duration=1.0)
        sent = walk_twists(rig)
        check("run means at least 1.0 m/s, even if a slower speed is asked for",
              bool(sent) and min(m.linear.x for m in sent) >= 1.0 - 1e-9,
              f"result {res}; forward speeds sent: {sorted({round(m.linear.x, 2) for m in sent})}")
        res = await rig.call("move", direction="forward", speed=1.5, duration=10.0)
        check("a move the robot refuses comes back as a failure with the reason",
              res.ok is False and "m" in res.message, f"got {res}")

        if "turn" in decls:
            rig.robot.published.clear()
            res = await rig.call("turn", direction="left", angle=90)
            twists = rig.robot.twists()
            yaw = sum(m.angular.z * (b[0] - a[0]) for (a, b), m in
                      zip(zip(twists, twists[1:]), (t[1] for t in twists)))
            check("turn left turns counter-clockwise (+z)", any(m.angular.z > 0 for _, m in twists),
                  f"result {res}; turn rates sent: {sorted({round(m.angular.z, 2) for _, m in twists})}")
            check("... by about the angle asked for (90 deg)", 70 <= math.degrees(yaw) <= 110,
                  f"turned about {math.degrees(yaw):.0f} deg")

        if "follow" in decls:
            res = await rig.call("follow", enabled=True)
            check("follow(enabled=True) starts following", rig.robot.follower_on, f"got {res}")
            res = await rig.call("follow", enabled=False)
            check("follow(enabled=False) stops it", not rig.robot.follower_on, f"got {res}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- part 2
async def part2() -> None:
    print("Part 2: trick actions (the fake clip trick 'hold_pose': wave_left, wave_right, leave)")
    rig = Rig()
    try:
        ctrl = rig.ts.tricks["hold_pose"].controller
        res = await rig.ts.trick_action("wave_left")
        await rig.settle()
        if not_implemented(res):
            skip_part("trick_action")
            return

        start = len(rig.records)
        res = await rig.ts.trick_action("fetch_the_ball")
        await rig.settle()
        fails = ([] if res.ok else [res.message]) + rig.failures(start)
        check("an unknown action fails", bool(fails), f"got {res}")
        check("... and the message lists the actions that exist", any("wave_left" in f for f in fails),
              f"messages: {fails}")

        start = len(rig.records)
        rig.robot.published.clear()
        res = await rig.ts.trick_action("wave_left")  # hold_pose is not running
        await rig.settle()
        fails = ([] if res.ok else [res.message]) + rig.failures(start)
        check("an action while its trick is not running fails", bool(fails), f"got {res}")
        check("... the message says which trick has to run first", any("hold_pose" in f for f in fails),
              f"messages: {fails}")
        check("... and nothing was sent to the trick", not rig.robot.clips(ctrl))

        await rig.ts.trick("hold_pose")
        await rig.settle()
        check("(provided) playing the trick leaves it holding its pose",
              ctrl in rig.robot.active() and rig.ts.clip_trick is rig.ts.tricks["hold_pose"])
        start = len(rig.records)
        res = await rig.ts.trick_action("wave_left")
        await rig.settle()
        check("an action while the trick holds its pose is accepted", res.ok, f"got {res}")
        check("... and plays that clip", rig.robot.clips(ctrl)[-1:] == ["wave_left"], f"clips sent: {rig.robot.clips(ctrl)}")
        check("... without a failure in the queue", not rig.failures(start), f"{rig.failures(start)}")
        check("... and the trick keeps holding its pose afterwards",
              ctrl in rig.robot.active() and WALKING_CONTROLLER not in rig.robot.active())

        await rig.ts.trick_action("leave")
        await rig.settle()
        check("the exit clip plays", rig.robot.clips(ctrl)[-1:] == ["leave"], f"clips sent: {rig.robot.clips(ctrl)}")
        check("... then the walking policy takes the legs back",
              WALKING_CONTROLLER in rig.robot.active() and ctrl not in rig.robot.active(),
              f"active: {sorted(rig.robot.active())}")
        check("... and nothing is holding a pose any more", rig.ts.clip_trick is None)
    finally:
        rig.close()

    rig = Rig()
    try:
        ctrl = rig.ts.tricks["hold_pose"].controller
        # "Sit and give me your paw", in one breath: two tool calls, back to back.
        await rig.ts.trick("hold_pose")
        start = len(rig.records)
        res = await rig.ts.trick_action("wave_right")
        await rig.settle()
        check("an action queued right behind its trick is accepted and plays",
              res.ok and "wave_right" in rig.robot.clips(ctrl),
              f"result {res}; queue: {rig.failures(start)}; clips sent: {rig.robot.clips(ctrl)}")

        decls = {d["name"]: d for d in tools.declarations(rig.ts)}
        if "trick_action" not in decls:
            check("tools.py declares trick_action", False, f"declared: {sorted(decls)}")
            return
        params = decls["trick_action"].get("parameters", {}).get("properties", {})
        enums = [v for p in params.values() for v in p.get("enum", [])]
        check("trick_action's choices are the installed actions",
              {"wave_left", "wave_right", "leave"} <= set(enums), f"choices: {enums}")
        arg = next(iter(params), None)
        res = await rig.call("trick_action", **{arg: "wave_left"}) if arg else None
        check("calling the trick_action tool plays the clip", bool(res and res.ok)
              and rig.robot.clips(ctrl)[-1:] == ["wave_left"], f"result {res}; clips sent: {rig.robot.clips(ctrl)}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- provided
async def provided() -> None:
    print("Provided robot behaviour (these should pass before you change anything)")
    rig = Rig()
    try:
        bad = await tools.call(rig.ts, "stand_up", {"speed": 3})
        check("a tool call with a parameter the tool doesn't have is refused", not bad.ok, f"got {bad}")
        bad = await tools.call(rig.ts, "play_trick", {"name": "backflip"})
        check("a value outside a tool's choices is refused, listing the choices",
              not bad.ok and "bow" in bad.message, f"got {bad}")

        rig.robot.controllers[WALKING_CONTROLLER] = "inactive"
        rig.ts.walk_since = None
        await rig.ts.activate_walking()
        await rig.ts.move(0.4, 0.0, 0.0, 1.0)
        on_at = rig.clock.now
        await rig.settle()
        first = rig.robot.twists()[0][0] if rig.robot.twists() else None
        if first is not None:
            check("stand_up waits for the walking policy before the next command walks",
                  first - on_at >= WALK_READY_S - 0.01, f"walked {first - on_at:.2f} s after stand-up")

        # A tilt e-stop: the controller says so on /rosout.
        rig.robot.send("/rosout", _Msg(name="gemini_walk", msg=tool_server.ESTOP_LOG))
        await rig.settle()
        res = await tools.call(rig.ts, "robot_status", {})
        check("after a fall, robot_status says it fell over", "fall" in res.message.lower() or "fell" in res.message.lower(),
              f"got {res.message!r}")
        res = await rig.ts.move(0.4, 0.0, 0.0, 1.0)
        check("after a fall, moves are refused", not res.ok, f"got {res}")
        rig.imu(tilt_deg=70)
        res = await rig.ts._use(WALKING_CONTROLLER)
        check("standing up while still tipped over is refused, asking for help",
              not res.ok and "upright" in res.message, f"got {res}")
        rig.imu(tilt_deg=3)
        res = await rig.ts._use(WALKING_CONTROLLER)
        check("once upright and still, standing up works again", res.ok and rig.ts.fallen is None, f"got {res}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- main
PARTS = {"part1": part1, "part2": part2, "robot": provided}


def main() -> None:
    chosen = sys.argv[1:] or list(PARTS)
    unknown = [p for p in chosen if p not in PARTS]
    if unknown:
        sys.exit(f"unknown part {unknown}; choose from {list(PARTS)}")
    for name in chosen:
        asyncio.run(PARTS[name]())
        print()
    if FAIL:
        print(f"{FAIL} check(s) failed, {PASS} passed.")
        raise SystemExit(1)
    if TODO:
        print(f"All {PASS} checks that ran passed; {TODO} piece(s) not implemented yet. Keep going!")
        raise SystemExit(1)
    print(f"All {PASS} checks passed. Now try it on the robot (with a TA's OK for new policies).")


if __name__ == "__main__":
    main()
