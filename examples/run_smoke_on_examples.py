# -*- coding: utf-8 -*-
"""Re-run AST + smoke checks on example cards (no API key required)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardgen.effects.effect_runtime import (  # noqa: E402
    EffectCtx as Ctx,
    GameView,
    JokerBag,
    ast_validate,
    compile_effects,
)
from cardgen.engine.cards import Card, classify_hand  # noqa: E402


def _C(rank: str, suit: str, enhancement: str = "none") -> Card:
    return Card(rank=rank, suit=suit, enhancement=enhancement)


def _smoke_cases():
    pair = [
        _C("A", "Hearts"),
        _C("A", "Spades"),
        _C("3", "Clubs"),
        _C("5", "Diamonds"),
        _C("9", "Hearts"),
    ]
    fh = [
        _C("K", "Hearts"),
        _C("K", "Spades"),
        _C("K", "Clubs"),
        _C("2", "Diamonds"),
        _C("2", "Hearts"),
    ]
    flush = [
        _C("2", "Hearts"),
        _C("5", "Hearts"),
        _C("7", "Hearts"),
        _C("9", "Hearts"),
        _C("J", "Hearts"),
    ]
    high = [
        _C("A", "Spades"),
        _C("K", "Hearts"),
        _C("9", "Clubs"),
        _C("5", "Diamonds"),
        _C("3", "Clubs"),
    ]
    held = [_C("Q", "Clubs"), _C("10", "Spades")]
    steel_held = [_C("Q", "Clubs", "steel"), _C("10", "Spades"), _C("4", "Diamonds")]
    glass_flush = [
        _C("2", "Hearts", "glass"),
        _C("5", "Hearts"),
        _C("7", "Hearts"),
        _C("9", "Hearts"),
        _C("J", "Hearts"),
    ]
    mixed = [
        _C("A", "Hearts", "gold"),
        _C("A", "Spades", "mult"),
        _C("3", "Clubs"),
        _C("5", "Diamonds", "bonus"),
        _C("9", "Hearts"),
    ]
    rich = GameView(money=40, discards_left=3, hands_left=1, ante=3, joker_count=4)
    poor = GameView(money=4, discards_left=0, hands_left=3, ante=1, joker_count=2)
    mid = GameView(money=20, discards_left=2, hands_left=2, ante=2, joker_count=3)
    return [
        ("Pair@rich", pair, held, rich),
        ("FullHouse@rich", fh, held, rich),
        ("Flush@poor", flush, held, poor),
        ("HighCard@poor", high, held, poor),
        ("SteelHeld@*", flush, steel_held, mid),
        ("GlassScored@*", glass_flush, held, mid),
        ("GoldMixed@*", mixed, steel_held, rich),
    ]


def run_smoke(fn):
    rows = []
    joker = JokerBag({})
    for label, played, held, game in _smoke_cases():
        ht, scored = classify_hand(played)
        ctx = Ctx()
        try:
            fn(ctx, ht, list(scored), list(played), list(held), game, joker)
            rows.append(
                {
                    "case": label,
                    "ok": True,
                    "x_mult": ctx.x_mult,
                    "mult": ctx.mult,
                    "chips": ctx.chips,
                }
            )
        except Exception as e:  # noqa: BLE001
            rows.append({"case": label, "ok": False, "error": str(e)})
    return rows


def main() -> int:
    cards_dir = ROOT / "examples" / "cards"
    paths = sorted(p for p in cards_dir.glob("card_*.json"))
    if not paths:
        print("No example cards found")
        return 1
    failed = 0
    for path in paths:
        card = json.loads(path.read_text(encoding="utf-8"))
        code = card.get("effect_code") or ""
        name = card.get("card_name")
        errs = ast_validate(code)
        if errs:
            print(f"[FAIL] {name}: AST {errs}")
            failed += 1
            continue
        fn, _od = compile_effects(code)
        smoke = run_smoke(fn)
        ok = all(r.get("ok") for r in smoke)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name} ({path.name}) smoke_cases={len(smoke)}")
        if not ok:
            failed += 1
            for r in smoke:
                if not r.get("ok"):
                    print("   ", r)
    print(f"Done. failed={failed}/{len(paths)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
