# Gemini Pupper

Talk to Pupper, and it listens, looks, and does what you ask: walks, turns,
runs, follows you, sits, stays, shakes a paw, and dances. Gemini Live is the
brain, trained policies are the muscles, and the tool layer in between -- the
part that turns "come here" into motor commands and tells Gemini what really
happened -- is yours to build.

This is the starter code for CS 123 lab 6. The robot stack, the web app and
the trick pipeline work out of the box; the tools Gemini can use are almost
all missing. Search for `YOUR CODE HERE` / `TODO(student)`.

## Setup (once)

You need your own Gemini API key (from [Google AI Studio](https://aistudio.google.com/apikey)).
Never commit it or paste it into a file in this repo.

On your laptop (Node.js 20 or newer), build the web app and copy it to the robot:

```bash
npm install
npm run build
rsync -a dist/ pi@pupper<N>.local:~/gemini_pupper/dist/
```

On the Pupper, for the on-robot screen (kiosk) only, store the key where
`robot/start.sh --kiosk` reads it:

```bash
mkdir -p ~/.config/gemini-pupper && (umask 077; cat > ~/.config/gemini-pupper/api_key)
# paste the key, press Enter, then Ctrl-D
```

The Pupper must be logged into W&B (`wandb login`) with the same account you
train tricks with -- you did this in lab 4.

## Running

On the Pupper:

```bash
robot/start.sh            # robot stack + robot server on localhost:8000 (~40 s)
robot/stop.sh             # relax the motors and stop everything
```

From your laptop, forward the port and open the app:

```bash
ssh -N -L 8000:localhost:8000 pi@pupper<N>.local
# then browse to http://localhost:8000, open Settings, paste your Gemini key,
# and press WAKE PUPPER
```

`robot/start.sh --kiosk` also shows the app full-screen on the robot's own
screen, using a USB microphone and the robot's speaker.

### A faster loop while you write tools

Rebuilding and copying `dist/` after every change to `services/geminiLive.ts`
gets old fast. Run the app on your laptop instead, and point it at the robot
through the same SSH tunnel:

```bash
npm run dev               # https://localhost:5173 (accept the self-signed certificate)
# Settings -> Robot API URL: http://localhost:8000
```

It reloads on every save. Changes to `robot/*.py` need the robot server
restarted (`robot/stop.sh && robot/start.sh`).

### Checking your tool layer at the desk

```bash
python3 robot/test_tools.py           # all parts; or part1 / part2 / part3
```

Contract tests for `robot/tool_server.py` against a fake robot: no ROS, no
Pupper, no Gemini. They check what each tool does and what Gemini is told.
Run them after every change (your coding agent can run them too).

## Tricks

Every folder under `tricks/` with a `trick.yaml` is a trick Gemini can play.
Two ship with the repo, the worked example from pupper-mjlab:

- `sit`: a trained tracking policy. Pupper sits like a dog, holds, stands up.
- `sit_replay`: the same motion played open loop, with no policy. Compare them.

New tricks are designed and trained in
[pupper-mjlab](https://github.com/cs123-stanford/pupper-mjlab) (the
`CS123_Pupper_Tricks` notebook). Training uploads the policy to W&B, and one
command on the Pupper fetches it:

```bash
python3 robot/get_trick.py <entity>/mjlab/<run-id> --name my_trick         # a trained policy
python3 robot/get_trick.py --motion mjlab/my_trick --name my_trick_replay  # plain replay, no training
robot/stop.sh && robot/start.sh      # the launch file loads one controller per policy trick
```

`get_trick.py` writes a `trick.yaml` template. Its `description` is what
Gemini reads when deciding whether your trick is what someone asked for, so
write it for Gemini. A clip trick (a pose it holds, plus moves on request)
also lists `actions` (clips Gemini may ask for while the trick runs) and an
`exit_clip` (played by itself before any other motion). See `robot/tricks.py`
for every field.

**Safety:** test new tricks with Pupper on the ground, clear space around it,
and a hand near the e-stop (press the gamepad's right stick). A new
trained policy runs on the robot for the first time only with a TA's OK. The
motors get hot: if Pupper is hot to the touch or a motor faults, stop and let
it cool down.

## Files

| File | What it does |
|---|---|
| `services/geminiLive.ts` | **The lab.** `buildTools` (the tools Gemini sees) and the dispatch that calls the robot. The rest is the Gemini Live connection. |
| `robot/tool_server.py` | **Also the lab.** What each tool does on the robot, and what it reports back. Queue, controller switching and trick playback are provided. |
| `robot/test_tools.py` | Desk-side contract tests for `tool_server.py`, against a fake robot. |
| `tricks/` | Custom tricks: `trick.yaml` + a policy JSON or a joint CSV. |
| `robot/get_trick.py` | Fetches a trained trick (or a motion for plain replay) from W&B. |
| `robot/tricks.py` | Loads `tricks/`; the `trick.yaml` fields. |
| `robot/server.py` | HTTP API on port 8000 (one endpoint per tool) and the built web app. |
| `robot/launch/` | Robot stack: the course controllers, a command mux, person detection and following, one controller per policy trick. |
| `robot/start.sh`, `robot/stop.sh` | Start and stop everything on the Pupper. |
| `robot/kiosk.py` | Drives the app on the robot's own screen. |
| `services/robotBridge.ts` | The browser's HTTP client for the robot server. |
| `App.tsx`, `components/` | The face, settings and debug panel. |
| `AGENTS.md`, `CLAUDE.md` | Rules for your coding agent: safety, what's yours, how to check work. |

## How the pieces talk

```
 you ──voice──> browser (App.tsx) ──audio + camera──> Gemini Live
                    ^                                     │
                    │ {success, message}          function call
                    │                                     v
                    └──── geminiLive.ts dispatch <────────┘
                                  │ HTTP (robotBridge.ts)
                                  v
              robot/server.py ──> tool_server.py queue ──> ROS 2
                                                           │
       /llm_cmd_vel ─> cmd_vel_mux ─> gemini_walk      (walking)
       controller switch ─> trick_<name>, /trick_<name>/clip   (tricks, clips)
       person_follower services                         (follow mode)
```

The joystick always outranks Gemini: `cmd_vel_mux` prefers it whenever it is
sending. Pressing the right stick is the e-stop.

## Notes

- The web app talks to Gemini directly from the browser with your key; the
  robot server never sees it.
- `GET /system/mode`, `/queue/status`, `/animations`, `/trick_actions` and
  `/limits` are handy with `curl` while debugging (they don't move anything).
  Every `POST` does.
- Logs: `/tmp/gemini-pupper/robot.log` (ROS) and `/tmp/gemini-pupper/server.log`
  (the robot server, including every tool call and how it ended).
