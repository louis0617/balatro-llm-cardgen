# -*- coding: utf-8 -*-
"""Greedy agent: max-score play; shop scoring uses an optional archetype matrix.

Without the matrix file, shop bonuses are neutral. Play and discard still run.

Also aware of decision-space templates on play/discard:
- held_card_bonus / bonus_if_last_hand / earn_on_discard
"""
from __future__ import annotations

from typing import Any

from cardgen.agents.archetype_shop import (
    matrix_sell_priority,
    matrix_shop_bonus,
    roster_commitment,
)
from cardgen.effects.interpreter import jokers_have_template
from cardgen.engine.cards import RANK_VALUE
from cardgen.engine.game import MiniBalatro


def _remaining_target(game: MiniBalatro) -> float:
    target = float(getattr(game, "_blind_target", 0) or 0)
    cum = float(getattr(game, "_cum_score", 0) or 0)
    if target <= 0:
        return 0.0
    return max(0.0, target - cum)


def _joker_value(
    card: dict[str, Any],
    *,
    commitment: dict[str, Any] | None = None,
    ante: int = 1,
) -> float:
    """Relative keep/buy score: base power + FPX archetype matrix fit."""
    score = {
        "xMult": 6.0,
        "+Mult": 4.0,
        "+Chips": 3.0,
        "Special": 4.5,
        "Retrigger": 5.5,
        "Hybrid": 4.5,
        "Economy": 2.5,
        "Utility": 2.0,
    }.get(card.get("effect_type"), 1.5)
    cost = int(card.get("cost", 5) or 5)
    score += (10 - cost) * 0.15
    if card.get("builtin") in (
        "j_cavendish",
        "j_photograph",
        "j_stencil",
        "j_hanging_chad",
        "j_sock_and_buskin",
        "j_steel_joker",
        "j_constellation",
        "j_acrobat",
    ):
        score += 2.5
    tmpl = (card.get("implementation") or {}).get("template")
    if tmpl in (
        "bonus_if_last_hand",
        "earn_on_discard",
        "held_card_bonus",
        "mult_per_unique_type",
        "xmult_with_penalty",
        "retrigger_scored",
    ):
        score += 1.8
    # Fair acquisition: no score bribe for generated cards (shelf is already random)
    if card.get("generated") or (
        not card.get("builtin") and card.get("implementation")
    ):
        score += 0.15
    if card.get("builtin") == "j_ice_cream":
        score -= 1.0
    if card.get("builtin") in ("j_joker", "j_credit_card"):
        score -= 0.5
    # --- FPX matrix deck-building ---
    if commitment is None:
        commitment = {"dominant": "uncommitted", "committed": False, "scores": {}}
    score += matrix_shop_bonus(card, commitment, ante=ante)
    return score


def _weakest_joker_index(
    jokers: list[dict[str, Any]],
    *,
    commitment: dict[str, Any],
    ante: int,
) -> int:
    """Sell the card with worst keep-score, boosted by matrix sell priority."""
    best_i = 0
    best_metric = float("inf")
    for i, j in enumerate(jokers):
        keep = _joker_value(j, commitment=commitment, ante=ante)
        sell_pri = matrix_sell_priority(j, commitment)
        metric = keep - sell_pri  # high sell_pri → more likely weakest
        if metric < best_metric:
            best_metric = metric
            best_i = i
    return best_i


