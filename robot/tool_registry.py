"""The tool registry: turns the @tool functions in tools.py into what Gemini reads,
and checks every call against it before running it (provided).

You don't change this file. In tools.py:

    @tool("What Gemini reads about the tool.",
          speed=Param("number", "What Gemini reads about this parameter.", required=False))
    async def my_tool(robot, speed=0.4) -> Result:
        ...

A description may contain {tricks} or {actions}: the installed tricks, or the
installed trick actions, one per line. A parameter's enum (the values Gemini
may pass) may be TRICK_NAMES or ACTION_IDS for the same lists.

The web app asks the robot server for the declarations (GET /tools) when it
connects, and sends every call to POST /tools/<name>, which runs call() below.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from robot_api import Result, Robot

log = logging.getLogger("tools")


@dataclass
class Param:
    """One parameter of a tool, as Gemini sees it."""

    type: str  # "string", "number", "integer" or "boolean"
    description: str
    enum: list | Callable[[Robot], list] | None = None  # allowed values
    required: bool = True


@dataclass
class Tool:
    name: str
    description: str
    params: dict[str, Param]
    run: Callable[..., Awaitable[Result]]


TOOLS: dict[str, Tool] = {}


def tool(description: str, **params: Param):
    """Register the function below as a tool. Its name is the function's name."""

    def register(fn):
        TOOLS[fn.__name__] = Tool(fn.__name__, description, params, fn)
        return fn

    return register


def TRICK_NAMES(robot: Robot) -> list:
    """enum: the installed tricks."""
    return list(robot.tricks)


def ACTION_IDS(robot: Robot) -> list:
    """enum: the installed trick actions."""
    return list(robot.action_ids())


def _trick_list(robot: Robot) -> str:
    return "\n".join(f'- "{name}": {t.description}' for name, t in robot.tricks.items())


def _action_list(robot: Robot) -> str:
    lines = [f'- "{aid}" (during "{t.name}"): {t.actions[clip]}' for aid, (t, clip) in robot.action_ids().items()]
    return "\n".join(lines) or "(none installed yet)"


def _describe(text: str, robot: Robot) -> str:
    if "{tricks}" in text:
        text = text.replace("{tricks}", _trick_list(robot))
    if "{actions}" in text:
        text = text.replace("{actions}", _action_list(robot))
    return text


def _resolve(value, robot: Robot):
    return value(robot) if callable(value) else value


def declarations(robot: Robot) -> list[dict]:
    """Every tool in the format Gemini expects."""
    out = []
    for t in TOOLS.values():
        props, required = {}, []
        for name, p in t.params.items():
            prop: dict[str, Any] = {"type": p.type.upper(), "description": p.description}
            enum = _resolve(p.enum, robot)
            if enum:  # an empty list (nothing installed yet) is left out: Gemini rejects it
                prop["enum"] = [str(v) for v in enum]
            props[name] = prop
            if p.required:
                required.append(name)
        decl: dict[str, Any] = {"name": t.name, "description": _describe(t.description, robot)}
        if props:
            decl["parameters"] = {"type": "OBJECT", "properties": props, "required": required}
        out.append(decl)
    return out


_TYPES = {"string": (str,), "number": (int, float), "integer": (int,), "boolean": (bool,)}


async def call(robot: Robot, name: str, args: dict) -> Result:
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
        if enum is not None and not enum:
            return Result(False, f"{name}: nothing is installed for {pname} yet, so it can't be used")
        if enum is not None and v not in enum:
            return Result(False, f"{name}: {pname} must be one of {list(enum)}, not {v!r}")
    try:
        return await t.run(robot, **args)
    except Exception as e:  # a bug in a tool must not crash the server
        log.exception("tool %s failed", name)
        return Result(False, f"{name} failed on the robot: {type(e).__name__}: {e}")
