"""What the robot does when Gemini asks: one function per behavior.

tools.py turns Gemini's words into a call to one of these. Each behavior decides
whether the request is allowed, does it, and returns a Result: Gemini reads its
message, so it should say what happened, or what was wrong and what would work.

Every motion has the same shape. Read stand_up and lie_down below first: they
are finished examples of it.

    async def behavior(robot, ...):
        (1) NOW: check what can be checked right away; refuse with a reason
        async def job():
            (2) LATER, when the queue gets here: check again, act, report the outcome
        (3) return await robot.queue(name, job, seconds)   # what Gemini hears now

Why a queue? Gemini often asks for several things in one breath ("sit, then
shake"). The queue runs them one at a time, in order, while Gemini keeps
talking. So a tool replies as soon as its job is *accepted*; the job's
*outcome* (done, fell over, controller failed) goes to the debug log and to
robot_status.

The Robot API you use is listed at the top of robot_api.py.
"""

from __future__ import annotations

from robot_api import (
    FELL_MESSAGE,
    LIMITS,
    LLM_CMD_RATE,
    WALK_READY_S,
    WALKING_CONTROLLER,
    MoveLimits,
    Result,
    Robot,
    not_written,
    with_note,
)
from tricks import Trick


# ============================================================ worked examples (provided)
async def stand_up(robot: Robot) -> Result:
    """Stand up on the walking policy (also: stand up after a trick)."""
    note = await leave_follow_mode(robot)  # (1) now: any motion ends follow mode (TODO 5)

    async def job() -> Result:  # (2) later: give the legs to the walking policy
        return await robot.switch_to(WALKING_CONTROLLER)

    return with_note(note, await robot.queue("activate walking", job, WALK_READY_S))  # (3)


async def lie_down(robot: Robot) -> Result:
    """Relax every motor, so the robot lies down."""
    note = await leave_follow_mode(robot)

    async def job() -> Result:
        return await robot.switch_to(None)  # None: no controller holds the legs

    return with_note(note, await robot.queue("deactivate", job, 1.0))