def _shop_decision(game: MiniBalatro, **kwargs: Any) -> dict[str, Any]:
    offers = kwargs.get("offers") or []
    planet = kwargs.get("planet") or {}
    joker_buys = int(kwargs.get("joker_buys_this_shop") or 0)
    max_buys = int(kwargs.get("max_joker_buys") or 1)
    ht = planet.get("hand_type")
    planet_cost = int(planet.get("cost", 2))
    can_buy_more = joker_buys < max_buys

    commitment = roster_commitment(game.jokers)
    ante = int(game.ante)

    ranked: list[tuple[float, int, dict]] = []
    for i, card in enumerate(offers):
        cost = int(card.get("cost", 99))
        if game.dollars < cost and len(game.jokers) < 5:
            continue
        ranked.append(
            (_joker_value(card, commitment=commitment, ante=ante), i, card)
        )
    # When full, still rank offers that we cannot afford yet (sell-then-buy)
    if not ranked:
        for i, card in enumerate(offers):
            ranked.append(
                (_joker_value(card, commitment=commitment, ante=ante), i, card)
            )
    ranked.sort(key=lambda x: x[0], reverse=True)

    best_offer = ranked[0] if ranked else None
    slots_full = len(game.jokers) >= 5

    # Sell to make room / upgrade along archetype
    if game.jokers and best_offer is not None and can_buy_more:
        offer_v, offer_i, offer_card = best_offer
        cost = int(offer_card.get("cost", 5))
        weak_i = _weakest_joker_index(
            game.jokers, commitment=commitment, ante=ante
        )
        weak_v = _joker_value(
            game.jokers[weak_i], commitment=commitment, ante=ante
        )
        # Lower threshold when offer fits committed arch and owned is anti/off-arch
        margin = 1.0 if commitment.get("committed") else 1.2
        if slots_full and offer_v >= weak_v + margin:
            return {"action": "sell", "joker_index": weak_i}
        if len(game.jokers) >= 4 and offer_v >= weak_v + 1.5 and game.dollars >= cost:
            return {"action": "sell", "joker_index": weak_i}
        if not slots_full and game.dollars < cost and offer_v >= 5.0:
            gain = max(1, int(game.jokers[weak_i].get("cost", 4)) // 2)
            if game.dollars + gain >= cost and offer_v >= weak_v + 1.0:
                return {"action": "sell", "joker_index": weak_i}

    # Buy when slot available
    if best_offer is not None and can_buy_more and not slots_full:
        offer_v, offer_i, offer_card = best_offer
        cost = int(offer_card.get("cost", 5))
        # If committed, skip strong anti-arch offers even if raw power high
        if commitment.get("committed"):
            from cardgen.agents.archetype_shop import role_fit

            if role_fit(offer_card, commitment["dominant"]) < 0.0 and offer_v < 7.0:
                offer_v = -999  # force skip
        skip_tight = game.ante <= 1 and game.dollars - cost < 2 and offer_v < 4.0
        skip_weak = len(game.jokers) >= 3 and offer_v < 3.2
        if (
            offer_v > -100
            and game.dollars >= cost
            and not skip_tight
            and not skip_weak
        ):
            return {"action": "buy", "offer_index": offer_i}

    if ht and game.dollars >= planet_cost:
        lv = game.hand_levels.get(ht, 1)
        planet_value = 4.0 - 0.4 * lv
        if game._ante_hand_plays and ht == game._ante_hand_plays.most_common(1)[0][0]:
            planet_value += 1.5
        # Planet leans toward committed hand types
        if commitment.get("committed"):
            arch_hand = {
                "flush": "Flush",
                "pair_family": "Pair",
                "straight": "Straight",
                "high_card_chip": "High Card",
            }.get(commitment["dominant"])
            if arch_hand and ht == arch_hand:
                planet_value += 1.2
        if best_offer is None or planet_value >= best_offer[0] - 1.0:
            return {"action": "buy_planet", "hand_type": ht}

    return {"action": "skip"}


def greedy_agent(game: MiniBalatro, phase: str, **kwargs: Any) -> dict[str, Any]:
    if phase == "shop":
        return _shop_decision(game, **kwargs)

    combos = game.evaluate_combos()
    if not combos:
        return {"action": "play", "card_indices": [0] if game.hand else []}

    best_combo, best_score, _ = combos[0]
    best_ids = {id(c) for c in best_combo}
    discards_left = getattr(game, "_discards_left", 0)
    hands_left = getattr(game, "_hands_left", 1)
    has_earn_discard = jokers_have_template(game.jokers, "earn_on_discard")
    has_last_bonus = jokers_have_template(game.jokers, "bonus_if_last_hand")
    remaining = _remaining_target(game)

    want_discard = False
    if discards_left > 0 and len(game.hand) >= 5:
        if remaining > 0:
            if best_score >= remaining * 0.7:
                want_discard = False
            elif has_earn_discard:
                want_discard = best_score < remaining * 0.3
            else:
                want_discard = best_score < remaining * 0.5
        else:
            if has_earn_discard:
                want_discard = best_score < 80.0
            else:
                want_discard = best_score < 120.0

    if want_discard:
        junk = [i for i, c in enumerate(game.hand) if id(c) not in best_ids]
        junk = [i for i in junk if game.hand[i].enhancement != "steel"]
        if jokers_have_template(game.jokers, "held_card_bonus"):
            junk = [i for i in junk if game.hand[i].rank not in ("J", "Q", "K")] or junk
        junk.sort(
            key=lambda i: 14 if game.hand[i].rank == "A" else RANK_VALUE[game.hand[i].rank]
        )
        if junk:
            return {"action": "discard", "card_indices": junk[:2]}

    if has_last_bonus and hands_left > 1 and len(combos) > 1:
        if remaining > 0 and best_score < remaining and hands_left >= 2:
            weak_combo, weak_score, _ = combos[-1]
            if weak_score < best_score * 0.55 and len(weak_combo) <= 2:
                id_to_i = {id(c): i for i, c in enumerate(game.hand)}
                indices = [id_to_i[id(c)] for c in weak_combo if id(c) in id_to_i]
                if indices:
                    return {"action": "play", "card_indices": indices}

    id_to_i = {id(c): i for i, c in enumerate(game.hand)}
    indices = [id_to_i[id(c)] for c in best_combo if id(c) in id_to_i]
    return {"action": "play", "card_indices": indices}
