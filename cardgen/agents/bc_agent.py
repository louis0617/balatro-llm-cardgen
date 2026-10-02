# -*- coding: utf-8 -*-
"""Behavioral cloning agent: play + shop buy/sell; discard falls back to greedy."""
from __future__ import annotations

import pickle
import random
from pathlib import Path
from typing import Any

import numpy as np

from cardgen.engine.cards import HAND_TYPES, RANK_VALUE
from cardgen.engine.game import MiniBalatro

ART = Path(__file__).resolve().parent / "bc_artifacts"

ET_CODES = {
    "+Mult": 1, "+Chips": 2, "xMult": 3, "Retrigger": 4,
    "Economy": 5, "Utility": 6, "Special": 7, "Hybrid": 8,
}
ARCH_CODES = {
    "flush": 1, "pair_family": 2, "straight": 3, "high_card_chip": 4,
    "economy": 5, "steel_glass": 6, "retrigger": 7,
    "uncommitted": 0, "universal": 8,
}


def _load_bundle(name: str):
    path = ART / name
    if not path.exists():
        return None
    with path.open("rb") as f:
        return pickle.load(f)


def _et(x: Any) -> float:
    return float(ET_CODES.get(str(x or ""), 0))


def _roster_stats(jokers: list[dict]) -> dict[str, float]:
    n_x = sum(1 for j in jokers if j.get("effect_type") == "xMult")
    n_add = sum(
        1 for j in jokers if j.get("effect_type") in ("+Mult", "+Chips", "Hybrid")
    )
    types = [j.get("effect_type") or "Other" for j in jokers]
    # crude dominant: most common effect_type bucket → uncommitted if empty
    dom = "uncommitted"
    if types:
        from collections import Counter

        dom_et = Counter(types).most_common(1)[0][0]
        dom = {
            "xMult": "retrigger",
            "+Mult": "pair_family",
            "+Chips": "high_card_chip",
            "Economy": "economy",
            "Retrigger": "retrigger",
            "Special": "flush",
            "Hybrid": "pair_family",
            "Utility": "uncommitted",
        }.get(dom_et, "uncommitted")
    ent = 0.0
    if types:
        from collections import Counter
        import math

        c = Counter(types)
        n = len(types)
        ent = -sum((v / n) * math.log(v / n + 1e-12) for v in c.values())
    return {
        "n_jokers": float(len(jokers)),
        "n_xmult": float(n_x),
        "n_additive": float(n_add),
        "dom_arch_code": float(ARCH_CODES.get(dom, 0)),
        "archetype_entropy": float(ent),
        "dominant_archetype": dom,
    }


def _arch_match(dom: str, cand_et: str) -> float:
    # map effect_type loosely to archetype affinity
    prefer = {
        "xMult": "retrigger",
        "Retrigger": "retrigger",
        "Economy": "economy",
        "+Chips": "high_card_chip",
        "+Mult": "pair_family",
        "Special": "flush",
        "Hybrid": "pair_family",
    }.get(str(cand_et), "")
    if not dom or dom == "uncommitted":
        return 0.0
    if prefer == dom:
        return 1.0
    return 0.2


