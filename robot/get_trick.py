#!/usr/bin/env python3
"""Fetch a trick from Weights & Biases into tricks/<name>/.

Pupper trick training (pupper-mjlab's Mjlab-Tracking-Flat-Pupper-v3) uploads the
trick policy to its W&B run as policy.json; the training log prints the exact
command to run here. The Pupper is already logged into W&B for policy deploys.

    python3 robot/get_trick.py <entity>/mjlab/<run-id> --name sit
    python3 robot/get_trick.py mjlab/<run-id> --name sit          # your default entity
    python3 robot/get_trick.py --motion <entity>/mjlab/sit --name sit_replay   # replay only

A policy trick lands as tricks/<name>/policy.json. --motion instead fetches a
motion artifact uploaded with pupper-mjlab's upload_motion and installs its
joint recording as a replay trick (open loop, no policy): the quick way to see a
design on the robot before training it.

If tricks/<name>/trick.yaml does not exist yet a template is written; edit its
description (it is what Gemini reads). Restart Gemini Pupper afterwards
(robot/stop.sh, then robot/start.sh): the launch file loads one controller per
policy trick at startup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

TRICK_DIR = Path(__file__).resolve().parent.parent / "tricks"
VALIDATOR = Path.home() / "pupper_gait_deploy" / "download_policy.py"


def resolve_run_path(run: str, project: str, entity: str | None) -> str:
  """Accept entity/project/run-id, project/run-id or a bare run id."""
  import wandb

  parts = run.split("/")
  if len(parts) == 3:
    return run
  if len(parts) == 2:
    project, run = parts
  entity = entity or wandb.Api().default_entity
  if entity is None:
    sys.exit("Could not determine the W&B entity; pass a full entity/project/run-id path.")
  return f"{entity}/{project}/{run}"


def resolve_artifact(name: str, project: str, entity: str | None) -> str:
  import wandb

  parts = name.split("/")
  if len(parts) == 1:
    name = f"{project}/{name}"
  if len(name.split("/")) == 2:
    name = f"{entity or wandb.Api().default_entity}/{name}"
  return name if ":" in name else name + ":latest"


def fetch_policy(run_path: str, dest: Path) -> dict:
  import wandb

  run = wandb.Api().run(run_path)
  if "policy.json" not in [f.name for f in run.files()]:
    sys.exit(
      f"{run_path} has no policy.json yet. Trick runs upload it at every checkpoint "
      "save and on Ctrl+C; wait for the first checkpoint, or check the run id."
    )
  with tempfile.TemporaryDirectory() as tmp:
    path = Path(run.file("policy.json").download(root=tmp, replace=True).name)
    policy = json.loads(path.read_text())
    if "trick" not in policy or "motion" not in policy:
      sys.exit(f"{run_path}'s policy.json is not a trick policy (no trick/motion blocks).")
    if VALIDATOR.exists():  # the controller's own checks: layout, shapes, clips
      check = subprocess.run([sys.executable, str(VALIDATOR), "--validate-only", str(path)])
      if check.returncode != 0:
        sys.exit("validation failed; not installing")
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest / "policy.json")
  print(f"Run {run.name} ({run_path}) -> {dest / 'policy.json'}")
  return policy


def fetch_motion(artifact_name: str, dest: Path) -> None:
  import wandb

  artifact = wandb.Api().artifact(artifact_name)
  with tempfile.TemporaryDirectory() as tmp:
    csv = Path(artifact.download(root=tmp)) / "robot.csv"
    if not csv.exists():
      sys.exit(
        f"{artifact_name} has no robot.csv (the joint recording). Upload the motion with "
        "upload_motion after saving it with save_robot_csv."
      )
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(csv, dest / "motion.csv")
  print(f"Motion {artifact_name} -> {dest / 'motion.csv'}")


def write_template(dest: Path, name: str, kind: str, policy: dict | None) -> None:
  spec = dest / "trick.yaml"
  if spec.exists():
    print(f"Kept the existing {spec}")
    return
  lines = [
    f"# {name}: fetched with get_trick.py. Edit the description -- it is what Gemini reads",
    "# when deciding whether to play this trick.",
    f"description: TODO describe what the robot does in {name}.",
  ]
  if kind == "policy":
    lines += ["type: policy", "policy: policy.json"]
  else:
    lines += ["type: replay", "motion: motion.csv"]
  lines += ["start_pose: standing", "end_pose: standing"]
  if kind == "policy":
    lines.append("max_body_angle_deg: 60   # the tilt e-stop while the trick plays")
    clips = (policy or {}).get("trick", {}).get("clips", [])
    if clips:
      lines += [
        "# This policy has clips. Name the ones Gemini may ask for while the trick runs,",
        "# and the clip that returns to standing (played before any other motion):",
        "# actions:",
      ]
      lines += [f"#   {c['name']}: TODO what this clip does" for c in clips]
      lines += ["# exit_clip: <clip>", "# end_pose: <the pose the looping clip holds>"]
  spec.write_text("\n".join(lines) + "\n")
  print(f"Wrote a template {spec}; edit its description.")


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  parser.add_argument("run", nargs="?", help="W&B training run: entity/project/run-id, project/run-id or run-id")
  parser.add_argument("--name", required=True, help="trick name: the folder under tricks/ and Gemini's id")
  parser.add_argument("--motion", help="instead of a run: a motion artifact, installed as a replay trick")
  parser.add_argument("--project", default="mjlab")
  parser.add_argument("--entity", default=None)
  args = parser.parse_args()
  if bool(args.run) == bool(args.motion):
    parser.error("pass a training run or --motion, not both")

  dest = TRICK_DIR / args.name
  if args.motion:
    fetch_motion(resolve_artifact(args.motion, args.project, args.entity), dest)
    write_template(dest, args.name, "replay", None)
  else:
    policy = fetch_policy(resolve_run_path(args.run, args.project, args.entity), dest)
    trick = policy["trick"]
    print(f"Trick '{trick['name']}': {trick['frames']} frames, {trick['duration_s']:.1f} s")
    for c in trick.get("clips", []):
      print(f"  clip {c['name']:14} {(c['end'] - c['start']) / trick['fps']:.1f} s"
            f"{' loops' if c.get('loop') else ''}{' -> ' + str(c['next']) if c.get('next') is not None else ''}")
    write_template(dest, args.name, "policy", policy)
  print("Restart Gemini Pupper (robot/stop.sh, then robot/start.sh) to load it.")


if __name__ == "__main__":
  main()
