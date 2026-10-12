"""Part 2: Walk. TODO 2 (check_move), TODO 3 (the turn and move tools), then TODO 4 (arc).

Read it top to bottom: check_move (yours) decides whether a move is allowed;
walk (finished: read it) does a move on the robot; turn, move and arc (yours)
are what Gemini calls, and they call walk.

    "walk forward" -> move (TODO 3) -> walk -> check_move (TODO 2) -> the job, later
"""

from __future__ import annotations

import math

from basics import ENDS_FOLLOW
from part3_follow import leave_follow_mode
from robot_api import FELL_MESSAGE, LIMITS, LLM_CMD_RATE, WALKING_CONTROLLER, MoveLimits, Result, Robot, not_written, with_note  # noqa: F401
from tool_registry import Param, tool

# "Run" means at least this fast, in m/s (the walking policy switches to its
# running gait above about 0.5 m/s).
RUN_MIN_SPEED = 1.0
RUN_DEFAULT_SPEED = 1.2
TURN_SPEED = 60.0  # deg/s


# ============================================================ what the robot does
def check_move(vx: float, vy: float, wz_deg: float, duration: float, limits: MoveLimits = LIMITS) -> str | None:
    """None if the robot may make this move, else the reason it may not.

    vx forward m/s, vy left m/s, wz_deg counter-clockwise deg/s, duration in s.

    TODO 2 (Part 2) ------------------------------------------------------------
    Gemini reads:        the string you return, word for word, as the tool's
                         reply. "too fast" leaves Gemini guessing; "too fast:
                         |vx|<=1.5 m/s" lets it retry at a speed that works.
    Must always be true: refuse anything too fast, too slow to move at all, a
                         duration that isn't more than 0 and at most
                         duration_max, and a move that would travel farther
                         than distance_max. Look at every field of MoveLimits
                         (robot/robot_api.py).
    Why here:            the tool descriptions ask Gemini to stay within the
                         limits; this makes sure of it.
    Tests check:         - good moves (even exactly at a limit) -> None
                         - each bad move -> a non-empty reason
                         - the reason contains the limit's number, as Python
                           prints it: vx_max "1.5", vy_max "0.5", wz_max
                           "114.0", duration_max "10.0", distance_max "5.0".
                           Passes: f"... at most {limits.duration_max} s"
                           Fails:  "too long", or "{limits.duration_max:.0f}" ("10")
    Test:                python3 lab/test.py todo2
    """
    # ========== TODO 2: YOUR CODE HERE ==========
    # Check the rules one at a time, and return the first reason you find.
    # Each reason says what was wrong AND the limit, e.g. f"too fast: limits are |vx|<={limits.vx_max} m/s, ..."
    # 1. Too fast: abs(vx) > limits.vx_max, or abs(vy) > limits.vy_max, or abs(wz_deg) > limits.wz_max.
    # 2. Too slow to move at all: vx, vy AND wz_deg are ALL below their minimums (vx_min, vy_min, wz_min).
    #    (Only all three: a turn in place has vx = vy = 0, and that is fine.)
    # 3. The duration must be more than 0 and at most limits.duration_max.
    # 4. Too far: speed * duration > limits.distance_max, where speed = (vx**2 + vy**2) ** 0.5.
    # 5. Nothing wrong: return None.
    return "TODO 2 is not written yet (check_move in lab/part2_walk.py)"
    # ====================================