class BehavioralCloningAgent:
    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)
        self.np_rng = np.random.RandomState(seed)
        self.play_bundle = _load_bundle("play_model.pkl")
        self.discard_bundle = _load_bundle("discard_model.pkl")
        self.shop_buy_bundle = _load_bundle("shop_buy_model.pkl")
        self.shop_sell_bundle = _load_bundle("shop_sell_model.pkl")

    def available(self) -> bool:
        return self.play_bundle is not None

    def shop_available(self) -> bool:
        return self.shop_buy_bundle is not None

    def __call__(self, game: MiniBalatro, phase: str, **kwargs: Any) -> dict[str, Any]:
        if phase == "shop":
            return self._shop(game, **kwargs)

        combos = game.evaluate_combos()
        if not combos:
            return {"action": "play", "card_indices": [0] if game.hand else []}

        discards_left = getattr(game, "_discards_left", 0)
        # Discard: prefer discard model; else greedy-style weak-hand discard
        if discards_left > 0 and self._want_discard(game, combos):
            best_combo = combos[0][0]
            best_ids = {id(c) for c in best_combo}
            junk = [i for i, c in enumerate(game.hand) if id(c) not in best_ids]
            junk = [i for i in junk if game.hand[i].enhancement != "steel"]
            junk.sort(
                key=lambda i: 14 if game.hand[i].rank == "A" else RANK_VALUE[game.hand[i].rank]
            )
            if junk:
                return {"action": "discard", "card_indices": junk[:2]}

        indices = self._sample_play(game, combos)
        return {"action": "play", "card_indices": indices}

    def _shop(self, game: MiniBalatro, **kwargs: Any) -> dict[str, Any]:
        offers = kwargs.get("offers") or []
        planet = kwargs.get("planet") or {}
        if self.shop_buy_bundle is None:
            from cardgen.agents.greedy import greedy_agent

            return greedy_agent(game, "shop", **kwargs)

        import pandas as pd

        roster = _roster_stats(game.jokers)
        buy_feats = self.shop_buy_bundle["features"]
        buy_model = self.shop_buy_bundle["model"]

        scored: list[tuple[float, int, dict]] = []
        for i, card in enumerate(offers):
            cost = int(card.get("cost", 99))
            # Still score offers when full — need value for sell-to-upgrade
            if game.dollars < cost and len(game.jokers) < 5:
                continue
            et = card.get("effect_type") or ""
            row = {
                "ante": float(game.ante),
                "dollars": float(game.dollars),
                "n_jokers": roster["n_jokers"],
                "n_xmult": roster["n_xmult"],
                "n_additive": roster["n_additive"],
                "dom_arch_code": roster["dom_arch_code"],
                "archetype_entropy": roster["archetype_entropy"],
                "cand_et_code": _et(et),
                "cand_arch_code": float(ARCH_CODES.get(roster["dominant_archetype"], 0)),
                "cost": float(cost),
                "cost_over_dollars": float(cost) / max(float(game.dollars), 1.0),
                "arch_match": _arch_match(roster["dominant_archetype"], str(et)),
                "slots_left": max(0.0, 5.0 - len(game.jokers)),
            }
            X = pd.DataFrame([{k: row.get(k, 0.0) for k in buy_feats}])
            p = float(buy_model.predict_proba(X)[0, 1])
            if card.get("generated") or (
                not card.get("builtin") and card.get("implementation")
            ):
                p = min(0.95, p + 0.05)
            if game.dollars >= cost or len(game.jokers) >= 5:
                scored.append((p, i, card))

        scored.sort(key=lambda x: x[0], reverse=True)

        joker_buys = int(kwargs.get("joker_buys_this_shop") or 0)
        max_buys = int(kwargs.get("max_joker_buys") or 1)
        can_buy = joker_buys < max_buys
        slots_full = len(game.jokers) >= 5

        # Sell first when full / upgrade, so next loop can buy (deck-building)
        if self.shop_sell_bundle is not None and game.jokers and scored and can_buy:
            best_p = scored[0][0]
            sell_feats = self.shop_sell_bundle["features"]
            sell_model = self.shop_sell_bundle["model"]
            if slots_full or (len(game.jokers) >= 4 and best_p >= 0.35):
                best_sell = None
                best_ps = -1.0
                for idx, owned in enumerate(list(game.jokers)):
                    et = owned.get("effect_type") or ""
                    row = {
                        "ante": float(game.ante),
                        "dollars": float(game.dollars),
                        "n_jokers": roster["n_jokers"],
                        "n_xmult": roster["n_xmult"],
                        "n_additive": roster["n_additive"],
                        "dom_arch_code": roster["dom_arch_code"],
                        "archetype_entropy": roster["archetype_entropy"],
                        "cand_et_code": _et(et),
                        "cand_arch_code": float(ARCH_CODES.get(roster["dominant_archetype"], 0)),
                        "cost": float(owned.get("cost") or 4),
                        "arch_match": _arch_match(roster["dominant_archetype"], str(et)),
                        "shop_has_offers": 1.0 if offers else 0.0,
                    }
                    X = pd.DataFrame([{k: row.get(k, 0.0) for k in sell_feats}])
                    p_sell = float(sell_model.predict_proba(X)[0, 1])
                    if p_sell > best_ps:
                        best_ps = p_sell
                        best_sell = idx
                thresh = 0.18 if slots_full else 0.28
                if best_sell is not None and (
                    best_ps >= thresh or (slots_full and best_p >= 0.25)
                ):
                    return {"action": "sell", "joker_index": best_sell}

        if scored and can_buy and not slots_full:
            p_best, i_best, _ = scored[0]
            # Take best offer if model is reasonably confident, else sample
            if p_best >= 0.22 or (game.dollars >= 8 and p_best >= 0.12):
                return {"action": "buy", "offer_index": i_best}
            for p, i, card in scored:
                if self.rng.random() < max(0.08, min(0.85, p)):
                    return {"action": "buy", "offer_index": i}

        if self.shop_sell_bundle is not None and game.jokers and len(game.jokers) >= 4:
            sell_feats = self.shop_sell_bundle["features"]
            sell_model = self.shop_sell_bundle["model"]
            for idx, owned in enumerate(list(game.jokers)):
                et = owned.get("effect_type") or ""
                row = {
                    "ante": float(game.ante),
                    "dollars": float(game.dollars),
                    "n_jokers": roster["n_jokers"],
                    "n_xmult": roster["n_xmult"],
                    "n_additive": roster["n_additive"],
                    "dom_arch_code": roster["dom_arch_code"],
                    "archetype_entropy": roster["archetype_entropy"],
                    "cand_et_code": _et(et),
                    "cand_arch_code": float(ARCH_CODES.get(roster["dominant_archetype"], 0)),
                    "cost": float(owned.get("cost") or 4),
                    "arch_match": _arch_match(roster["dominant_archetype"], str(et)),
                    "shop_has_offers": 1.0 if offers else 0.0,
                }
                X = pd.DataFrame([{k: row.get(k, 0.0) for k in sell_feats}])
                p_sell = float(sell_model.predict_proba(X)[0, 1])
                if self.rng.random() < p_sell * 0.35:
                    return {"action": "sell", "joker_index": idx}

        ht = planet.get("hand_type")
        planet_cost = int(planet.get("cost", 2))
        if ht and game.dollars >= planet_cost and self.rng.random() < 0.35:
            return {"action": "buy_planet", "hand_type": ht}

        return {"action": "skip"}

    def _want_discard(self, game: MiniBalatro, combos) -> bool:
        best_score = combos[0][1]
        target = float(getattr(game, "_blind_target", 0) or 0)
        cum = float(getattr(game, "_cum_score", 0) or 0)
        rem = max(0.0, target - cum)
        if rem > 0 and best_score >= rem * 0.7:
            return False
        # Strong greedy-style gate first (keeps runs playable)
        if rem > 0 and best_score < rem * 0.45 and getattr(game, "_discards_left", 0) > 0:
            return True
        if self.discard_bundle is not None:
            feats = self.discard_bundle["features"]
            row = {
                "ante": float(game.ante),
                "hands_left": float(getattr(game, "_hands_left", 0)),
                "discards_left": float(getattr(game, "_discards_left", 0)),
                "dollars": float(game.dollars),
                "blind_target": float(getattr(game, "_blind_target", 0) or 0),
                "best_score": float(best_score),
                "score_over_target": float(best_score) / float(getattr(game, "_blind_target", 0) or 1),
                "n_hand": float(len(game.hand)),
            }
            import pandas as pd

            X = pd.DataFrame([{k: row.get(k, 0.0) for k in feats}])
            p = float(self.discard_bundle["model"].predict_proba(X)[0, 1])
            return self.rng.random() < p * 0.5
        return False

    def _sample_play(self, game: MiniBalatro, combos) -> list[int]:
        # Restrict to near-optimal combos so BC variation stays playable
        top = combos[: min(8, len(combos))]
        best = top[0][1] or 1.0
        if self.play_bundle is None:
            combo = top[0][0]
        else:
            feats = self.play_bundle["features"]
            rows = []
            for rank_i, (combo, sc, ht) in enumerate(top):
                rows.append({
                    "combo_score": sc,
                    "score_rank": rank_i + 1,
                    "score_ratio_to_best": sc / best,
                    "combo_n_cards": len(combo),
                    "hand_type_idx": HAND_TYPES.index(ht) if ht in HAND_TYPES else 0,
                    "ante": float(game.ante),
                    "hands_left": float(getattr(game, "_hands_left", 0)),
                    "discards_left": float(getattr(game, "_discards_left", 0)),
                    "dollars": float(game.dollars),
                    "blind_target": float(getattr(game, "_blind_target", 0) or 0),
                    "n_hand": float(len(game.hand)),
                })
            import pandas as pd

            X = pd.DataFrame([{k: r.get(k, 0.0) for k in feats} for r in rows])
            logits = np.asarray(self.play_bundle["model"].predict_proba(X)[:, 1], dtype=float)
            # Blend with score rank so weak combos stay rare
            score_w = np.array([sc / best for _, sc, _ in top], dtype=float)
            logits = 0.65 * logits + 0.35 * score_w
            logits = logits - logits.max()
            ex = np.exp(logits / 0.25)
            p = ex / (ex.sum() + 1e-12)
            idx = int(self.np_rng.choice(len(top), p=p))
            combo = top[idx][0]

        id_to_i = {id(c): i for i, c in enumerate(game.hand)}
        return [id_to_i[id(c)] for c in combo if id(c) in id_to_i]


def make_bc_agent(seed: int = 0):
    agent = BehavioralCloningAgent(seed=seed)
    if not agent.available():
        from cardgen.agents.greedy import greedy_agent

        return greedy_agent
    return agent
