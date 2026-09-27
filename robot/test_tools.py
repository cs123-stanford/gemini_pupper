#!/usr/bin/env python3
"""Desk-side contract tests for the tool layer: no robot, no ROS, no Gemini.

Run them after every change to robot/tool_server.py (your coding agent can too):

    python3 robot/test_tools.py            # all parts
    python3 robot/test_tools.py part1      # just one: part1, part2 or part3

A fake robot stands in for ROS. It keeps a table of controllers and their
states, records every message the tool server publishes, answers the person
follower's services, and plays trick clips instantly -- but only when the
trick's controller is actually active, like the real one. Time is virtual, so
a 10 s walk takes no real time.

The tests check the *contract* of each tool -- what the robot does and what
Gemini is told -- not how you wrote it. The fake tricks here are made up
(hold_pose, dance); they don't need your trained policies. When a test fails,
the printout says what was asked and what happened.

Passing these tests means your tool layer keeps its promises. It does not mean
the robot is ready: that is what the real Pupper, the e-stop and a TA are for.
"""

from __future__ import annotations

import asyncio
import logging
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
    def __init__(self):
        self.x = self.y = self.z = 0.0


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
                for cb in self.subs.get(f"/{controller}/clip_status", []):
                    cb(_DataMsg(f"{msg.data} holding frame 0 queued 0"))


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
    mod("sensor_msgs")
    mod("sensor_msgs.msg", CompressedImage=_Msg, JointState=_Msg)
    mod("std_msgs")
    mod("std_msgs.msg", Empty=_DataMsg, Float64MultiArray=_DataMsg, String=_DataMsg)
    mod("std_srvs")
    mod("std_srvs.srv", Trigger=_Srv)


_install_fake_ros()
import tool_server  # noqa: E402
from tool_server import LIMITS, LLM_CMD_RATE, WALKING_CONTROLLER, ToolServer, check_move  # noqa: E402
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
    """Made-up tricks: a single-motion policy, a clip trick that holds a pose,
    and a clip trick for the dance. Clip lengths are in frames at 50 fps."""
    tricks = {
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
        "dance": Trick(
            name="dance", description="Dances.", kind="policy", path=Path("dance.json"), duration=12.0,
            clips=[
                _clip("start", 0, 50, next="groove"),
                _clip("groove", 49, 100, loop=True),
                _clip("step_a", 99, 150, next="groove"),
                _clip("step_b", 149, 200, next="groove"),
                _clip("finish", 199, 250),
            ],
            actions={"step_a": "A step.", "step_b": "Another step.", "finish": "Ends the dance."},
            exit_clip="finish",
        ),
    }
    return tricks


class Rig:
    """A fresh ToolServer wired to a fresh fake robot."""

    def __init__(self):
        global ROBOT
        self.clock = VirtualClock()
        ROBOT = self.robot = FakeRobot(self.clock)
        tool_server.time = types.SimpleNamespace(monotonic=self.clock.monotonic)
        tool_server.asyncio = _AsyncioShim(self.clock)
        tool_server.load_tricks = fixture_tricks
        tool_server.list_animations = lambda: {}
        names = set(tool_server.LEG_CONTROLLERS) | set(tool_server.ANIMATION_CONTROLLERS)
        names |= {t.controller for t in fixture_tricks().values()}
        self.robot.controllers = {n: "inactive" for n in names}
        self.robot.controllers[WALKING_CONTROLLER] = "active"  # standing on the walking policy
        self.records: list[logging.LogRecord] = []
        handler = logging.Handler()
        handler.emit = self.records.append
        log = logging.getLogger("tool_server")
        log.handlers[:] = [handler]
        log.setLevel(logging.INFO)
        log.propagate = False
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


# ----------------------------------------------------------------------------- part 1
async def part1() -> None:
    await part1a()
    await part1b()
    await part1c()


