# -*- coding: utf-8 -*-
"""Archetype-aware shop scoring from an optional joker matrix CSV.

If the CSV is absent, `load_matrix()` returns an empty mapping.
"""
from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
MATRIX_CSV = ROOT / "data" / "reference" / "jokers" / "joker_archetype_matrix.csv"
MATRIX_XLSX = (
    ROOT
    / "data"
    / "reference"
    / "jokers"
    / "expert_valid"
    / "V1_FPX_joker_archetype_matrix_fpx.xlsx"
)

ARCHETYPES = (
    "flush",
    "pair_family",
    "straight",
    "high_card_chip",
    "economy",
    "steel_glass",
    "retrigger",
)

ROLE_SCORE = {
    "core": 1.0,
    "enabler": 0.75,
    "support": 0.45,
    "universal": 0.35,
    "neutral": 0.0,
    "anti": -0.55,
    "": 0.0,
}

PICK_BONUS = {
    "must": 2.5,
    "high_value_conditional": 1.2,
    "high_value": 1.0,
    "normal": 0.0,
    "low": -0.4,
    "skip": -1.0,
}


@lru_cache(maxsize=1)
def load_matrix() -> dict[str, dict[str, Any]]:
    """Load joker_key -> matrix row. Prefers synced CSV; falls back to Excel."""
    rows: dict[str, dict[str, Any]] = {}
    if MATRIX_CSV.exists():
        with MATRIX_CSV.open(encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                key = (r.get("joker_key") or "").strip()
                if key:
                    rows[key] = r
        return rows
    if MATRIX_XLSX.exists():
        import pandas as pd

        df = pd.read_excel(MATRIX_XLSX, sheet_name=0)
        # Chinese expert sheet → map by column position / known aliases
        colmap = {}
        for c in df.columns:
            s = str(c)
            if "内部" in s or s == "joker_key":
                colmap["joker_key"] = c
            elif s in ARCHETYPES:
                colmap[s] = c
            elif "同花" in s and "置信" not in s:
                colmap["flush"] = c
            elif "对子" in s and "置信" not in s:
                colmap["pair_family"] = c
            elif "顺子" in s and "置信" not in s:
                colmap["straight"] = c
            elif "高牌" in s and "置信" not in s:
                colmap["high_card_chip"] = c
            elif "经济" in s and "置信" not in s:
                colmap["economy"] = c
            elif "钢" in s and "置信" not in s:
                colmap["steel_glass"] = c
            elif "重触发" in s and "置信" not in s:
                colmap["retrigger"] = c
            elif "主流派" in s or s == "primary_archetype":
                colmap["primary_archetype"] = c
        for _, rec in df.iterrows():
            key = str(rec.get(colmap.get("joker_key", "joker_key"), "")).strip()
            if not key or key == "nan":
                continue
            row = {"joker_key": key}
            for a in ARCHETYPES:
                if a in colmap:
                    row[a] = str(rec.get(colmap[a], "neutral") or "neutral")
            if "primary_archetype" in colmap:
                row["primary_archetype"] = str(
                    rec.get(colmap["primary_archetype"], "uncommitted") or "uncommitted"
                )
            rows[key] = row
    return rows


def matrix_status() -> dict[str, Any]:
    rows = load_matrix()
    return {
        "csv": str(MATRIX_CSV),
        "csv_exists": MATRIX_CSV.exists(),
        "xlsx": str(MATRIX_XLSX),
        "xlsx_exists": MATRIX_XLSX.exists(),
        "n_rows": len(rows),
        "scheme_sample": next(iter(rows.values()), {}).get("scheme_version"),
    }


def _role(row: dict[str, Any] | None, arch: str) -> str:
    if not row:
        return "neutral"
    return str(row.get(arch) or "neutral").strip().lower()


def _card_key(card: dict[str, Any]) -> str | None:
    for k in ("key", "builtin", "joker_key"):
        v = card.get(k)
        if v:
            return str(v)
    return None


def lookup(card: dict[str, Any]) -> dict[str, Any] | None:
    matrix = load_matrix()
    key = _card_key(card)
    if key and key in matrix:
        return matrix[key]
    # generated stubs sometimes use j_gen_*
    if key and key.startswith("j_gen_"):
        return None
    name = (card.get("name") or "").strip().lower()
    if name:
        for row in matrix.values():
            if str(row.get("joker_name") or "").strip().lower() == name:
                return row
    return None


def role_fit(card: dict[str, Any], archetype: str) -> float:
    """How well card fits a committed archetype (matrix role or generated targets)."""
    if not archetype or archetype in ("uncommitted", "universal"):
        return 0.15
    row = lookup(card)
    if row:
        return ROLE_SCORE.get(_role(row, archetype), 0.0)
    # Generated card: use target_archetypes as soft support
    targets = card.get("target_archetypes") or []
    if archetype in targets:
        return 0.55
    if "universal" in targets:
        return 0.3
    tmpl = (card.get("implementation") or {}).get("template")
    # crude template → arch hints
    tmpl_arch = {
        "earn_on_discard": "economy",
        "earn_dollars": "economy",
        "earn_dollars_if_hand": "economy",
        "bonus_interest": "economy",
        "retrigger_scored": "retrigger",
        "held_card_bonus": "high_card_chip",
    }.get(tmpl or "")
    if tmpl_arch == archetype:
        return 0.5
    return 0.05


def roster_commitment(jokers: list[dict[str, Any]]) -> dict[str, Any]:
    """Infer current build commitment from owned jokers via matrix roles."""
    scores = {a: 0.0 for a in ARCHETYPES}
    primaries: list[str] = []
    for j in jokers:
        row = lookup(j)
        if row:
            prim = str(row.get("primary_archetype") or "uncommitted")
            if prim in ARCHETYPES:
                primaries.append(prim)
                scores[prim] += 0.35
            for a in ARCHETYPES:
                scores[a] += ROLE_SCORE.get(_role(row, a), 0.0)
        else:
            for t in j.get("target_archetypes") or []:
                if t in scores:
                    scores[t] += 0.4
                    primaries.append(t)
    # ignore pure noise
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    top_a, top_v = ranked[0]
    second_v = ranked[1][1] if len(ranked) > 1 else 0.0
    committed = top_v >= 1.2 and (top_v - second_v) >= 0.35
    if len(jokers) < 2:
        committed = False
    return {
        "scores": scores,
        "dominant": top_a if committed else "uncommitted",
        "strength": float(top_v),
        "committed": committed,
        "primaries": primaries,
    }


def matrix_shop_bonus(card: dict[str, Any], commitment: dict[str, Any], ante: int) -> float:
    """Additive shop score from FPX matrix (buy/keep)."""
    bonus = 0.0
    row = lookup(card)
    dom = commitment.get("dominant") or "uncommitted"

    if row:
        mp = str(row.get("must_pick") or "").lower() in ("true", "1", "yes")
        if mp and ante <= 3:
            bonus += 2.0
        bonus += PICK_BONUS.get(str(row.get("pick_priority") or "normal"), 0.0)
        phase = str(row.get("phase_role") or "")
        if ante <= 2 and phase == "early_transition":
            bonus += 0.8
        elif ante >= 5 and phase == "late_core":
            bonus += 1.0
        elif 3 <= ante <= 4 and phase == "mid_flex":
            bonus += 0.4
        prim = str(row.get("primary_archetype") or "uncommitted")
        if commitment.get("committed"):
            bonus += 2.2 * role_fit(card, dom)
            if prim == dom:
                bonus += 1.0
            if _role(row, dom) == "anti":
                bonus -= 2.0
        else:
            # Uncommitted early: prefer flexible / must-pick / multi-support
            if prim in ("uncommitted", "universal"):
                bonus += 0.6
            support_n = sum(
                1 for a in ARCHETYPES if _role(row, a) in ("core", "enabler", "support")
            )
            if support_n >= 3:
                bonus += 0.5
    else:
        # generated / unknown: lean on declared targets once committed
        if commitment.get("committed"):
            bonus += 2.0 * role_fit(card, dom)
        else:
            bonus += 0.3

    return bonus


def matrix_sell_priority(card: dict[str, Any], commitment: dict[str, Any]) -> float:
    """Higher = more eager to sell."""
    dom = commitment.get("dominant") or "uncommitted"
    row = lookup(card)
    pri = 0.0
    if commitment.get("committed"):
        fit = role_fit(card, dom)
        pri += (0.6 - fit) * 3.0  # anti/neutral → sell
        if row and _role(row, dom) == "anti":
            pri += 2.5
        if row and str(row.get("primary_archetype")) not in (dom, "uncommitted", "universal"):
            # off-archetype primary while committed
            if fit < 0.3:
                pri += 1.2
    else:
        # early: sell low pick_priority junk first
        if row:
            pri -= PICK_BONUS.get(str(row.get("pick_priority") or "normal"), 0.0) * 0.5
            if str(row.get("phase_role")) == "late_core":
                pri += 0.8  # too early for late cores sometimes
    return pri
