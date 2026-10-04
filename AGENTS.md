# Notes for coding agents (CS 123, Gemini Pupper lab)

You are helping a Stanford CS 123 student with the Gemini Pupper lab (lab 6).
The student is learning. Explain what you change and why, keep changes small
enough to review, and leave the decisions that are the point of the lab (tool
design, clip design, what to refuse and why) for the student to make with you,
not for you to make alone. The student has to be able to explain every line
they submit.

## What this repo is

Pupper is a real robot dog: 12 motors, a Raspberry Pi, a camera. Gemini Live
(in the browser) talks with people and calls **tools**. The tools are Python:
the web app gets Gemini's prompt (`robot/prompt.md`) and tool list
(`robot/tools.py`) from the robot server (`robot/server.py`, port 8000), and
sends every tool call back to it. `robot/tool_server.py` runs the motions one
at a time and drives the ROS 2 controllers. Trick policies are trained in
pupper-mjlab and fetched from W&B with `robot/get_trick.py`.

| Student work (`YOUR CODE HERE` / `TODO(student)`) | Provided (don't rewrite) |
| --- | --- |
| `robot/prompt.md`: Gemini's prompt | The web app (`App.tsx`, `components/`, `services/`): students don't need to touch TypeScript |
| `robot/tools.py`: `move`, `turn`, `follow`, `trick_action` (descriptions and code) | The tool registry and the basic tools at the top of `tools.py` |
| `robot/tool_server.py`: `check_move`, `move`'s walking loop, `_leave_follow_mode`, `trick_action` | The queue, controller switching, tricks, clips and fall recovery in `tool_server.py` |
| `tricks/sit_stay_shake/trick.yaml` (after training): description, `actions`, `exit_clip` | `robot/server.py`, `robot/tricks.py`, `robot/launch/`, the shell scripts, `kiosk.py`, `get_trick.py` |
| In pupper-mjlab: `tricks/sit_stay_shake.py` (or the Sit_Stay_Shake notebook): `cut`, `hold`, `mirror`, the clips and `ORDER` | The rest of pupper-mjlab |

If a provided file looks wrong, tell the student and let them ask a TA; don't
patch infrastructure to make a symptom go away.

## Safety rules (these override everything else)

1. **Never move the robot without the student's explicit OK, right then.**
   That includes `robot/start.sh`, `curl` to any POST endpoint of the robot
   server, `ros2 topic pub`, `ros2 control switch_controllers`, and anything
   that activates a controller. Say what will happen and wait. The student must
   be at the robot with a hand near the e-stop.
2. **Simulate first.** A new or changed motion goes through the motion report
   and the physics replay (`play_motion.py`, verdict HOLDS UP / WOBBLES /
   FALLS) before it goes anywhere near the robot. A trained policy is scored
   the same way (`play_motion.py --checkpoint`) and watched in the viewer.
3. **New trained policies need a TA's OK** before their first run on the
   robot. A badly trained contact-heavy trick can slam a paw or the body into
   the ground.
4. **Respect the limits.** Don't raise `MoveLimits`, `max_body_angle_deg`,
   joint limits, speed caps or gains to make something "work". Motion design
   reports should show IK error under 2 mm, nothing below the ground, joint
   speeds under about 15 rad/s and no joint at its limit.
5. **Heat.** The motors get hot. If the student says the robot is hot or a
   motor faults, stop testing and let it cool; don't retry in a loop.
6. **No secrets in files.** Never write an API key into the repo, a commit, a
   log or the web app. The Gemini key lives in
   `~/.config/gemini-pupper/api_key` on the robot (and in the browser's
   Settings); W&B uses `wandb login`.

## How to check work without the robot

- `python3 robot/test_tools.py` (or `part1` / `part2` / `robot`): tests with a
  fake robot. Run them after every change to `tools.py` or `tool_server.py`.
  They check what the tools do, not how they are written.
- In pupper-mjlab: `uv run python -m mjlab.tasks.tracking.config.pupper.tricks.sit_stay_shake`
  checks `cut`, `hold` and `mirror` and builds the library;
  `uv run python -m mjlab.tasks.tracking.config.pupper.play_motion <motion>.npz`
  replays it with physics (add `--checkpoint` to score a trained policy).

## Conventions

- Every tool returns a Result (`{success, message}`), and Gemini reads the
  message. Say what happened, or what was wrong and what would work instead.
- Rules are enforced on the robot, not only in the prompt: the prompt and the
  tool descriptions tell Gemini what to do; the code makes sure it happens.
- Motion goes through the queue (`_enqueue`); use `await asyncio.sleep`, never
  `time.sleep`, in the server.
- Units: metres, seconds, degrees. Directions use the robot's convention:
  +y is left, and a positive turn is to the left.
- After changing `tools.py` or `tool_server.py`, restart the server
  (`robot/stop.sh`, then `robot/start.sh`). After changing `prompt.md`,
  reconnect in the app.
- The robot is called Pupper. Gemini Pupper was created by Peng Xu (Google
  DeepMind); keep his credit in the README and the app.