async def part1a() -> None:
    print("Part 1a: check_move refuses what the robot can't or shouldn't do")
    probe = check_move(0.4, 0.0, 0.0, 2.0)
    if probe and "not implemented yet" in probe:
        skip_part("check_move")
    else:
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
    print("Part 1b: move walks the robot, then stands still")
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
        outcome = rig.outcomes()
        crashed = [o for o in outcome if "raised" in o]
        if crashed and "NotImplementedError" in crashed[0]:
            skip_part("move's walking loop")
            return
        check("the move ran without crashing", not crashed, "; ".join(crashed))
        check("the walking policy took the legs", WALKING_CONTROLLER in rig.robot.active())
        twists = rig.robot.twists()
        moving = [m for _, m in twists if abs(m.linear.x) > 1e-6]
        check("it published the forward velocity", bool(moving) and all(abs(m.linear.x - 0.4) < 1e-6 for m in moving),
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
        check("a turn publishes its yaw rate in rad/s", bool(turns) and abs(turns[0].angular.z - 60 / 57.2958) < 1e-3,
              f"yaw rates sent: {sorted({round(m.angular.z, 3) for m in turns})}")
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


# ----------------------------------------------------------------------------- part 2
async def _action(rig: Rig, action: str):
    """Call trick_action and let the queue run it."""
    res = await rig.ts.trick_action(action)
    await rig.settle()
    return res, None


def _run_failures(rig: Rig, start: int) -> list[str]:
    return [r.getMessage() for r in rig.records[start:] if r.levelno >= logging.WARNING]


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
        res, _ = await _action(rig, "fetch_the_ball")
        fails = ([] if res.ok else [res.message]) + _run_failures(rig, start)
        check("an unknown action fails", bool(fails), f"got {res}")
        check("... and the message lists the actions that exist", any("wave_left" in f for f in fails),
              f"messages: {fails}")

        start = len(rig.records)
        rig.robot.published.clear()
        res, _ = await _action(rig, "wave_left")  # hold_pose is not running
        fails = ([] if res.ok else [res.message]) + _run_failures(rig, start)
        check("an action while its trick is not running fails", bool(fails), f"got {res}")
        check("... the message says which trick has to run first", any("hold_pose" in f for f in fails),
              f"messages: {fails}")
        check("... and nothing was sent to the trick", not rig.robot.clips(ctrl))

        await rig.ts.custom_trick("hold_pose")
        await rig.settle()
        check("(provided) playing the trick leaves it holding its pose",
              ctrl in rig.robot.active() and rig.ts.clip_trick is rig.ts.tricks["hold_pose"])
        start = len(rig.records)
        res, _ = await _action(rig, "wave_left")
        check("an action while the trick holds its pose is accepted", res.ok, f"got {res}")
        check("... and plays that clip", rig.robot.clips(ctrl)[-1:] == ["wave_left"], f"clips sent: {rig.robot.clips(ctrl)}")
        check("... without a failure in the queue", not _run_failures(rig, start), f"{_run_failures(rig, start)}")
        check("... and the trick keeps holding its pose afterwards",
              ctrl in rig.robot.active() and WALKING_CONTROLLER not in rig.robot.active())

        res, _ = await _action(rig, "leave")
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
        await rig.ts.custom_trick("hold_pose")
        start = len(rig.records)
        res = await rig.ts.trick_action("wave_right")
        await rig.settle()
        check("an action queued right behind its trick is accepted and plays",
              res.ok and "wave_right" in rig.robot.clips(ctrl),
              f"result {res}; queue: {_run_failures(rig, start)}; clips sent: {rig.robot.clips(ctrl)}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- part 3
async def part3() -> None:
    print("Part 3: dance (the fake clip trick 'dance': step_a, step_b; exit clip finish)")
    if tool_server.DANCE_TRICK != "dance":
        print(f"  (these tests use a fake trick named 'dance'; yours is {tool_server.DANCE_TRICK!r})")
        tool_server.DANCE_TRICK = "dance"
    rig = Rig()
    try:
        ctrl = rig.ts.tricks["dance"].controller
        res = await rig.ts.dance([{"move": "step_a", "hold_s": 0.5}])
        await rig.settle()
        if not_implemented(res):
            skip_part("dance")
            return
        rig.close()
        rig = Rig()

        for name, moves in [
            ("an unknown move", [{"move": "step_a", "hold_s": 0.0}, {"move": "moonwalk", "hold_s": 0.0}]),
            ("an empty dance", []),
            ("a negative hold", [{"move": "step_a", "hold_s": -1.0}]),
        ]:
            res = await rig.ts.dance(moves)
            await rig.settle()
            check(f"refuses {name} right away", res.ok is False, f"got {res}")
            check("... before anything moves", not rig.robot.clips(ctrl), f"clips sent: {rig.robot.clips(ctrl)}")
            if name == "an unknown move":
                check("... and the message lists the moves that exist", "step_a" in res.message, f"got {res.message!r}")

        start = len(rig.records)
        res = await rig.ts.dance([{"move": "step_b", "hold_s": 0.5}, {"move": "step_a", "hold_s": 0.0},
                                  {"move": "step_b", "hold_s": 1.0}])
        check("a good dance is accepted", res.ok, f"got {res}")
        if not await rig.settle():
            check("the dance finishes", False, "the queue never emptied")
            return
        played = [c for c in rig.robot.clips(ctrl) if c in ("step_a", "step_b")]
        check("the moves play in order", played == ["step_b", "step_a", "step_b"], f"clips sent: {rig.robot.clips(ctrl)}")
        check("... without a failure in the queue", not _run_failures(rig, start), f"{_run_failures(rig, start)}")
        check("... and it ends standing on the walking policy", WALKING_CONTROLLER in rig.robot.active(),
              f"active: {sorted(rig.robot.active())}")
    finally:
        rig.close()


# ----------------------------------------------------------------------------- main
PARTS = {"part1": part1, "part2": part2, "part3": part3}


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