# ============================================================ Part 2: walk
def check_move(vx: float, vy: float, wz_deg: float, duration: float, limits: MoveLimits = LIMITS) -> str | None:
    """None if the robot may make this move, else the reason it may not.

    vx forward m/s, vy left m/s, wz_deg counter-clockwise deg/s, duration in s.

    TODO 2 (Part 2) ------------------------------------------------------------
    Gemini reads:        the string you return: say what was wrong, and the limit.
    Must always be true: refuse anything too fast, too slow to move at all, a
                         duration that isn't more than 0 and at most
                         duration_max, and a move that would travel farther
                         than distance_max. Look at every field of MoveLimits.
    Why here:            the tool descriptions ask Gemini to stay within the
                         limits; this makes sure of it.
    Test:                python3 robot/test_tools.py todo2
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
    return "TODO 2 is not written yet (check_move in robot/behaviors.py)"
    # ====================================


async def walk(robot: Robot, vx: float, vy: float, wz_deg: float, duration: float) -> Result:
    """Walk at (vx, vy, wz_deg) for duration seconds, then stand still.

    vx forward m/s, vy left m/s, wz_deg counter-clockwise deg/s. The move and
    turn tools both call this.

    TODO 3 (Part 2) ------------------------------------------------------------
    Now:                 check_move (refuse with its reason); leave follow mode
                         (note = await leave_follow_mode(robot)); refuse with
                         FELL_MESSAGE if robot.fallen.
    Later (the job):     if robot.fallen, return FELL_MESSAGE; switch_to the
                         WALKING_CONTROLLER (and return its Result if it fails);
                         send the speed LLM_CMD_RATE times a second until
                         duration is up; stop (send zeros) and return
                         FELL_MESSAGE if robot.fallen turns true on the way;
                         end with a zero speed; return what it did.
    Gemini hears now:    with_note(note, await robot.queue(name, job, duration)).
                         Name it f"move vx={vx} vy={vy} wz={wz_deg} {duration}s".
    Why send it again and again: cmd_vel_mux (which lets the joystick win over
                         Gemini) forgets a speed after 0.5 s.
    Why check fallen twice: the robot can fall while this job waits in line, or
                         while it walks.
    Use:                 robot.send_speed, robot.sleep, robot.now, robot.switch_to
                         (never time.sleep: it freezes the whole server)
    Test:                python3 robot/test_tools.py todo3
    """
    # ========== TODO 3: YOUR CODE HERE ==========
    # Copy the shape of stand_up above: (1) now, (2) the job, (3) queue it.
    # NOW, before anything is queued:
    # 1. reason = check_move(vx, vy, wz_deg, duration). If there is a reason: return Result(False, reason).
    # 2. note = await leave_follow_mode(robot)
    # 3. If robot.fallen: return Result(False, FELL_MESSAGE).
    # THE JOB, which runs later, when the queue gets to it:
    # 4. async def job() -> Result:
    #        a. If robot.fallen: return Result(False, FELL_MESSAGE).
    #        b. res = await robot.switch_to(WALKING_CONTROLLER); if not res.ok: return res
    #        c. end = robot.now() + duration
    #           while robot.now() < end:
    #               if robot.fallen: send a zero speed and return Result(False, FELL_MESSAGE)
    #               robot.send_speed(vx, vy, wz_deg)
    #               await robot.sleep(1.0 / LLM_CMD_RATE)
    #        d. robot.send_speed(0, 0, 0)  (stand still)
    #        e. return Result(True, ...) saying what it did, e.g. f"moved vx={vx} vy={vy} wz={wz_deg} for {duration} s"
    # QUEUE IT, and return what Gemini hears now:
    # 5. return with_note(note, await robot.queue(f"move vx={vx} vy={vy} wz={wz_deg} {duration}s", job, duration))
    return not_written("TODO 3", "walk in robot/behaviors.py")
    # ====================================


# ============================================================ Part 3: follow
async def leave_follow_mode(robot: Robot) -> str:
    """Every motion calls this first, before it queues anything.

    TODO 5 (Part 3) ------------------------------------------------------------
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
    Test:                python3 robot/test_tools.py todo5
    """
    # ========== TODO 5: YOUR CODE HERE ==========
    # 1. If robot.following is False, there is nothing to do: return "".
    # 2. Turn the person follower off: await robot.stop_following()
    # 3. Stand still (the follower may have been walking): robot.send_speed(0, 0, 0)
    # 4. Return the note Gemini will read, e.g. "Stopped following the person first. "
    #    (end it with a space: the tool's own reply comes right after it)
    return ""  # for now: following never ends
    # ====================================


# ============================================================ Part 4: tricks
async def play_trick(robot: Robot, name: str) -> Result:
    """Play a trick from <repo>/tricks.

    Every trick in the lab is a policy trick: it plays its own controller (the
    job is play_policy_trick below).

    TODO 7, part 1 (Part 4) ----------------------------------------------------
    Now:                 an unknown name fails with f"unknown trick '{name}';
                         available: {list(robot.tricks)}"; leave follow mode.
    Later (the job):     play_policy_trick(robot, trick).
    Gemini hears now:    robot.queue(f"trick {name}", job, trick.total_time,
                         then_holding=...) with the note in front.
                         then_holding is the trick if it is a clip trick (it has
                         trick.clips: it will hold a pose), else None.
    Test:                python3 robot/test_tools.py todo7

    Optional, after the lab: the jump. Pupper's default walking policy can
    already jump (you have seen it on the gamepad). Give Gemini that jump:
    rename tricks/jump/trick.yaml.optional to trick.yaml, and make a trick of
    trick.kind == "reference" play with robot.play_reference_trick(trick)
    instead. Test: python3 robot/test_tools.py optional_jump
    """
    # ========== TODO 7: YOUR CODE HERE ==========
    # NOW:
    # 1. trick = robot.tricks.get(name). If it is None, fail, and list the real names: list(robot.tricks).
    # 2. note = await leave_follow_mode(robot)
    # THE JOB:
    # 3. job = lambda: play_policy_trick(robot, trick)
    #    (a lambda is a function in one line: robot.queue calls it later, when it's the trick's turn)
    # QUEUE IT:
    # 4. Decide then_holding: will this trick hold a pose when it's done? (Read the card above.)
    # 5. return with_note(note, await robot.queue(f"trick {name}", job, trick.total_time, then_holding=...))
    return not_written("TODO 7", "play_trick in robot/behaviors.py")
    # ====================================


async def play_policy_trick(robot: Robot, trick: Trick) -> Result:
    """The job that plays a policy trick: give the legs to the trick's controller,
    wait for it, then leave the robot in the right pose.

    TODO 7, part 2 (Part 4) ----------------------------------------------------
    1. A clip trick that is already holding its pose (robot.holding_now is
       trick): nothing to do; return f"already doing {trick.name}".
    2. A trick that is not a clip trick and whose controller is still active
       (it is holding the end of its last run): relax first, with
       switch_to(None). Switching to a controller that is already active does
       nothing, so without this the trick would not play again.
    3. switch_to(trick.controller), then wait trick.total_time + 0.3 s. If the
       robot fell, return f"{trick.name} ended in a fall: {FELL_MESSAGE}".
    4. Leave it in the right pose, and say which:
       - a clip trick (trick.clips) now holds its looping clip: set
         robot.holding_now = trick; say it stays trick.end_pose, list
         trick.actions, and name trick.exit_clip (any other motion plays it first);
       - trick.end_pose == "standing": hand the legs back to the walking
         policy, and say so (or that it couldn't);
       - otherwise the trick's controller holds its final pose: say that.
    Must always be true: every outcome says what pose the robot is in now.
    Use:                 robot.switch_to, robot.is_active, robot.sleep, robot.fallen
    """
    # ========== TODO 7: YOUR CODE HERE ==========
    # Write steps 1-4 of the card above, in order. Each step that can fail returns a
    # Result(False, ...) that says why; every success says which pose the robot is in now.
    # Hints: is a clip trick?        trick.clips (a non-empty list)
    #        is its controller on?   await robot.is_active(trick.controller)
    #        relax / take the legs:  await robot.switch_to(None) / await robot.switch_to(trick.controller)
    #        wait for the trick:     await robot.sleep(trick.total_time + 0.3)
    return not_written("TODO 7", "play_policy_trick in robot/behaviors.py")
    # ====================================


# ============================================================ Part 5: sit, stay, shake
async def trick_action(robot: Robot, action: str) -> Result:
    """Play one of a clip trick's actions (e.g. shake a paw while sitting).

    TODO 9 (Part 5) ------------------------------------------------------------
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
    Test:                python3 robot/test_tools.py todo9
    """
    # ========== TODO 9: YOUR CODE HERE ==========
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
    return not_written("TODO 9", "trick_action in robot/behaviors.py")
    # ====================================
