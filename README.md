<div align="center">
<img width="1200" height="475" alt="GHBanner" src="https://github.com/user-attachments/assets/0aa67016-6eaf-458a-adb2-6e31a0763ed6" />
</div>

# Gemini Pupper

Talk to Pupper, and it listens, looks and does what you ask. Gemini Live is
the brain: a foundation model that hears you, sees through the camera and
talks back. Trained policies are the muscles. In between are the tools: the
only way Gemini can move the robot, and the only way it learns what really
happened. In CS 123, Lab 6 (*A Foundation Model on a Leash*), you write them.

**Gemini Pupper was created by [Peng Xu](https://scholar.google.com/citations?user=460NWeQAAAAJ&hl=en)
(Google DeepMind)**, original repo [sippeyxp/gemini-pupper](https://github.com/sippeyxp/gemini-pupper).
This is the CS 123 version: tools in Python, trick policies, and safety checks.

## What's where

```
  You speak ──► Gemini Live ──► tool call ──► tools.py       what Gemini reads; words → a robot command
                     ▲                             │
                     │                             ▼
                     │                        behaviors.py   is it allowed, and what the robot does
                     │                             │
                     └──── the reply (a Result) ◄──┤
                                                   ▼
                                              robot_api.py   (provided) queue, controllers, falls, e-stop
```

| File | What it is | Yours? |
| --- | --- | --- |
| `robot/prompt.md` | Gemini's system prompt: who Pupper is, how it behaves | TODO 1, 6, 11 |
| `robot/tools.py` | Every tool Gemini can call: what Gemini reads, and a short body | TODO 4, 6, 8, 10 |
| `robot/behaviors.py` | What the robot does: check, queue a job, report | TODO 2, 3, 5, 7, 9 |
| `robot/test_tools.py` | Tests with a fake robot: `python3 robot/test_tools.py todo3` | run them |
| `robot/chat.py` | Talk to Gemini in text and watch every tool call: `--toy` (Peng's demo), your tools on a fake robot (default), or `--robot` | run it |
| `tricks/sit_stay_shake/` | The clip trick you train in Part 5 (`get_trick.py` makes it) | TODO 10 (its `trick.yaml`) |
| `robot/robot_api.py` | The Robot API: the queue, the legs, falls, follow mode, the e-stop | no: read the table at the top |
| `robot/tool_registry.py` | Turns `@tool` functions into what Gemini reads | no |
| everything else | the web app, the robot server, the launch files | no |

The TODOs are numbered 1–11 in the order of the lab handout. Each one has a
short card in the code: what happens now, what happens later, what Gemini
hears, what must always be true, and which test checks it.

## Setup (once, on the Pupper)

```bash
git clone https://github.com/<you>/gemini_pupper.git ~/gemini_pupper
cd ~/gemini_pupper
robot/setup.sh
```

`setup.sh` installs Node in your home folder, builds the web app, checks the
Python packages and asks for your Gemini API key (from
[Google AI Studio](https://aistudio.google.com/apikey)). The key is saved in
`~/.config/gemini-pupper/api_key`, never in this repo. Run `setup.sh` again
any time; it is safe.

The Pupper must also be logged into W&B (`wandb login`) with the account you
train tricks with.

## Running

On the Pupper, on the ground, with clear space around it:

```bash
robot/start.sh --kiosk    # robot + the app on Pupper's own screen (uses its mic and speaker)
robot/start.sh            # robot only; open the app from your laptop (below)
robot/stop.sh             # relax the motors and stop everything
```

From your laptop: `ssh -N -L 8000:localhost:8000 pi@pupper<N>.local`, then
open http://localhost:8000, open **Settings**, paste your key and press
**WAKE PUPPER**. The debug view shows every tool call and its result.

The e-stop is the gamepad's right stick (press it): it relaxes the motors,
whatever Gemini is doing.

## Talk to Gemini in text

`robot/chat.py` (based on Peng Xu's Gemini Live example) runs the same loop as
the web app, in your terminal: you type, Gemini calls tools, and you see every
call and every reply. It needs `python3 -m pip install --user google-genai`
(`setup.sh` installs it on the Pupper) and your key in `GEMINI_API_KEY` or
`~/.config/gemini-pupper/api_key`.

```bash
python3 robot/chat.py --toy      # one toy tool that only prints: see how the loop works
python3 robot/chat.py            # your prompt and tools, on a fake robot: nothing moves
python3 robot/chat.py --robot    # your tools on the real Pupper (through the robot server): it moves!
```

## After you change something

| You changed | Then |
| --- | --- |
| `robot/prompt.md` | reconnect in the app |
| `robot/tools.py` or `robot/behaviors.py` | `python3 robot/test_tools.py`, then `robot/stop.sh && robot/start.sh` |
| a trick (`get_trick.py` or a `trick.yaml`) | `robot/stop.sh && robot/start.sh` |

## Tricks

Every trick is a policy, so the robot is always in one simple state: walking,
one trick, or motors off. Each folder under `tricks/` with a `trick.yaml` is a
trick Gemini can play (`robot/tricks.py` lists the fields). Tricks are trained
in [pupper-mjlab](https://github.com/cs123-stanford/pupper-mjlab); training
puts the policy on W&B, and one command fetches it:

```bash
python3 robot/get_trick.py <entity>/mjlab/<run-id> --name my_trick
robot/stop.sh && robot/start.sh
```

A clip trick holds a pose and takes requests: `actions` in its `trick.yaml`
lists the clips Gemini may ask for (with the `trick_action` tool), and
`exit_clip` is the clip that stands back up.

## More

- [Peng Xu's write-up: Interactive Robot Dog with Gemini Live](docs/interactive-robot-dog.md)
- [System architecture](docs/architecture.md)
