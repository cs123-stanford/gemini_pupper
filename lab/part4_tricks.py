"""Part 4: Tricks. TODO 6 (play_trick), then TODO 7 (what Gemini reads about it).

Read it top to bottom: play_trick (yours) checks the request and queues the
job; play_policy_trick (finished: read it) is that job; the play_trick tool
(yours: its words) is what Gemini calls.

Two kinds of trick. A normal trick (trick.clips == []) is one motion played start
to finish, like sit. A clip trick (trick.clips lists its clips), like
sit_stay_shake, is several short motions: it plays its first clip, then loops
one (the "stay") until Gemini asks for another (trick_action, Part 5) or any
other motion plays its exit clip (trick.exit_clip).
"""

from __future__ import annotations

from basics import ENDS_FOLLOW
from part3_follow import leave_follow_mode
from robot_api import FELL_MESSAGE, WALKING_CONTROLLER, Result, Robot, not_written, with_note  # noqa: F401
from tool_registry import TRICK_NAMES, Param, tool
from tricks import Trick


# ============================================================ what the robot does
async def play_trick(robot: Robot, name: str) -> Result:
    """Play a trick from <repo>/tricks. Every trick in the lab is a policy trick:
    it plays its own controller (the job is play_policy_trick below).

    TODO 6 (Part 4) ------------------------------------------------------------
    Now:                 an unknown name fails with f"unknown trick '{name}';
                         available: {list(robot.tricks)}"; leave follow mode.
    Later (the job):     play_policy_trick(robot, trick), below: read it.
    Gemini hears now:    robot.queue(f"trick {name}", job, trick.total_time,
                         then_holding=...) with the note in front.
                         then_holding is the trick if it is a clip trick (it has
                         trick.clips: it will hold a pose), else None.
    Test:                python3 lab/test.py todo6

    Optional, after the lab: the jump. Pupper's default walking policy can
    already jump (you have seen it on the gamepad). Give Gemini that jump:
    rename tricks/jump/trick.yaml.optional to trick.yaml, and make a trick of
    trick.kind == "reference" play with robot.play_reference_trick(trick)
    instead. Test: python3 lab/test.py optional_jump
    """
    # ========== TODO 6: YOUR CODE HERE ==========
    # NOW:
    # 1. trick = robot.tricks.get(name). If it is None, fail, and list the real names: list(robot.tricks).
    # 2. note = await leave_follow_mode(robot)
    # THE JOB:
    # 3. job = lambda: play_policy_trick(robot, trick)
    #    (a lambda is a function in one line: robot.queue calls it later, when it's the trick's turn)
    # QUEUE IT:
    # 4. Decide then_holding: will this trick hold a pose when it's done? (Read the card above.)
    # 5. return with_note(note, await robot.queue(f"trick {name}", job, trick.total_time, then_holding=...))
    return not_written("TODO 6", "play_trick in lab/part4_tricks.py")
    # ====================================


async def play_policy_trick(robot: Robot, trick: Trick) -> Result:
    """The job that plays a policy trick (finished: read it).

    Your play_trick (TODO 6) queues this; it runs when the queue gets to the
    trick. It gives the legs to the trick's controller, waits while the trick
    plays, then leaves the robot in the right pose, and says which: Gemini (and
    robot_status) can only plan the next move if it knows. The four steps:

    1. A clip trick already holding its pose: nothing to do.
    2. A trick still holding the end of its last run (its controller is still
       on): relax first. Switching to a controller that is already on does
       nothing at all, so without this "swim again" would just keep lying there.
    3. Give the legs to the trick, and wait while it plays.
    4. Afterwards: a clip trick keeps holding (and remembers it, in
       robot.holding_now); a trick that ends standing hands the legs back to
       the walking policy; any other trick holds its final pose.

    Examples (the handout has them as a table):
      sit (ends standing), robot walking   -> "played sit; back on the walking policy"
      swim (ends lying), robot walking     -> "played swim; the trick controller holds the final pose"
      swim again, still lying from swim    -> relaxes first (step 2), then the same
      sit_stay_shake (a clip trick)        -> "played sit_stay_shake; it now stays sitting. Trick
                                              actions: shake_left, shake_right, stand_up. ..."
      sit_stay_shake, already sitting      -> "already doing sit_stay_shake"
    """
    if trick.clips and robot.holding_now is trick:  # 1. already holding its pose
        return Result(True, f"already doing {trick.name}")
    if not trick.clips and await robot.is_active(trick.controller):
        # 2. Still holding this trick's end pose: relax, so switching to it restarts it.
        res = await robot.switch_to(None)
        if not res.ok:
            return res
    res = await robot.switch_to(trick.controller)  # 3. the trick takes the legs
    if not res.ok:
        return res
    await robot.sleep(trick.total_time + 0.3)  # ... and plays
    if robot.fallen:
        return Result(False, f"{trick.name} ended in a fall: {FELL_MESSAGE}")
    if trick.clips:  # 4. a clip trick stays in its looping clip until asked for an action
        robot.holding_now = trick
        actions = ", ".join(trick.actions) or "none"
        leave = f" Any other motion first plays {trick.exit_clip}." if trick.exit_clip else ""
        return Result(True, f"played {trick.name}; it now stays {trick.end_pose}. Trick actions: {actions}.{leave}")
    if trick.end_pose == "standing":  # 4. hand back to the walking policy
        res = await robot.switch_to(WALKING_CONTROLLER)
        if not res.ok:
            return Result(False, f"played {trick.name} but could not return to walking: {res.message}")
        return Result(True, f"played {trick.name}; back on the walking policy")
    return Result(True, f"played {trick.name}; the trick controller holds the final pose")  # 4. it stays


# ============================================================ what Gemini reads
# TODO 7: describe play_trick for Gemini. {tricks} in a description becomes the
# list of installed tricks (each with its description from its trick.yaml).
# Gemini needs to know that each trick says whether it starts standing or lying
# down, and that the robot keeps a trick's final pose until the next motion.
#   Test: python3 lab/test.py todo7
# ========== TODO 7: YOUR CODE HERE ==========
@tool(
    "play_trick",
    "TODO 7: describe play_trick for Gemini." + ENDS_FOLLOW + "\nTricks:\n{tricks}",
    name=Param("string", "TODO 7", enum=TRICK_NAMES),
)
# ====================================
async def play_trick_tool(robot: Robot, name: str) -> Result:
    return await play_trick(robot, name)
