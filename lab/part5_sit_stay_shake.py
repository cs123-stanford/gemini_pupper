"""Part 5: Sit, Stay, Shake. TODO 8 (trick_action), then TODO 9 (what Gemini reads about it).

A clip trick (part4_tricks.py explains them) holds a pose and takes requests:
the shakes and the stand-up of sit_stay_shake are its *actions*, and they only
make sense while the trick holds its pose. You train sit_stay_shake in the
notebook and fetch it with robot/get_trick.py; until then, the tests use a
made-up clip trick called hold_pose.
"""

from __future__ import annotations

from robot_api import WALKING_CONTROLLER, Result, Robot, not_written  # noqa: F401
from tool_registry import ACTION_IDS, Param, tool


# ============================================================ what the robot does
async def trick_action(robot: Robot, action: str) -> Result:
    """Play one of a clip trick's actions (e.g. shake a paw while sitting).

    TODO 8 (Part 5) ------------------------------------------------------------
    Now:                 robot.action_ids() maps each action to (trick, clip). An
                         unknown action fails, listing the real ones. An action
                         only works while its trick holds its pose: refuse unless
                         robot.holding_after_queue is trick, and tell Gemini
                         which trick to play first.
    Later (the job):     check again that trick.controller is active (it may
                         have fallen, been e-stopped or stopped since); play the
                         clip with robot.play_clip. The exit clip ends standing:
                         after it, robot.holding_now = None and the legs go back
                         to the walking policy.
    Gemini hears now:    robot.queue(f"{trick.name} {clip}", job,
                         trick.clip_time_estimate(clip), then_holding=...):
                         None after the exit clip, else trick.
    Why check twice:     "sit, then shake" said in one breath queues both before
                         the sit has happened (holding_after_queue knows it
                         will); a fall or a stop can still happen in between.
    Use:                 robot.action_ids, robot.holding_after_queue,
                         robot.is_active, robot.play_clip, robot.switch_to
    Tests check:         - an unknown action fails, and the message lists the real ones.
                           Passes: "unknown trick action fetch_the_ball; available: ['wave_left', ...]"
                         - an action while its trick isn't (going to be) holding fails
                           right away, names the trick, and queues nothing.
                           Passes: "wave_left only works while hold_pose is running;
                                    play it first (play_trick hold_pose)"
                           Fails:  "not sitting" (Gemini can't tell which trick to play)
                         - while holding: the clip plays and the trick keeps holding
                         - the exit clip: walking takes the legs back, holding_now is
                           None, and later actions are refused (then_holding=None)
                         - "sit, then shake" queued back to back plays both
                           (the now-check must use holding_after_queue)
                         - if the trick was relaxed before the queue got there, the
                           job refuses (the later check: robot.is_active)
    Test:                python3 lab/test.py todo8
    """
    # ========== TODO 8: YOUR CODE HERE ==========
    # NOW:
    # 1. found = robot.action_ids().get(action). If None: fail, listing list(robot.action_ids()).
    # 2. trick, clip = found
    # 3. If robot.holding_after_queue is not trick: fail, and say which trick to play first
    #    (e.g. f"... play it first (play_trick {trick.name})").
    # THE JOB:
    # 4. async def job() -> Result:
    #        a. If not await robot.is_active(trick.controller): fail, saying which trick must run first.
    #        b. res = await robot.play_clip(trick, clip)
    #        c. If res failed, or clip is not the exit clip (trick.exit_clip): return res.
    #        d. It was the exit clip (the robot is standing again): robot.holding_now = None,
    #           then res = await robot.switch_to(WALKING_CONTROLLER), and report how that went.
    # QUEUE IT:
    # 5. return await robot.queue(f"{trick.name} {clip}", job, trick.clip_time_estimate(clip),
    #                              then_holding=...)   None after the exit clip, else trick.
    return not_written("TODO 8", "trick_action in lab/part5_sit_stay_shake.py")
    # ====================================


# ============================================================ what Gemini reads
# TODO 9: describe trick_action for Gemini, and write its body (it calls
# trick_action above). {actions} in a description becomes the list of installed
# actions, each with its trick and its description from trick.yaml. Say what has
# to happen first, and what ends it. (Also TODO 9: the words in
# tricks/sit_stay_shake/trick.yaml, once you have fetched your policy.)
#   Tests check:
#   - the description is 20+ characters, and action is described
#   - it contains {actions} (each action's description appears in it)
#   - action keeps enum=ACTION_IDS, and the tool plays the clip
#   - trick.yaml (once fetched): no TODO left, description 20+ characters, and
#     every action described in 10+ characters.
#     Passes: shake_left: "Shakes the left paw, then keeps sitting."  Fails: shake_left: "left"
#   Test: python3 lab/test.py todo9
# ========== TODO 9: YOUR CODE HERE ==========
@tool(
    "trick_action",
    "TODO 9: describe trick_action for Gemini. Actions:\n{actions}",
    action=Param("string", "TODO 9", enum=ACTION_IDS),
)
async def trick_action_tool(robot: Robot, action: str) -> Result:
    # One line: call trick_action(robot, action) (your TODO 8), await it, and return it.
    return not_written("TODO 9", "trick_action in lab/part5_sit_stay_shake.py")
# ====================================
