# -*- coding: utf-8 -*-
"""Runtime for LLM-written effect() jokers inside MiniBalatro."""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Callable

from cardgen.engine.cards import CHIP_BY_RANK, RANK_VALUE, Card

ALLOWED_CALLS = frozenset(
    {
        "len",
        "set",
        "sum",
        "min",
        "max",
        "abs",
        "range",
        "enumerate",
        "zip",
        "rank_value",
        "chip_value",
        "sorted",
        "list",
        "tuple",
        "int",
        "float",
        "str",
        "bool",
        "dict",
        "isinstance",
        "all",
        "any",
    }
)
FORBIDDEN_NAMES = frozenset(
    {
        "__import__",
        "eval",
        "exec",
        "open",
        "compile",
        "input",
        "print",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "random",
    }
)


@dataclass
class EffectCtx:
    mult: float = 0.0
    chips: float = 0.0
    x_mult: float = 1.0
    dollars: float = 0.0
    retrigger_count: int = 0


@dataclass
class GameView:
    """Read-only snapshot for effect(); mutations here do NOT affect the real game."""

    money: int = 0
    discards_left: int = 0
    hands_left: int = 0
    ante: int = 1
    joker_count: int = 0


class JokerBag:
    def __init__(self, store: dict[str, Any]):
        self._store = store

    @property
    def state(self) -> dict[str, Any]:
        if "state" not in self._store:
            self._store["state"] = {}
        st = self._store["state"]
        if not isinstance(st, dict):
            self._store["state"] = {}
            return self._store["state"]
        return st


class EffectSandboxError(Exception):
    pass


ALLOWED_FUNCS = frozenset({"effect", "on_discard"})


def ast_validate(code: str) -> list[str]:
    errs: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [f"syntax: {e}"]
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            errs.append("forbidden: import")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            errs.append(f"forbidden dunder attr: {node.attr}")
        elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            errs.append(f"forbidden name: {node.id}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in FORBIDDEN_NAMES:
                errs.append(f"forbidden call: {node.func.id}")
            elif node.func.id not in ALLOWED_CALLS:
                errs.append(f"forbidden call: {node.func.id}")
        elif isinstance(node, ast.FunctionDef) and node.name not in ALLOWED_FUNCS:
            errs.append(f"only def effect / on_discard allowed, got {node.name}")
    if not any(isinstance(n, ast.FunctionDef) and n.name == "effect" for n in tree.body):
        errs.append("missing def effect(...)")
    return errs


def _sandbox_globals() -> dict[str, Any]:
    glb: dict[str, Any] = {
        "__builtins__": {
            "len": len,
            "set": set,
            "sum": sum,
            "min": min,
            "max": max,
            "abs": abs,
            "range": range,
            "enumerate": enumerate,
            "zip": zip,
            "sorted": sorted,
            "list": list,
            "tuple": tuple,
            "int": int,
            "float": float,
            "str": str,
            "bool": bool,
            "dict": dict,
            "isinstance": isinstance,
            "all": all,
            "any": any,
            "True": True,
            "False": False,
            "None": None,
        }
    }

    def rank_value(card: Card) -> int:
        return int(RANK_VALUE.get(card.rank, 0))

    def chip_value(card: Card) -> int:
        return int(CHIP_BY_RANK.get(card.rank, 0))

    glb["rank_value"] = rank_value
    glb["chip_value"] = chip_value
    return glb


def compile_effects(code: str) -> tuple[Callable, Callable | None]:
    """Compile effect() and optional on_discard()."""
    errs = ast_validate(code)
    if errs:
        raise EffectSandboxError("; ".join(errs))
    glb = _sandbox_globals()
    loc: dict[str, Any] = {}
    exec(compile(code, "<effect>", "exec"), glb, loc)  # noqa: S102
    fn = loc.get("effect") or glb.get("effect")
    if not callable(fn):
        raise EffectSandboxError("effect not defined")
    od = loc.get("on_discard") or glb.get("on_discard")
    return fn, od if callable(od) else None


def compile_effect(code: str) -> Callable:
    """Back-compat: return only effect()."""
    fn, _ = compile_effects(code)
    return fn


def ctx_to_mods(ctx: EffectCtx, source: str | None) -> list[dict[str, Any]]:
    mods: list[dict[str, Any]] = []
    if ctx.mult:
        mods.append({"add_mult": float(ctx.mult), "source": source})
    if ctx.chips:
        mods.append({"add_chips": float(ctx.chips), "source": source})
    if abs(float(ctx.x_mult) - 1.0) > 1e-9:
        mods.append({"x_mult": float(ctx.x_mult), "source": source})
    if ctx.dollars:
        mods.append({"dollars": float(ctx.dollars), "source": source})
    if int(ctx.retrigger_count) > 0:
        mods.append(
            {
                "retrigger_count": int(ctx.retrigger_count),
                # legacy alias for older readers / Lua export paths
                "retrigger_factor": 1.0 + float(ctx.retrigger_count),
                "source": source,
            }
        )
    return mods


def _game_view_from_joker(j: dict[str, Any]) -> GameView:
    return GameView(
        money=int(j.get("dollars_ctx", 0) or 0),
        discards_left=int(j.get("discards_left_ctx", 0) or 0),
        hands_left=int(j.get("hands_left_ctx", 0) or 0),
        ante=int(j.get("ante_ctx", 1) or 1),
        joker_count=int(j.get("n_jokers_ctx", 1) or 1),
    )


def run_effect_on_joker(
    j: dict[str, Any],
    hand_type: str,
    played: list[Card],
    held: list[Card],
) -> list[dict[str, Any]]:
    """Execute attached effect_fn; return score mods."""
    fn = j.get("effect_fn")
    if not callable(fn):
        return []
    from cardgen.engine.cards import classify_hand

    _, scored = classify_hand(played)
    ctx = EffectCtx()
    game = _game_view_from_joker(j)
    bag = JokerBag(j)
    try:
        fn(ctx, hand_type, list(scored), list(played), list(held), game, bag)
    except Exception:
        return []
    return ctx_to_mods(ctx, j.get("key"))


def run_on_discard_on_joker(
    j: dict[str, Any],
    discarded: list[Card],
    held: list[Card],
) -> dict[str, float]:
    """Execute on_discard_fn if present; else bump state['discarded'].

    Returns dollars (immediate) and temp_mult_bonus (applied next scored hand).
    """
    fn = j.get("on_discard_fn")
    if not callable(fn):
        st = j.setdefault("state", {})
        if not isinstance(st, dict):
            j["state"] = {}
            st = j["state"]
        st["discarded"] = int(st.get("discarded", 0) or 0) + len(discarded)
        return {"dollars": 0.0, "temp_mult_bonus": 0.0}

    ctx = EffectCtx()
    game = _game_view_from_joker(j)
    bag = JokerBag(j)
    try:
        fn(ctx, list(discarded), list(held), game, bag)
    except Exception:
        return {"dollars": 0.0, "temp_mult_bonus": 0.0}
    # Discard-time: dollars cash now; +mult becomes next-hand temp bonus
    return {
        "dollars": float(ctx.dollars or 0),
        "temp_mult_bonus": float(ctx.mult or 0),
    }


def attach_effect_fn(joker: dict[str, Any], code: str) -> dict[str, Any]:
    j = dict(joker)
    effect_fn, on_discard_fn = compile_effects(code)
    j["effect_fn"] = effect_fn
    if on_discard_fn is not None:
        j["on_discard_fn"] = on_discard_fn
    j.setdefault("state", {})
    return j
