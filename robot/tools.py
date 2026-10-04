"""The tools Gemini can call.

Each tool is one Python function with a @tool line above it. The @tool line is
what Gemini reads: a description and the parameters. Gemini decides when to
call a tool, and what to pass, from these words alone. The function is what
runs on the robot. Whatever it returns (a Result) is sent back to Gemini, so
Gemini knows what really happened.

The web app asks the robot server for this list (GET /tools) when it connects,
and sends every tool call to POST /tools/<name>. So after you change this file,
restart the server (robot/stop.sh, then robot/start.sh) and reconnect: no web
app rebuild needed.

Directions here use the robot's convention: positive y is LEFT, and a positive
turn is to the LEFT (counter-clockwise).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from tool_server import LIMITS, Result, ToolServer

log = logging.getLogger("tools")

# "Run" means at least this fast, in m/s (the walking policy switches to its
# running gait above about 0.5 m/s).
RUN_MIN_SPEED = 1.0
RUN_DEFAULT_SPEED = 1.2
TURN_SPEED = 60.0  # deg/s

# Added to every motion tool's description.
ENDS_FOLLOW = (
  " If follow mode is on, this ends it: first tell the user,"
  ' e.g. "Let me stop following you and ...".'
)


# --------------------------------------------------------------------- the registry
@dataclass
class Param:
  """One parameter of a tool, as Gemini sees it."""

  type: str  # "string", "number", "integer" or "boolean"
  description: str
  enum: list | Callable[[ToolServer], list] | None = None  # allowed values
  required: bool = True


@dataclass
class Tool:
  name: str
  description: str | Callable[[ToolServer], str]
  params: dict[str, Param]
  run: Callable[..., Awaitable[Result]]


TOOLS: dict[str, Tool] = {}


def tool(description: str | Callable[[ToolServer], str], **params: Param):
  """Register the function below as a tool. Its name is the function's name.

  ``description`` (and a Param's ``enum``) may be a function of the robot, for
  lists that depend on what is installed, like the tricks.
  """

  def register(fn):
    TOOLS[fn.__name__] = Tool(fn.__name__, description, params, fn)
    return fn

  return register


def _resolve(value, robot: ToolServer):
  return value(robot) if callable(value) else value


def declarations(robot: ToolServer) -> list[dict]:
  """Every tool in the format Gemini expects. A tool whose choices list is
  empty (say, no trick actions installed) is left out."""
  out = []
  for t in TOOLS.values():
    props, required, empty = {}, [], False
    for name, p in t.params.items():
      prop: dict[str, Any] = {"type": p.type.upper(), "description": p.description}
      enum = _resolve(p.enum, robot)
      if enum is not None:
        if not enum:
          empty = True
        prop["enum"] = [str(v) for v in enum]
      props[name] = prop
      if p.required:
        required.append(name)
    if empty:
      continue
    decl: dict[str, Any] = {"name": t.name, "description": _resolve(t.description, robot)}
    if props:
      decl["parameters"] = {"type": "OBJECT", "properties": props, "required": required}
    out.append(decl)
  return out


_TYPES = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,)}


async def call(robot: ToolServer, name: str, args: dict) -> Result:
  """Check a tool call against its declaration, then run it."""
  t = TOOLS.get(name)
  if t is None:
    return Result(False, f"unknown tool {name}; the tools are {sorted(TOOLS)}")
  args = dict(args or {})
  extra = sorted(set(args) - set(t.params))
  if extra:
    return Result(False, f"{name} has no parameter {extra}; it takes {sorted(t.params)}")
  for pname, p in t.params.items():
    if pname not in args:
      if p.required:
        return Result(False, f"{name} needs {pname}: {p.description}")
      continue
    v = args[pname]
    if isinstance(v, bool) and p.type != "boolean" or not isinstance(v, _TYPES[p.type]):
      return Result(False, f"{name}: {pname} must be a {p.type}, not {v!r}")
    enum = _resolve(p.enum, robot)
    if enum is not None and v not in enum:
      return Result(False, f"{name}: {pname} must be one of {list(enum)}, not {v!r}")
  try:
    return await t.run(robot, **args)
  except Exception as e:  # a bug in a tool must not crash the server
    log.exception("tool %s failed", name)
    return Result(False, f"{name} failed on the robot: {type(e).__name__}: {e}")


# --------------------------------------------------------------------- basic tools
@tool("Stand up and turn on walking. Needed before moving, and to stand up after a trick." + ENDS_FOLLOW)
async def stand_up(robot: ToolServer) -> Result:
  return await robot.activate_walking()


@tool(
  "Relax all motors so the robot lies down. Use when the user says sleep, relax"
  " or lie down." + ENDS_FOLLOW
)
async def lie_down(robot: ToolServer) -> Result:
  return await robot.deactivate()


@tool("Emergency stop: cancel everything queued and stand still.")
async def stop(robot: ToolServer) -> Result:
  return await robot.immediate_stop()


@tool("Check what the robot is doing right now: walking, in a trick, following, motors off, or fallen over.")
async def robot_status(robot: ToolServer) -> Result:
  return await robot.mode()


def _trick_list(robot: ToolServer) -> str:
  return "\n".join(f'- "{name}": {t.description}' for name, t in robot.tricks.items())


@tool(
  lambda robot: (
    "Play a trick. Each says whether it starts standing or lying down; from the"
    " other pose it still plays but looks wrong. A trick keeps its final pose"
    " until the next motion or stand_up." + ENDS_FOLLOW + "\nTricks:\n" + _trick_list(robot)
  ),
  name=Param("string", "The exact trick name.", enum=lambda robot: list(robot.tricks)),
)
async def play_trick(robot: ToolServer, name: str) -> Result:
  return await robot.trick(name)


# --------------------------------------------------------------------- your tools
# ========== YOUR CODE HERE: Part 1: motion tools ==========
# TODO(student): finish move, turn and follow below. For each one:
# 1. Write the description and the parameter descriptions. Gemini picks a tool,
#    and fills in its parameters, from these words alone. Put the robot's real
#    limits in them (LIMITS.vx_max and so on), and add ENDS_FOLLOW to motion tools.
# 2. Write the body. It calls the robot (robot.move(...), robot.set_following(...))
#    and returns the Result, so Gemini hears what really happened.
# Directions: the robot's +y is LEFT, and a positive turn is to the LEFT.


@tool(
  "TODO(student): describe the move tool for Gemini.",
  direction=Param("string", "TODO(student)", enum=["forward", "backward", "left", "right"]),
  run=Param("boolean", "TODO(student)", required=False),
  speed=Param("number", "TODO(student)", required=False),
  duration=Param("number", "TODO(student)", required=False),
)
async def move(
  robot: ToolServer,
  direction: str,
  run: bool = False,
  speed: float | None = None,
  duration: float = 1.5,
) -> Result:
  # TODO(student): turn direction/run/speed/duration into vx (forward) and vy
  # (left) in m/s, then `return await robot.move(vx, vy, 0.0, duration)`.
  # In this lab, "run" means RUN_MIN_SPEED (1.0 m/s) or faster, forward or
  # backward. Make sure of it here, in code, not only in the description.
  return Result(False, "move is not implemented yet: TODO(student) in robot/tools.py")


@tool(
  "TODO(student): describe the turn tool for Gemini.",
  direction=Param("string", "TODO(student)", enum=["left", "right"]),
  angle=Param("number", "TODO(student)", required=False),
)
async def turn(robot: ToolServer, direction: str, angle: float = 45.0) -> Result:
  # TODO(student): turn in place at TURN_SPEED deg/s for as long as `angle`
  # takes: robot.move(0.0, 0.0, wz_deg, seconds). Left is positive.
  return Result(False, "turn is not implemented yet: TODO(student) in robot/tools.py")


@tool(
  "TODO(student): describe the follow tool for Gemini.",
  enabled=Param("boolean", "TODO(student)"),
)
async def follow(robot: ToolServer, enabled: bool) -> Result:
  # TODO(student): robot.set_following(enabled) starts or stops following.
  return Result(False, "follow is not implemented yet: TODO(student) in robot/tools.py")


# ========== YOUR CODE HERE: Part 2: the trick_action tool ==========
def _action_list(robot: ToolServer) -> str:
  """The installed actions, one per line, for your description."""
  return "\n".join(
    f'- "{aid}" (during "{t.name}"): {t.actions[clip]}' for aid, (t, clip) in robot.action_ids().items()
  )


@tool(
  # TODO(student): describe trick_action for Gemini. A description can be a
  # function of the robot, like play_trick's above, so it can list the actions
  # with _action_list(robot). Say what has to happen first.
  lambda robot: "TODO(student): describe trick_action for Gemini.",
  action=Param("string", "TODO(student)", enum=lambda robot: list(robot.action_ids())),
)
async def trick_action(robot: ToolServer, action: str) -> Result:
  # TODO(student): call the robot side (robot.trick_action) and return its Result.
  return Result(False, "trick_action is not implemented yet: TODO(student) in robot/tools.py")
