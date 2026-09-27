"""ROS side of Gemini Pupper: a command queue that turns tool calls into robot motion.

Every public method returns a ``Result`` so the robot server can pass real
outcomes back to Gemini instead of assuming success. Gemini only knows what
these messages tell it: a refusal with a clear reason is something it can
explain to the user; a silent failure is something it will cover up.

Most of this file is provided: the command queue, controller switching, and
playing tricks and clips. The parts marked ``YOUR CODE HERE`` / ``TODO(student)``
are the lab:

  Part 1  check_move, ToolServer.move, ToolServer._leave_follow_mode
  Part 2  ToolServer.trick_action
  Part 3  ToolServer.dance

Check your work at the desk, with no robot: ``python3 robot/test_tools.py``.

Topics and controllers used (all started by launch/gemini_pupper.launch.py):
  /llm_cmd_vel                      speed commands; cmd_vel_mux forwards them to
                                    /cmd_vel, and a joystick always overrides them
  /animation_controller_py/animation_select   trick name for the animation player
  /forward_{position,kp,kd}_controller/commands   custom replay tricks (tricks/)
  trick_<name> controllers           custom policy tricks (loaded by the launch file)
  /trick_<name>/clip, /clip_status  clip tricks: request a clip, follow playback
  /camera/image_raw/compressed      latest camera frame
  activate/deactivate_person_following        person_follower services
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import rclpy
from controller_manager_msgs.srv import ListControllers, SwitchController
from geometry_msgs.msg import Twist
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from sensor_msgs.msg import JointState
from std_msgs.msg import Empty, Float64MultiArray, String
from std_srvs.srv import Trigger

from tricks import WALK_CONTROLLER, Trick, load_tricks

log = logging.getLogger("tool_server")

# The walking controller Gemini drives: gemini_walk, the course default policy
# (the joystick's X button) loaded by our launch file with running allowed. See
# tricks.py.
WALKING_CONTROLLER = WALK_CONTROLLER
# Everything that may hold the leg joints; switching modes deactivates the others.
LEG_CONTROLLERS = {
    WALK_CONTROLLER,
    "neural_controller",
    "neural_controller_default",
    "neural_controller_default_alt",
    "neural_controller_three_legged",
    "neural_controller_student",
}
ANIMATION_CONTROLLERS = ["forward_position_controller", "forward_kp_controller", "forward_kd_controller"]

ANIMATION_DIR = Path(
    "/home/pi/pupperv3-monorepo/ros2_ws/install/animation_controller_py/share/animation_controller_py/launch/animations"
)
ANIMATION_FRAME_RATE = 40.0  # Hz, animation_controller_py's frame_rate
ANIMATION_BLEND_IN = 1.0  # s, animation_controller_py's init_duration

LLM_CMD_RATE = 20.0  # Hz; cmd_vel_mux drops a source that is quiet for 500 ms

# Part 3: the clip trick your dance tool sequences (tricks/<DANCE_TRICK>/).
DANCE_TRICK = "dance"

# Custom replay tricks play like the monorepo's animation player: blend from the
# current pose for 1 s, then follow the recording, at these gains.
REPLAY_RATE = 100.0  # Hz
REPLAY_BLEND_S = 1.0
REPLAY_KP = 7.5
REPLAY_KD = 0.25
JOINT_NAMES = [
    "leg_front_r_1", "leg_front_r_2", "leg_front_r_3", "leg_front_l_1", "leg_front_l_2", "leg_front_l_3",
    "leg_back_r_1", "leg_back_r_2", "leg_back_r_3", "leg_back_l_1", "leg_back_l_2", "leg_back_l_3",
]


@dataclass
class MoveLimits:
    """Speeds below the minimums barely move the robot; above the maximums are unsafe."""

    vx_min: float = 0.2  # m/s
    vy_min: float = 0.2  # m/s
    wz_min: float = 20.0  # deg/s
    vx_max: float = 1.5  # m/s; above about 0.5 the default policy runs
    vy_max: float = 0.5  # m/s, the policy's trained sideways range
    wz_max: float = 114.0  # deg/s, the policy's trained 2 rad/s
    duration_max: float = 10.0  # s
    distance_max: float = 5.0  # m in one move, so a run can't cross the room


LIMITS = MoveLimits()


@dataclass
class Result:
    ok: bool
    message: str

    def as_dict(self) -> dict:
        return {"success": self.ok, "message": self.message}


def check_move(vx: float, vy: float, wz_deg: float, duration: float, limits: MoveLimits = LIMITS) -> str | None:
    """Why a move request must be refused, or None if the robot may do it.

    vx forward m/s, vy left m/s, wz counter-clockwise deg/s (signs don't matter
    here), duration in seconds.
    """
    # ========== YOUR CODE HERE: Part 1: refuse what the robot can't or shouldn't do ==========
    # TODO(student): check the request against `limits` (see MoveLimits) and
    # return a reason for anything the robot must not do. What can go wrong
    # with a speed, a duration, and the two together? Every field of MoveLimits
    # is there for a reason.
    #
    # The string you return is *all* Gemini learns about the refusal: say what
    # was wrong and what the limit is, so it can explain it to the user or pick
    # a request that works. (Until this is written, every move is refused.)
    return "move is not implemented yet: TODO(student) check_move in robot/tool_server.py"
    # ==========================================================================================


def list_animations() -> dict[str, float]:
    """Installed trick recordings: csv stem -> playback duration in seconds."""
    out = {}
    for csv in sorted(ANIMATION_DIR.glob("*.csv")):
        with open(csv) as f:
            frames = sum(1 for _ in f) - 1
        if frames > 0:
            out[csv.stem] = frames / ANIMATION_FRAME_RATE + ANIMATION_BLEND_IN
    return out


class ToolServer:
    """Owns a ROS node and runs queued commands one at a time."""

    def __init__(self) -> None:
        if not rclpy.ok():
            rclpy.init()
        self.node = Node("gemini_pupper_tools")
        self.switch_client = self.node.create_client(SwitchController, "/controller_manager/switch_controller")
        self.list_client = self.node.create_client(ListControllers, "/controller_manager/list_controllers")
        self.follow_on = self.node.create_client(Trigger, "activate_person_following")
        self.follow_off = self.node.create_client(Trigger, "deactivate_person_following")
        self.cmd_pub = self.node.create_publisher(Twist, "/llm_cmd_vel", 10)
        self.anim_pub = self.node.create_publisher(String, "/animation_controller_py/animation_select", 10)

        self.pos_pub = self.node.create_publisher(Float64MultiArray, "/forward_position_controller/commands", 10)
        self.kp_pub = self.node.create_publisher(Float64MultiArray, "/forward_kp_controller/commands", 10)
        self.kd_pub = self.node.create_publisher(Float64MultiArray, "/forward_kd_controller/commands", 10)
        self.joint_pos: dict[str, float] = {}
        self.node.create_subscription(JointState, "/joint_states", self._on_joints, 10)

        self.latest_image: queue.Queue[CompressedImage] = queue.Queue(maxsize=1)
        self.node.create_subscription(CompressedImage, "/camera/image_raw/compressed", self._on_image, 1)

        # Clip tricks: request clips and follow what the controller is playing.
        self.clip_trick: Trick | None = None  # the clip trick holding the legs, if any
        self.clip_status: dict[str, tuple[str, bool]] = {}  # controller -> (clip, holding)
        self.clip_pubs: dict[str, object] = {}
        for t in load_tricks().values():
            if t.clips:
                self.clip_pubs[t.controller] = self.node.create_publisher(String, f"/{t.controller}/clip", 10)
                self.node.create_subscription(
                    String, f"/{t.controller}/clip_status", lambda m, c=t.controller: self._on_clip_status(c, m), 10
                )

        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        threading.Thread(target=self.executor.spin, daemon=True).start()

        self.animations = list_animations()
        self.tricks: dict[str, Trick] = load_tricks()
        self.leg_controllers = LEG_CONTROLLERS | {t.controller for t in self.tricks.values() if t.kind == "policy"}
        self.following = False
        self.commands: asyncio.Queue = asyncio.Queue()
        self.current: asyncio.Task | None = None
        self.busy_until = 0.0  # monotonic time when the queued work should finish
        self.worker = asyncio.get_event_loop().create_task(self._run_queue())
        # The gamepad e-stop (right-stick press) relaxes the course's joystick
        # controllers and publishes /emergency_stop. The controllers used here
        # (walking, tricks, recordings) are not on its list, so relax them too.
        self.loop = asyncio.get_event_loop()
        self.node.create_subscription(Empty, "/emergency_stop", self._on_estop, 10)
        log.info("tool server ready: %d tricks, walking controller %s", len(self.animations), WALKING_CONTROLLER)

    # ---------------------------------------------------------------- ROS helpers
    def _on_joints(self, msg: JointState) -> None:
        self.joint_pos.update(zip(msg.name, msg.position))

    def _on_clip_status(self, controller: str, msg: String) -> None:
        # "<clip> playing|holding frame N queued K"
        parts = msg.data.split()
        if len(parts) >= 2:
            self.clip_status[controller] = (parts[0], parts[1] == "holding")

    def _on_image(self, msg: CompressedImage) -> None:
        try:
            self.latest_image.get_nowait()
        except queue.Empty:
            pass
        self.latest_image.put_nowait(msg)

    async def _call(self, client, request, timeout: float = 3.0):
        if not client.wait_for_service(timeout_sec=timeout):
            return None
        future = client.call_async(request)
        deadline = time.monotonic() + timeout
        while not future.done() and time.monotonic() < deadline:
            await asyncio.sleep(0.02)
        return future.result() if future.done() else None

    async def controller_states(self) -> dict[str, str]:
        res = await self._call(self.list_client, ListControllers.Request())
        return {c.name: c.state for c in res.controller} if res else {}

    async def _switch(self, activate: list[str], deactivate: list[str]) -> Result:
        states = await self.controller_states()
        if not states:
            return Result(False, "controller_manager is not running; is the robot stack launched?")
        missing = [c for c in activate if c not in states]
        if missing:
            return Result(False, f"controllers not loaded: {missing}")
        clip_trick = self.clip_trick
        if clip_trick and states.get(clip_trick.controller) == "active" and clip_trick.controller in deactivate:
            self.clip_trick = None
            # Stand up through the trick's own exit clip before another motion takes the
            # legs (not before relaxing the motors: lying down from a sit is fine).
            if activate and clip_trick.exit_clip:
                res = await self._play_clip(clip_trick, clip_trick.exit_clip)
                if not res.ok:
                    log.warning("exit clip: %s", res.message)
        req = SwitchController.Request()
        req.activate_controllers = [c for c in activate if states[c] != "active"]
        req.deactivate_controllers = [c for c in deactivate if states.get(c) == "active"]
        if not req.activate_controllers and not req.deactivate_controllers:
            return Result(True, "already in that mode")
        req.strictness = SwitchController.Request.STRICT
        res = await self._call(self.switch_client, req)
        if res is None or not res.ok:
            return Result(False, f"controller switch failed (activate {activate})")
        return Result(True, "ok")

    def _all_but(self, keep: str) -> list[str]:
        """Every leg and animation controller except ``keep``: what to deactivate
        when ``keep`` takes the legs."""
        return sorted((self.leg_controllers - {keep}) | set(ANIMATION_CONTROLLERS))

    async def _walk(self) -> Result:
        """Hand the legs to the walking policy (standing up if needed)."""
        return await self._switch([WALKING_CONTROLLER], self._all_but(WALKING_CONTROLLER))

    def _publish(self, vx: float, vy: float, wz_deg: float) -> None:
        t = Twist()
        t.linear.x, t.linear.y, t.angular.z = float(vx), float(vy), float(wz_deg) / 57.2958
        self.cmd_pub.publish(t)

    # ---------------------------------------------------------------- queue
    async def _run_queue(self) -> None:
        while True:
            name, coro_fn = await self.commands.get()
            self.current = asyncio.create_task(coro_fn())
            try:
                res = await self.current
                (log.info if res.ok else log.warning)("%s: %s", name, res.message)
            except asyncio.CancelledError:
                self._publish(0, 0, 0)
                log.info("%s: cancelled", name)
            except Exception:
                log.exception("%s failed", name)
            finally:
                self.current = None

    async def _enqueue(self, name: str, coro_fn, duration: float) -> Result:
        now = time.monotonic()
        self.busy_until = max(self.busy_until, now) + duration
        await self.commands.put((name, coro_fn))
        return Result(True, f"{name} queued; the queue should finish in {self.busy_until - now:.1f} s")

    def status(self) -> dict:
        return {
            "queued": self.commands.qsize(),
            "running": self.current is not None,
            "seconds_left": round(max(0.0, self.busy_until - time.monotonic()), 1),
            "following": self.following,
        }

    # ---------------------------------------------------------------- tools
    async def activate_walking(self) -> Result:
        note = await self._leave_follow_mode()

        async def run():
            return await self._walk()

        return self._noted(note, await self._enqueue("activate walking", run, 1.0))

    async def deactivate(self) -> Result:
        note = await self._leave_follow_mode()

        async def run():
            return await self._switch([], sorted(self.leg_controllers | set(ANIMATION_CONTROLLERS)))

        return self._noted(note, await self._enqueue("deactivate", run, 1.0))

    async def move(self, vx: float, vy: float, wz_deg: float, duration: float) -> Result:
        """Walk with a body velocity for a while: vx forward m/s, vy left m/s, wz
        counter-clockwise deg/s, for ``duration`` seconds.

        (The browser sends right- and clockwise-positive values; server.py flips
        them to ROS's left- and counter-clockwise-positive convention first.)
        """
        problem = check_move(vx, vy, wz_deg, duration)
        if problem:
            return Result(False, problem)
        note = await self._leave_follow_mode()

        async def run():
            res = await self._walk()
            if not res.ok:
                return res
            # ========== YOUR CODE HERE: Part 1: drive the walking policy ==========
            # TODO(student): make the robot walk at (vx, vy, wz_deg) for `duration`
            # seconds, then stand still, and return a Result saying what it did.
            # self._publish sends one velocity command. cmd_vel_mux (the node that
            # lets the joystick outrank Gemini) drops a source that has been quiet
            # for 500 ms, so a single message is not enough. Wait with
            # `await asyncio.sleep(...)`, never time.sleep(): the server runs on
            # one event loop, and a blocking sleep freezes everything, including
            # immediate_stop.
            raise NotImplementedError("move: TODO(student) in robot/tool_server.py")
            # =======================================================================

        return self._noted(note, await self._enqueue(f"move vx={vx} vy={vy} wz={wz_deg} {duration}s", run, duration))

    async def animation(self, csv_name: str) -> Result:
        if csv_name not in self.animations:
            return Result(False, f"unknown trick recording {csv_name}")
        duration = self.animations[csv_name]
        note = await self._leave_follow_mode()

        async def run():
            res = await self._switch(ANIMATION_CONTROLLERS, sorted(self.leg_controllers))
            if not res.ok:
                return res
            self.anim_pub.publish(String(data=csv_name))
            await asyncio.sleep(duration)
            return Result(True, f"played {csv_name}; the robot now holds the trick's final pose")

        return self._noted(note, await self._enqueue(f"trick {csv_name}", run, duration))

    async def custom_trick(self, name: str) -> Result:
        """Play a trick from <repo>/tricks: a replay (joint CSV) or a policy (trick controller)."""
        trick = self.tricks.get(name)
        if trick is None:
            return Result(False, f"unknown custom trick {name}")
        note = await self._leave_follow_mode()
        if trick.kind == "policy":
            run = lambda: self._play_policy_trick(trick)  # noqa: E731
        else:
            run = lambda: self._play_replay_trick(trick)  # noqa: E731
        return self._noted(note, await self._enqueue(f"trick {name}", run, trick.total_time))

    async def _play_policy_trick(self, trick: Trick) -> Result:
        if trick.clips and self.clip_trick is trick:
            return Result(True, f"already doing {trick.name}")
        res = await self._switch([trick.controller], self._all_but(trick.controller))
        if not res.ok:
            return res
        await asyncio.sleep(trick.total_time + 0.3)
        if trick.clips:  # stays in its looping clip until asked for an action
            self.clip_trick = trick
            actions = ", ".join(trick.actions) or "none"
            leave = f" Any other motion first plays {trick.exit_clip}." if trick.exit_clip else ""
            return Result(True, f"played {trick.name}; it now stays {trick.end_pose}. Trick actions: {actions}.{leave}")
        if trick.end_pose == "standing":  # hand back to the walking policy
            res = await self._walk()
            if not res.ok:
                return Result(False, f"played {trick.name} but could not return to walking: {res.message}")
            return Result(True, f"played {trick.name}; back on the walking policy")
        return Result(True, f"played {trick.name}; the trick controller holds the final pose")

    def action_ids(self) -> dict[str, tuple[Trick, str]]:
        """Trick action ids Gemini uses -> (trick, clip). A clip name, prefixed with the
        trick's name only when two tricks share it."""
        pairs = [(t, clip) for t in self.tricks.values() for clip in t.actions]
        names = [clip for _, clip in pairs]
        return {(clip if names.count(clip) == 1 else f"{t.name}.{clip}"): (t, clip) for t, clip in pairs}

    async def trick_action(self, action: str) -> Result:
        """Play one of a clip trick's actions (a move from the pose the trick holds)."""
        # ========== YOUR CODE HERE: Part 2: trick actions ==========
        # TODO(student): the voice side of a clip trick. A clip trick stays in its
        # looping clip until asked for something; this plays one of its `actions`
        # (trick.yaml) on request. Things you have to get right:
        #   - which actions exist (self.action_ids() maps the ids Gemini uses to
        #     (trick, clip)), and what Gemini hears when it asks for one that
        #     doesn't;
        #   - preconditions: an action only makes sense while its trick is
        #     running (self.controller_states() tells you which controllers are
        #     active; trick.controller is the trick's). Think about *when* you
        #     check: when Gemini calls the tool, when the queue reaches it, or
        #     both. What goes wrong with each?
        #   - playing it: self._play_clip(trick, clip) requests the clip and waits
        #     until the controller has played it through. Run it through the
        #     queue (self._enqueue), like every other motion, with an honest
        #     duration estimate (trick.clip_length);
        #   - leaving: the trick's exit_clip ends standing. After it, nothing is
        #     holding a pose any more (self.clip_trick) and the walking policy
        #     should take the legs back (self._walk()).
        return Result(False, "trick actions are not implemented yet: TODO(student) in robot/tool_server.py")
        # ============================================================

    async def _play_clip(self, trick: Trick, clip: str) -> Result:
        """Request a clip and wait until the controller has played it through."""
        self.clip_status[trick.controller] = ("", False)  # forget an earlier activation's status
        self.clip_pubs[trick.controller].publish(String(data=clip))
        length = trick.clip_length(clip)
        longest = max((trick.clip_length(c["name"]) for c in trick.clips), default=0.0)
        deadline = time.monotonic() + longest + 1.0  # the current clip finishes first
        while self.clip_status.get(trick.controller, ("", False))[0] != clip:
            if time.monotonic() > deadline:
                return Result(False, f"{trick.name} did not start {clip} (is the controller running?)")
            await asyncio.sleep(0.05)
        deadline = time.monotonic() + length + 1.0
        while True:
            name, holding = self.clip_status.get(trick.controller, ("", False))
            if name != clip or holding or time.monotonic() > deadline:
                break
            await asyncio.sleep(0.05)
        return Result(True, f"played {clip}")

    async def _play_replay_trick(self, trick: Trick) -> Result:
        import csv

        with open(trick.path) as f:
            rows = list(csv.DictReader(f))
        times = [float(r["timestamp_sec"]) - float(rows[0]["timestamp_sec"]) for r in rows]
        frames = [[float(r[j]) for j in JOINT_NAMES] for r in rows]
        start = [self.joint_pos.get(j) for j in JOINT_NAMES]
        if any(v is None for v in start):
            return Result(False, "no /joint_states yet; is the robot stack running?")
        res = await self._switch(ANIMATION_CONTROLLERS, sorted(self.leg_controllers))
        if not res.ok:
            return res
        gains = lambda v: Float64MultiArray(data=[v] * len(JOINT_NAMES))  # noqa: E731
        t0 = time.monotonic()
        i = 0
        while True:
            t = time.monotonic() - t0
            if t < REPLAY_BLEND_S:  # blend from where the legs are to the first frame
                a = t / REPLAY_BLEND_S
                target = [s0 + a * (f0 - s0) for s0, f0 in zip(start, frames[0])]
            else:
                tm = t - REPLAY_BLEND_S
                if tm >= times[-1]:
                    break
                while i + 1 < len(times) and times[i + 1] <= tm:
                    i += 1
                a = (tm - times[i]) / max(times[i + 1] - times[i], 1e-6)
                target = [p + a * (q - p) for p, q in zip(frames[i], frames[i + 1])]
            self.kp_pub.publish(gains(REPLAY_KP))
            self.kd_pub.publish(gains(REPLAY_KD))
            self.pos_pub.publish(Float64MultiArray(data=target))
            await asyncio.sleep(1.0 / REPLAY_RATE)
        self.pos_pub.publish(Float64MultiArray(data=frames[-1]))
        return Result(True, f"played {trick.name}; the robot holds the trick's final pose")

    async def wait(self, duration: float) -> Result:
        async def run():
            await asyncio.sleep(duration)
            return Result(True, f"waited {duration} s")

        return await self._enqueue(f"wait {duration}s", run, duration)

    async def _stop_following(self) -> None:
        if self.following:
            await self._call(self.follow_off, Trigger.Request())
            self.following = False

    async def _leave_follow_mode(self) -> str:
        """Called by every motion tool before it queues anything.

        Returns a note for the front of that tool's result (see _noted), or "".
        """
        # ========== YOUR CODE HERE: Part 1: follow mode ends on motion ==========
        # TODO(student): the follow-mode rule. Questions and conversation keep
        # following; any *motion* (walk, turn, trick, stand up, lie down) ends
        # it, right away rather than when the queue gets to it, and Pupper says
        # so before moving ("Let me stop following you and ..."). Gemini can only
        # say that if the tool result tells it. self.following is the state;
        # self._stop_following() switches the person follower off.
        return ""
        # =========================================================================

    @staticmethod
    def _noted(note: str, res: Result) -> Result:
        return Result(res.ok, note + res.message) if note else res

    async def set_following(self, enabled: bool) -> Result:
        if not enabled:
            await self._stop_following()
            self._publish(0, 0, 0)
            return Result(True, "stopped following")
        if self.following:
            return Result(True, "already following the nearest person")
        await self.clear_queue()
        if self.current and not self.current.done():
            self.current.cancel()
        res = await self._walk()
        if not res.ok:
            return res
        r = await self._call(self.follow_on, Trigger.Request())
        if r is None or not r.success:
            return Result(False, "person_follower did not respond")
        self.following = True
        return Result(True, "following the nearest person. Any new motion (walk, turn, trick, stand, lie down) will end follow mode.")

    async def clear_queue(self) -> Result:
        n = 0
        while not self.commands.empty():
            self.commands.get_nowait()
            n += 1
        self.busy_until = time.monotonic()
        return Result(True, f"cleared {n} queued commands")

    def _on_estop(self, _msg: Empty) -> None:
        asyncio.run_coroutine_threadsafe(self.emergency_stop(), self.loop)

    async def emergency_stop(self) -> Result:
        """Gamepad e-stop: cancel everything and relax every leg controller."""
        await self.immediate_stop()
        self.clip_trick = None  # no exit clip: the motors just relax
        states = await self.controller_states()
        active = [c for c in sorted(self.leg_controllers | set(ANIMATION_CONTROLLERS)) if states.get(c) == "active"]
        if active:
            req = SwitchController.Request()
            req.deactivate_controllers = active
            req.strictness = SwitchController.Request.BEST_EFFORT
            await self._call(self.switch_client, req)
        self.walk_since = None
        log.warning("e-stop: relaxed %s", active or "nothing (no leg controller was active)")
        return Result(True, "e-stop: motors relaxed")

    async def immediate_stop(self) -> Result:
        """Clear the queue, cancel the running command, stop following and stand still."""
        cleared = await self.clear_queue()
        if self.current and not self.current.done():
            self.current.cancel()
        await self._stop_following()
        self._publish(0, 0, 0)
        return Result(True, f"stopped; {cleared.message}")

    async def dance(self, moves: list[dict]) -> Result:
        """Part 3: play a list of dance moves, in order, with timing.

        ``moves`` is what the browser sends, for example
        ``[{"move": "sway", "hold_s": 0.5}, {"move": "bow", "hold_s": 0.0}]``.
        You may change that shape; server.py's DanceStep and your dance tool's
        schema in services/geminiLive.ts must change with it.
        """
        # ========== YOUR CODE HERE: Part 3: the dance tool ==========
        # TODO(student): your dance is a clip trick (tricks/<DANCE_TRICK>/), so
        # Part 2's machinery can sequence its moves. Validate the *whole* request
        # before anything moves (unknown moves, bad timing, too long in total)
        # and refuse it with a message Gemini can act on; then queue the dance so
        # it starts the trick if it isn't running, plays the moves in order with
        # their timing, and ends standing on the walking policy.
        return Result(False, "dance is not implemented yet: TODO(student) in robot/tool_server.py")
        # ============================================================

    async def mode(self) -> Result:
        states = await self.controller_states()
        if not states:
            return Result(False, "controller_manager is not running")
        walking = states.get(WALKING_CONTROLLER) == "active"
        trick = states.get("forward_position_controller") == "active"
        clip_trick = self.clip_trick if self.clip_trick and states.get(self.clip_trick.controller) == "active" else None
        mode = (
            "following" if self.following
            else "walking" if walking
            else f"{clip_trick.name} ({clip_trick.end_pose}; actions: {', '.join(clip_trick.actions)})" if clip_trick
            else "trick pose" if trick
            else "motors off"
        )
        return Result(True, f"mode: {mode}")
