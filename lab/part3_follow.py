"""Part 3: Follow. TODO 4 (the rule that ends follow mode), then TODO 5 (the follow tool).

The person follower itself is provided (robot.set_following). The rule is yours:

    Questions and conversation keep following. Any motion (walk, turn, trick,
    stand up, lie down) ends follow mode, and Pupper says so first:
    "Let me stop following you and ..."
"""

from __future__ import annotations

from robot_api import Result, Robot, not_written  # noqa: F401
from tool_registry import Param, tool


# ============================================================ what the robot does
async def leave_follow_mode(robot: Robot) -> str:
    """Every motion calls this first, before it queues anything: look for it in
    stand_up (basics.py) and walk (part2_walk.py).

    TODO 4 (Part 3) ------------------------------------------------------------
    The rule:            talking and questions keep following. Any motion (walk,
                         turn, trick, stand up, lie down) ends follow mode right
                         away, not when the queue gets to the motion.
    Returns:             a note that goes in front of the tool's reply, e.g.
                         "Stopped following the person first. ", or "" if the
                         robot wasn't following.
    Why right away:      the person asked for something else *now*; the robot
                         shouldn't keep chasing them until the queue gets there.
    Why a note:          Gemini can only say "Let me stop following you and ..."
                         if the reply tells it.
    Use:                 robot.following, await robot.stop_following(),
                         robot.send_speed(0, 0, 0) (stand still)
    Test:                python3 lab/test.py todo4
    """
    # ========== TODO 4: YOUR CODE HERE ==========
    # 1. If robot.following is False, there is nothing to do: return "".
    # 2. Turn the person follower off: await robot.stop_following()
    # 3. Stand still (the follower may have been walking): robot.send_speed(0, 0, 0)
    # 4. Return the note Gemini will read, e.g. "Stopped following the person first. "
    #    (end it with a space: the tool's own reply comes right after it)
    return ""  # for now: following never ends
    # ====================================


# ============================================================ what Gemini reads
# TODO 5: describe follow for Gemini, and write its body: robot.set_following(enabled)
# (provided) starts or stops the person follower. Gemini should know what keeps
# follow mode on and what ends it (your rule in TODO 4).
#   Test: python3 lab/test.py todo5
# ========== TODO 5: YOUR CODE HERE ==========
@tool(
    "follow",
    "TODO 5: describe the follow tool for Gemini.",
    enabled=Param("boolean", "TODO 5"),
)
async def follow_tool(robot: Robot, enabled: bool) -> Result:
    # One line: robot.set_following(enabled) (provided) starts or stops following, and
    # returns the Result Gemini should hear. Await it and return it.
    return not_written("TODO 5", "follow in lab/part3_follow.py")
# ====================================