async def walk(robot: Robot, vx: float, vy: float, wz_deg: float, duration: float) -> Result:
    """Walk at (vx, vy, wz_deg) for duration seconds, then stand still (finished: read it).

    vx forward m/s, vy left m/s, wz_deg counter-clockwise deg/s. Your turn and
    move tools (TODO 3) call this. It is stand_up's shape (basics.py), with a
    loop in the job. Two things to notice:

    - Why send the speed again and again? The walking policy doesn't take
      "walk for 2 seconds"; it takes a speed, over and over. In between sits
      cmd_vel_mux (the node that lets the joystick win over Gemini), and it
      forgets a speed it hasn't heard for 0.5 s, so a crashed program can't
      leave Pupper walking forever. So the job sends it LLM_CMD_RATE (20) times
      a second for the whole walk, then a zero to stand still.
    - Why check robot.fallen three times? The robot may already have fallen when
      Gemini asks (1), may fall while this job waits in line (2), or while it
      walks (3). Each time, Gemini should hear FELL_MESSAGE, not "moved".
    """
    # NOW, before anything is queued:
    refused = check_move(vx, vy, wz_deg, duration)  # your TODO 2: is this move allowed?
    if refused:
        return Result(False, refused)  # Gemini hears why; nothing is queued
    note = await leave_follow_mode(robot)  # your TODO 5: any motion ends follow mode
    if robot.fallen:  # (1)
        return Result(False, FELL_MESSAGE)

    async def job() -> Result:  # LATER, when the queue gets to it
        if robot.fallen:  # (2)
            return Result(False, FELL_MESSAGE)
        res = await robot.switch_to(WALKING_CONTROLLER)  # the walking policy takes the legs
        if not res.ok:
            return res
        end = robot.now() + duration
        while robot.now() < end:  # keep the mux input alive
            if robot.fallen:  # (3)
                robot.send_speed(0, 0, 0)
                return Result(False, FELL_MESSAGE)
            robot.send_speed(vx, vy, wz_deg)
            await robot.sleep(1.0 / LLM_CMD_RATE)  # never time.sleep: it would freeze the server
        robot.send_speed(0, 0, 0)  # stand still
        return Result(True, f"moved {what} for {duration:.2f} s")  # the outcome (debug log)

    # What Gemini hears NOW: the job was accepted.
    what = f"vx={vx:g} vy={vy:g} wz={wz_deg:.3g}"  # 45.836623610465864 -> 45.8: Gemini reads this
    return with_note(note, await robot.queue(f"move {what} {duration:.3g}s", job, duration))


# ============================================================ what Gemini reads
# TODO 3: write turn first, then move: what Gemini reads (the description and every
# parameter's description) and their bodies.
#   - turn is the warm-up: one number to work out (which way), one call. It shows
#     you the whole path: Gemini's words -> numbers -> walk -> the robot.
#   - move is the real challenge: four parameters, defaults, and the "run" rule.
#   - Put the robot's real limits in the words: LIMITS.vx_max and the others
#     (robot/robot_api.py), RUN_MIN_SPEED, and the defaults. Add ENDS_FOLLOW.
#   Tests check:
#   - each tool's description is 20+ characters, and every parameter is described
#   - turn left sends +wz, right -wz, about the angle asked for, with vx = vy = 0
#   - move's words contain the number LIMITS.vx_max ("1.5") and the word "follow"
#     (from ENDS_FOLLOW). Passes: f"... up to {LIMITS.vx_max} m/s" + ENDS_FOLLOW
#   - the move examples below send exactly those speeds
#   - move("right", run=True) says it walked: the reply says "walk".
#     Passes: "Sideways never runs; walking instead. move vx=0 vy=-0.4 ... queued"
#     Fails:  "move vx=0 vy=-0.4 ... queued" (Gemini then tells them it's running)
#   - a move check_move refuses comes back as a failure with check_move's reason
#   Test: python3 lab/test.py todo3  (turn is checked first, on its own)
# ========== TODO 3: YOUR CODE HERE ==========
@tool(
    "turn",
    "TODO 3: describe the turn tool for Gemini.",
    direction=Param("string", "TODO 3", enum=["left", "right"]),
    angle=Param("number", "TODO 3", required=False),
)
async def turn_tool(robot: Robot, direction: str, angle: float = 45.0) -> Result:
    # Turn in place: no forward or sideways speed, just a turning speed, for as long
    # as the angle takes.
    # 1. wz_deg: +TURN_SPEED to the left (counter-clockwise), -TURN_SPEED to the right.
    # 2. How long it takes: seconds = abs(angle) / TURN_SPEED
    #    (90 degrees at 60 deg/s takes 1.5 s)
    # 3. return await walk(robot, 0.0, 0.0, wz_deg, seconds)
    return not_written("TODO 3", "turn in lab/part2_walk.py")


@tool(
    "move",
    "TODO 3: describe the move tool for Gemini.",
    direction=Param("string", "TODO 3", enum=["forward", "backward", "left", "right"]),
    run=Param("boolean", "TODO 3", required=False),
    speed=Param("number", "TODO 3", required=False),
    duration=Param("number", "TODO 3", required=False),
)
async def move_tool(
    robot: Robot,
    direction: str,
    run: bool = False,
    speed: float | None = None,
    duration: float = 1.5,
) -> Result:
    # Gemini may leave out run, speed and duration (then they have the defaults above:
    # speed is None when Gemini gave none). Work out ONE speed, then split it into vx and vy.
    # 1. The speed:
    #    - running (run is True AND the direction is forward or backward): at least
    #      RUN_MIN_SPEED; if Gemini gave no speed, RUN_DEFAULT_SPEED.
    #      (max(a, b) is the bigger of two numbers: max(0.6, RUN_MIN_SPEED) is 1.0.)
    #    - otherwise (walking, or any sideways move): speed, or 0.4 if Gemini gave none.
    # 2. Split it by direction (the robot's convention: +x forward, +y LEFT):
    #        forward: vx = +speed, vy = 0      backward: vx = -speed, vy = 0
    #        left:    vx = 0, vy = +speed      right:    vx = 0, vy = -speed
    # 3. If Gemini asked to run sideways, you walk instead: say so, or Gemini will
    #    tell the person it's running. Start the reply with a note:
    #      note = "Sideways never runs; walking instead. " (or "" otherwise)
    #      return with_note(note, await walk(robot, vx, vy, 0.0, duration))
    # Examples: move("forward") -> vx 0.4 | move("backward", run=True) -> vx -1.2 |
    #   move("forward", run=True, speed=0.6) -> vx 1.0 | move("right", run=True) -> vy -0.4
    return not_written("TODO 3", "move in lab/part2_walk.py")
