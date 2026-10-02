# -*- coding: utf-8 -*-
"""Behavioral AST constraints applied after syntax checks and before smoke tests.

Three rules. A minimum-branch rule for expand intents is not used: models
tend to add empty branches that pass the check without changing play.
"""
from __future__ import annotations

import ast
from typing import Any


def check_behavioral_constraints(code_str: str, intent_meta: dict[str, Any]) -> tuple[bool, str]:
    """
    intent_meta:
        behavioral_class: "expand" | "lock"
        archetype: flush | pair_family | straight | high_card_chip |
                   economy | steel_glass | retrigger
    """
    try:
        tree = ast.parse(code_str)
    except SyntaxError as e:
        return False, f"syntax: {e}"

    bc = intent_meta["behavioral_class"]
    arch = intent_meta["archetype"]

    # ── 规则 1：非 economy 意图，ctx.dollars / game.money 不能做主轴 ──
    if arch != "economy":
        dollar_refs = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("dollars", "money"):
                dollar_refs += 1
        if dollar_refs >= 2:
            return False, f"非 economy 意图但 dollars/money 出现 {dollar_refs} 次"

    # ── 规则 2：非 economy 意图，on_discard 不能做主效果 ──
    if arch != "economy":
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "on_discard":
                real_stmts = [
                    s
                    for s in node.body
                    if not (
                        isinstance(s, ast.Pass)
                        or (
                            isinstance(s, ast.Expr)
                            and isinstance(s.value, ast.Constant)
                        )
                    )
                ]
                if len(real_stmts) > 2:
                    return False, f"非 economy 意图但 on_discard 有 {len(real_stmts)} 条实质语句"

    # ── 规则 3：lock 类禁止负面惩罚 ──
    if bc == "lock":
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.AugAssign)
                and isinstance(node.op, ast.Sub)
                and isinstance(node.target, ast.Attribute)
                and node.target.attr in ("mult", "chips", "x_mult")
            ):
                return False, "lock 类不允许 -= mult/chips/x_mult"

    # ── 不要加规则 4（expand ≥2 if）──
    # expand 的决策质量靠 prompt 引导 + 人策审核

    return True, "OK"
