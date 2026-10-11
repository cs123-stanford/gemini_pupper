"""The tools Gemini can call.

Each tool is one Python function with an @tool(...) line above it.
  - The @tool line is what Gemini reads: a description, and a description of
    each parameter. Gemini decides when to call a tool, and what to pass, from
    these words alone, so put the robot's real limits in them.
  - The function is what runs on the robot. Keep it short: turn Gemini's words
    into numbers, and call a behavior (behaviors.py). Whatever it returns (a
    Result) goes back to Gemini, so Gemini knows what really happened.

After you change this file: python3 robot/test_tools.py, then restart
(robot/stop.sh && robot/start.sh) and reconnect in the app.

Directions use the robot's convention: positive y is LEFT, and a positive turn
is to the LEFT (counter-clockwise).
"""

from __future__ import annotations

import behaviors
from robot_api import LIMITS, Result, Robot, not_written  # noqa: F401
from tool_registry import ACTION_IDS, TRICK_NAMES, Param, call, declarations, tool  # noqa: F401

# "Run" means at least this fast, in m/s (the walking policy switches to its
# running gait above about 0.5 m/s).
RUN_MIN_SPEED = 1.0
RUN_DEFAULT_SPEED = 1.2
TURN_SPEED = 60.0  # deg/s

# Added to the description of every tool that ends follow mode (see TODO 5 and 6).
ENDS_FOLLOW = (
    " If follow mode is on, this ends it: first tell the user,"
    ' e.g. "Let me stop following you and ...".'
)


# ============================================================ provided tools (read these first)
@tool("Stand up and turn on walking. Needed before moving, and to stand up after a trick." + ENDS_FOLLOW)
async def stand_up(robot: Robot) -> Result:
    return await behaviors.stand_up(robot)


@tool(
    "Relax all motors so the robot lies down. Use when the user says sleep, relax"
    " or lie down." + ENDS_FOLLOW
)
async def lie_down(robot: Robot) -> Result:
    return await behaviors.lie_down(robot)


@tool("Emergency stop: cancel everything queued and stand still.")
async def stop(robot: Robot) -> Result:
    return await robot.immediate_stop()


@tool("Check what the robot is doing right now: walking, in a trick, following, motors off, or fallen over.")
async def robot_status(robot: Robot) -> Result:
    return await robot.mode()


# ============================================================ Part 4: play_trick
# TODO 8: describe play_trick for Gemini. {tricks} in a description becomes the
# list of installed tricks (each with its description from its trick.yaml).
# Gemini needs to know that each trick says whether it starts standing or lying
# down, and that the robot keeps a trick's final pose until the next motion.
# ========== TODO 8: YOUR CODE HERE ==========
@tool(
    "TODO 8: describe play_trick for Gemini." + ENDS_FOLLOW + "\nTricks:\n{tricks}",
    name=Param("string", "TODO 8", enum=TRICK_NAMES),
)
# ====================================
async def play_trick(robot: Robot, name: str) -> Result:
    return await behaviors.play_trick(robot, name)


# ============================================================ Part 2: move and turn
# TODO 4: write what Gemini reads about move and turn (the descriptions and every
# parameter's description), and their bodies.
#   - Put the robot's real limits in the words: LIMITS.vx_max and the others
#     (robot_api.py), RUN_MIN_SPEED, and the defaults. Add ENDS_FOLLOW.
#   - The body turns direction/run/speed/duration into vx (forward) and vy (left)
#     in m/s, and calls behaviors.walk(robot, vx, vy, 0.0, duration). Default
#     speed 0.4 m/s.
#   - "Run" means RUN_MIN_SPEED (1.0 m/s) or faster, forward or backward (sideways
#     never runs; default RUN_DEFAULT_SPEED). Make sure of that here, in code, not
#     only in the description.
#   - turn turns in place at TURN_SPEED deg/s for as long as `angle` takes:
#     behaviors.walk(robot, 0.0, 0.0, wz_deg, seconds). Left is positive.
#   Test: python3 robot/test_tools.py todo4
# ========== TODO 4: YOUR CODE HERE ==========
@tool(
    "TODO 4: describe the move tool for Gemini.",
    direction=Param("string", "TODO 4", enum=["forward", "backward", "left", "right"]),
    run=Param("boolean", "TODO 4", required=False),
    speed=Param("number", "TODO 4", required=False),
    duration=Param("number", "TODO 4", required=False),
)
async def move(
    robot: Robot,
    direction: str,
    run: bool = False,
    speed: float | None = None,
    duration: float = 1.5,
) -> Result:
    # 1. The speed. Running (run is True, and not sideways): at least RUN_MIN_SPEED,
    #    or RUN_DEFAULT_SPEED if no speed was given. Otherwise: speed, or 0.4 if none was given.
    #    (max(a, b) gives the bigger of two numbers.)
    # 2. vx (forward): +speed forward, -speed backward, 0.0 sideways.
    #    vy (LEFT is +): +speed left, -speed right, 0.0 forward or backward.
    # 3. return await behaviors.walk(robot, vx, vy, 0.0, duration)
    return not_written("TODO 4", "move in robot/tools.py")


@tool(
    "TODO 4: describe the turn tool for Gemini.",
    direction=Param("string", "TODO 4", enum=["left", "right"]),
    angle=Param("number", "TODO 4", required=False),
)
async def turn(robot: Robot, direction: str, angle: float = 45.0) -> Result:
    # 1. wz_deg: +TURN_SPEED to the left (counter-clockwise), -TURN_SPEED to the right.
    # 2. How long it takes: seconds = abs(angle) / TURN_SPEED
    # 3. return await behaviors.walk(robot, 0.0, 0.0, wz_deg, seconds)
    return not_written("TODO 4", "turn in robot/tools.py")
# ====================================


# ============================================================ Part 3: follow
# TODO 6: describe follow for Gemini, and write its body: robot.set_following(enabled)
# (provided) starts or stops the person follower. Gemini should know what keeps
# follow mode on and what ends it (your rule in TODO 5).
#   Test: python3 robot/test_tools.py todo6
# ========== TODO 6: YOUR CODE HERE ==========
@tool(
    "TODO 6: describe the follow tool for Gemini.",
    enabled=Param("boolean", "TODO 6"),
)
async def follow(robot: Robot, enabled: bool) -> Result:
    # One line: robot.set_following(enabled) (provided) starts or stops following, and
    # returns the Result Gemini should hear. Await it and return it.
    return not_written("TODO 6", "follow in robot/tools.py")
# ====================================


# ============================================================ Part 5: trick actions
# TODO 10: describe trick_action for Gemini, and write its body (it calls
# behaviors.trick_action). {actions} in a description becomes the list of
# installed actions, each with its trick and its description from trick.yaml.
# Say what has to happen first, and what ends it.
#   Test: python3 robot/test_tools.py todo10
# ========== TODO 10: YOUR CODE HERE ==========
@tool(
    "TODO 10: describe trick_action for Gemini. Actions:\n{actions}",
    action=Param("string", "TODO 10", enum=ACTION_IDS),
)
async def trick_action(robot: Robot, action: str) -> Result:
    # One line: call behaviors.trick_action(robot, action) (your TODO 9), await it, and return it.
    return not_written("TODO 10", "trick_action in robot/tools.py")
# =====================================