# ====================================


# TODO 4: the arc tool: walk forward and turn at the same time, along part of a
# circle. turn sends only a turning speed and move only a straight one, so
# "go in a circle" was move, stop, turn, move. walk takes vx and wz_deg together,
# and the locomotion policy can do both at once: arc is how Gemini asks for it.
#   Now:                 work out vx and wz_deg from the radius and the speed, then
#                        walk (walk checks the move with check_move and queues it).
#   Gemini reads:        the words, to pick a radius the robot can do; then the
#                        reply: walk's, or why there is no arc (a radius or speed
#                        of 0 or less), or check_move's reason (too tight, too far).
#   Must always be true: an arc the robot can't do never moves it and never crashes.
#   The math: around a circle of radius r (m) at speed v (m/s),
#     wz_deg = math.degrees(v / r)   (+ to the left, - to the right)
#     seconds = abs(angle) / abs(wz_deg)
#     e.g. 90 deg at 0.4 m/s around r = 0.5 m: wz = 45.8 deg/s for 1.96 s (0.79 m)
#   Put the real limits in the words: the robot turns at most LIMITS.wz_max deg/s,
#   so at speed v the radius must be at least v / math.radians(LIMITS.wz_max); one
#   arc goes at most LIMITS.distance_max m. Add ENDS_FOLLOW.
#   Tests check:
#   - arc's description is 20+ characters, and every parameter is described
#   - its words contain LIMITS.distance_max ("5.0") and "follow" (from ENDS_FOLLOW).
#     Passes: f"... One arc goes at most {LIMITS.distance_max} m." + ENDS_FOLLOW
#     Fails:  "Walk in a curve." (Gemini then asks for circles the robot refuses)
#   - arc("left", angle=90, radius=0.5) sends vx = +0.4, vy = 0 and wz = +45.8 deg/s,
#     and turns about 90 deg; arc("right", ...) sends a negative wz, still forward
#   - arc("left", speed=0.6, radius=1.0) sends vx = 0.6 and wz = +34.4 deg/s
#   - arc("left", radius=0) is a failure that says "radius", and sends nothing.
#     Passes: "radius must be more than 0 m"   Fails: a crash (division by zero)
#   - arc("left", radius=0.1) is too tight (229 deg/s): a failure with check_move's
#     reason ("114.0").  Fails: a success that quietly turned slower
#   Test: python3 lab/test.py todo4
# ========== TODO 4: YOUR CODE HERE ==========
@tool(
    "arc",
    "TODO 4: describe the arc tool for Gemini.",
    direction=Param("string", "TODO 4", enum=["left", "right"]),
    angle=Param("number", "TODO 4", required=False),
    radius=Param("number", "TODO 4", required=False),
    speed=Param("number", "TODO 4", required=False),
)
async def arc_tool(
    robot: Robot,
    direction: str,
    angle: float = 90.0,
    radius: float = 0.5,
    speed: float = 0.4,
) -> Result:
    # 1. No circle to follow: if radius <= 0 or speed <= 0, return Result(False, ...)
    #    saying which, and what works: "radius must be more than 0 m".
    # 2. wz_deg = math.degrees(speed / radius): + to the left, - to the right.
    # 3. seconds = abs(angle) / abs(wz_deg)
    # 4. return await walk(robot, speed, 0.0, wz_deg, seconds)  (walk checks it)
    # Examples: arc("left") -> vx 0.4, wz +45.8 for 1.96 s |
    #   arc("right", angle=180, radius=1.0, speed=0.6) -> vx 0.6, wz -34.4 for 5.24 s
    return not_written("TODO 4", "arc in lab/part2_walk.py")
# ====================================
