# -*- coding: utf-8 -*-
"""JSON whitelist effect interpreter + expanded builtin joker pool."""
from __future__ import annotations

from typing import Any

from cardgen.engine.cards import Card

WHITELIST_TEMPLATES = (
    "flat_mult",
    "flat_chips",
    "x_mult",
    "flat_mult_if_hand",
    "flat_chips_if_hand",
    "x_mult_if_hand",
    "retrigger_scored",
    "earn_dollars",
    "earn_dollars_if_hand",
    "bonus_interest",
    # decision-space templates
    "bonus_if_last_hand",
    "earn_on_discard",
    "xmult_with_penalty",
    "mult_per_unique_type",
    "held_card_bonus",
    # batch-1: expose common vanilla scoring axes
    "scored_card_suit_bonus",
    "scored_card_rank_bonus",
    "bonus_scaled_by_money",
    "bonus_scaled_by_discards",
    "bonus_if_n_played",
    # branch rewards: different hand types → different bonuses
    "branched_hand_bonus",
)

CARD_FILTERS = ("face", "even", "odd", "any")

# MiniBalatro ranks: 2-10, J, Q, K, A (not Jack/Queen/…)
RANK_CLASSES: dict[str, frozenset[str]] = {
    "face": frozenset({"J", "Q", "K"}),
    "even": frozenset({"2", "4", "6", "8", "10"}),
    "odd": frozenset({"A", "3", "5", "7", "9"}),
    "fibonacci": frozenset({"A", "2", "3", "5", "8"}),
    "ace": frozenset({"A"}),
    "number": frozenset({"2", "3", "4", "5", "6", "7", "8", "9", "10"}),
}

SUITS = ("Hearts", "Diamonds", "Spades", "Clubs")


def _matches_card_filter(card: Card, filt: str) -> bool:
    f = (filt or "any").lower()
    if f == "any":
        return True
    if f == "face":
        return card.rank in ("J", "Q", "K")
    if f == "even":
        return card.rank in ("2", "4", "6", "8", "10")
    if f == "odd":
        return card.rank in ("A", "3", "5", "7", "9")
    return False


def _scoring_cards(played: list[Card]) -> list[Card]:
    """Cards that actually score (Balatro scoring_hand), not full played set."""
    from cardgen.engine.cards import classify_hand

    _, scoring = classify_hand(played)
    return list(scoring)


def apply_joker_effects(
    jokers: list[dict[str, Any]],
    hand_type: str,
    played: list[Card],
    held: list[Card] | None = None,
) -> list[dict[str, Any]]:
    """Return list of score / dollar modification dicts for score_hand."""
    held = held or []
    mods: list[dict[str, Any]] = []
    for j in jokers:
        impl = j.get("implementation") or {}
        template = impl.get("template")
        values = impl.get("values") or {}
        condition = impl.get("condition") or {}
        hand_ok = True
        if template and (
            template.endswith("_if_hand") or template == "earn_dollars_if_hand"
        ):
            allowed = set(condition.get("hand_types") or [])
            hand_ok = hand_type in allowed

        if template == "flat_mult":
            mods.append({"add_mult": float(values.get("mult", 0)), "source": j.get("key")})
        elif template == "flat_chips":
            mods.append({"add_chips": float(values.get("chips", 0)), "source": j.get("key")})
        elif template == "x_mult":
            mods.append({"x_mult": float(values.get("x_mult", 1.0)), "source": j.get("key")})
        elif template == "flat_mult_if_hand":
            if hand_ok:
                if "mult" in values:
                    mods.append({"add_mult": float(values.get("mult", 0)), "active": True, "source": j.get("key")})
                if "chips" in values:
                    mods.append({"add_chips": float(values.get("chips", 0)), "active": True, "source": j.get("key")})
                if "x_mult" in values:
                    mods.append({"x_mult": float(values.get("x_mult", 1.0)), "active": True, "source": j.get("key")})
                if "dollars" in values:
                    mods.append({"dollars": float(values.get("dollars", 0)), "active": True, "source": j.get("key")})
                if not any(k in values for k in ("mult", "chips", "x_mult", "dollars")):
                    mods.append({"add_mult": 0.0, "active": True, "source": j.get("key")})
        elif template == "flat_chips_if_hand":
            if hand_ok:
                if "chips" in values:
                    mods.append({"add_chips": float(values.get("chips", 0)), "active": True, "source": j.get("key")})
                if "mult" in values:
                    mods.append({"add_mult": float(values.get("mult", 0)), "active": True, "source": j.get("key")})
                if "x_mult" in values:
                    mods.append({"x_mult": float(values.get("x_mult", 1.0)), "active": True, "source": j.get("key")})
                if not any(k in values for k in ("chips", "mult", "x_mult")):
                    mods.append({"add_chips": 0.0, "active": True, "source": j.get("key")})
        elif template == "x_mult_if_hand":
            if hand_ok:
                if "x_mult" in values:
                    mods.append({"x_mult": float(values.get("x_mult", 1.0)), "active": True, "source": j.get("key")})
                if "mult" in values:
                    mods.append({"add_mult": float(values.get("mult", 0)), "active": True, "source": j.get("key")})
                if "chips" in values:
                    mods.append({"add_chips": float(values.get("chips", 0)), "active": True, "source": j.get("key")})
                if not any(k in values for k in ("x_mult", "mult", "chips")):
                    mods.append({"x_mult": 1.0, "active": True, "source": j.get("key")})
        elif template == "retrigger_scored":
            n = int(values.get("retrigger_count", 1))
            mods.append({
                "retrigger_count": n,
                "retrigger_factor": 1.0 + n,
                "active": hand_ok if condition.get("hand_types") else True,
                "source": j.get("key"),
            })
        elif template == "earn_dollars":
            mods.append({"dollars": float(values.get("dollars", 0)), "source": j.get("key")})
        elif template == "earn_dollars_if_hand":
            mods.append({
                "dollars": float(values.get("dollars", 0)),
                "active": hand_ok,
                "source": j.get("key"),
            })
        elif template == "bonus_interest":
            # handled in shop/interest via joker flag; no per-hand mod
            pass
        elif template == "bonus_if_last_hand":
            # hands_left_ctx == 0 means this play is the last hand of the blind.
            # Optional condition.hand_types: empty = any hand type on last hand.
            if int(j.get("hands_left_ctx", 1)) == 0:
                allowed = set(condition.get("hand_types") or [])
                if allowed and hand_type not in allowed:
                    pass
                else:
                    if values.get("mult"):
                        mods.append({"add_mult": float(values["mult"]), "source": j.get("key")})
                    if values.get("chips"):
                        mods.append({"add_chips": float(values["chips"]), "source": j.get("key")})
                    if values.get("x_mult"):
                        mods.append({"x_mult": float(values["x_mult"]), "source": j.get("key")})
                    if values.get("dollars"):
                        mods.append({"dollars": float(values["dollars"]), "source": j.get("key")})
        elif template == "earn_on_discard":
            # discard-time only; see apply_discard_effects
            pass
        elif template == "xmult_with_penalty":
            xm = float(values.get("x_mult", 1.0))
            if xm > 1.0:
                mods.append({"x_mult": xm, "source": j.get("key")})
        elif template == "mult_per_unique_type":
            used = set(j.get("round_hand_types_ctx") or [])
            used.add(hand_type)
            n_unique = len(used)
            per = float(values.get("mult_per_type", values.get("mult", 0)))
            if per and n_unique:
                mods.append({"add_mult": per * n_unique, "source": j.get("key")})
        elif template == "held_card_bonus":
            filt = str(values.get("card_filter", "any"))
            matching = [c for c in held if _matches_card_filter(c, filt)]
            xm = float(values.get("x_mult", 1.0))
            if matching and xm > 1.0:
                mods.append({"x_mult": xm ** len(matching), "source": j.get("key")})
            add_m = float(values.get("mult", 0))
            if matching and add_m:
                mods.append({"add_mult": add_m * len(matching), "source": j.get("key")})
        elif template == "scored_card_suit_bonus":
            suit = str(values.get("suit") or "")
            mult_per = float(values.get("mult_per_card") or 0)
            chips_per = float(values.get("chips_per_card") or 0)
            n = sum(1 for c in _scoring_cards(played) if c.suit == suit)
            if n and mult_per:
                mods.append({"add_mult": mult_per * n, "source": j.get("key")})
            if n and chips_per:
                mods.append({"add_chips": chips_per * n, "source": j.get("key")})
        elif template == "scored_card_rank_bonus":
            rc = str(values.get("rank_class") or "")
            allowed = RANK_CLASSES.get(rc, frozenset())
            mult_per = float(values.get("mult_per_card") or 0)
            chips_per = float(values.get("chips_per_card") or 0)
            n = sum(1 for c in _scoring_cards(played) if c.rank in allowed)
            if n and mult_per:
                mods.append({"add_mult": mult_per * n, "source": j.get("key")})
            if n and chips_per:
                mods.append({"add_chips": chips_per * n, "source": j.get("key")})
        elif template == "bonus_scaled_by_money":
            per = max(1, int(values.get("per_dollars") or 1))
            amount = float(values.get("bonus_amount") or 0)
            bonus_type = str(values.get("bonus_type") or "mult")
            cap = int(values.get("cap") or 0)
            money = int(j.get("dollars_ctx", 0))
            total = (money // per) * amount
            if cap > 0:
                total = min(total, float(cap))
            if total > 0:
                if bonus_type == "chips":
                    mods.append({"add_chips": total, "source": j.get("key")})
                else:
                    mods.append({"add_mult": total, "source": j.get("key")})
        elif template == "bonus_scaled_by_discards":
            mode = str(values.get("mode") or "per_discard")
            mult_val = float(values.get("mult") or 0)
            chips_val = float(values.get("chips") or 0)
            dleft = int(j.get("discards_left_ctx", 0))
            if mode == "at_zero":
                if dleft == 0:
                    if mult_val:
                        mods.append({"add_mult": mult_val, "source": j.get("key")})
                    if chips_val:
                        mods.append({"add_chips": chips_val, "source": j.get("key")})
            else:  # per_discard
                if dleft > 0:
                    if mult_val:
                        mods.append({"add_mult": mult_val * dleft, "source": j.get("key")})
                    if chips_val:
                        mods.append({"add_chips": chips_val * dleft, "source": j.get("key")})
        elif template == "bonus_if_n_played":
            # Half Joker uses full played count (#full_hand), not scoring-only
            n_played = len(played)
            comp = str(values.get("comparator") or "le")
            n = int(values.get("n") or 0)
            triggered = (
                (comp == "le" and n_played <= n)
                or (comp == "ge" and n_played >= n)
                or (comp == "eq" and n_played == n)
            )
            if triggered:
                if float(values.get("mult") or 0):
                    mods.append({"add_mult": float(values["mult"]), "source": j.get("key")})
                if float(values.get("chips") or 0):
                    mods.append({"add_chips": float(values["chips"]), "source": j.get("key")})
                xm = float(values.get("x_mult") or 1.0)
                if xm > 1.0:
                    mods.append({"x_mult": xm, "source": j.get("key")})
        elif template == "branched_hand_bonus":
            # First matching hand_type branch wins (order = priority).
            for branch in values.get("branches") or []:
                if not isinstance(branch, dict):
                    continue
                if str(branch.get("hand_type") or "") != hand_type:
                    continue
                if float(branch.get("mult") or 0):
                    mods.append({"add_mult": float(branch["mult"]), "source": j.get("key")})
                if float(branch.get("chips") or 0):
                    mods.append({"add_chips": float(branch["chips"]), "source": j.get("key")})
                xm = float(branch.get("x_mult") or 1.0)
                if xm > 1.0:
                    mods.append({"x_mult": xm, "source": j.get("key")})
                if float(branch.get("dollars") or 0):
                    mods.append({"dollars": float(branch["dollars"]), "source": j.get("key")})
                break
        elif template == "python_effect" or callable(j.get("effect_fn")):
            from cardgen.effects.effect_runtime import run_effect_on_joker

            mods.extend(run_effect_on_joker(j, hand_type, played, held))
        elif j.get("builtin"):
            mods.extend(_builtin_mods(j, hand_type, played))

    # discard→next-hand temp mult (game puts same ctx on every enriched joker)
    for j in jokers:
        temp = float(j.get("temp_mult_bonus_ctx", 0) or 0)
        if temp:
            mods.append({"add_mult": temp, "source": "temp_mult_bonus"})
            break
    return mods


def apply_discard_effects(
    jokers: list[dict[str, Any]],
    discarded: list[Card],
    held: list[Card] | None = None,
    *,
    money: int = 0,
    discards_left: int = 0,
    hands_left: int = 0,
    ante: int = 1,
) -> dict[str, float]:
    """Discard-time hooks. Returns {dollars, temp_mult_bonus} aggregates."""
    dollars = 0.0
    temp_mult = 0.0
    n = len(discarded)
    if n <= 0:
        return {"dollars": 0.0, "temp_mult_bonus": 0.0}
    held_cards = list(held or [])
    for j in jokers:
        impl = j.get("implementation") or {}
        tmpl = impl.get("template")
        if tmpl == "python_effect" or callable(j.get("effect_fn")) or callable(
            j.get("on_discard_fn")
        ):
            from cardgen.effects.effect_runtime import run_on_discard_on_joker

            # Refresh snapshot fields for discard-time GameView
            j["dollars_ctx"] = money
            j["discards_left_ctx"] = discards_left
            j["hands_left_ctx"] = hands_left
            j["ante_ctx"] = ante
            j["n_jokers_ctx"] = len(jokers)
            d = run_on_discard_on_joker(j, discarded, held_cards)
            dollars += float(d.get("dollars", 0) or 0)
            temp_mult += float(d.get("temp_mult_bonus", 0) or 0)
            continue
        if tmpl != "earn_on_discard":
            continue
        values = impl.get("values") or {}
        dollars += float(values.get("dollars", 0)) * n
        temp_mult += float(values.get("mult", 0)) * n
    return {"dollars": dollars, "temp_mult_bonus": temp_mult}


def apply_round_start_penalties(
    jokers: list[dict[str, Any]],
) -> dict[str, int]:
    """Blind/round start: aggregate penalties from xmult_with_penalty."""
    out = {"penalty_hands": 0, "penalty_discards": 0, "penalty_dollars": 0}
    for j in jokers:
        impl = j.get("implementation") or {}
        if impl.get("template") != "xmult_with_penalty":
            continue
        values = impl.get("values") or {}
        out["penalty_hands"] += int(values.get("penalty_hands", 0) or 0)
        out["penalty_discards"] += int(values.get("penalty_discards", 0) or 0)
        out["penalty_dollars"] += int(values.get("penalty_dollars", 0) or 0)
    return out


def jokers_have_template(jokers: list[dict[str, Any]], template: str) -> bool:
    return any((j.get("implementation") or {}).get("template") == template for j in jokers)


def interest_bonus_from_jokers(jokers: list[dict[str, Any]]) -> int:
    """Extra interest dollars from bonus_interest templates / builtins."""
    bonus = 0
    for j in jokers:
        impl = j.get("implementation") or {}
        if impl.get("template") == "bonus_interest":
            bonus += int((impl.get("values") or {}).get("dollars", 1))
        if j.get("builtin") == "j_to_the_moon":
            bonus += 1
        if j.get("builtin") == "j_rocket":
            bonus += 2
    return bonus


def _builtin_mods(j: dict[str, Any], hand_type: str, played: list[Card]) -> list[dict[str, Any]]:
    b = j.get("builtin")
    mods: list[dict[str, Any]] = []
    if b == "j_joker":
        mods.append({"add_mult": 4.0, "source": b})
    elif b == "j_greedy_joker":
        n = sum(1 for c in played if c.suit == "Diamonds")
        if n:
            mods.append({"add_mult": 3.0 * n, "source": b})
    elif b == "j_lusty_joker":
        n = sum(1 for c in played if c.suit == "Hearts")
        if n:
            mods.append({"add_mult": 3.0 * n, "source": b})
    elif b == "j_wrathful_joker":
        n = sum(1 for c in played if c.suit == "Spades")
        if n:
            mods.append({"add_mult": 3.0 * n, "source": b})
    elif b == "j_gluttonous_joker":
        n = sum(1 for c in played if c.suit == "Clubs")
        if n:
            mods.append({"add_mult": 3.0 * n, "source": b})
    elif b == "j_jolly":
        if hand_type in ("Pair", "Two Pair", "Three of a Kind", "Full House", "Four of a Kind"):
            mods.append({"add_mult": 8.0, "source": b})
    elif b == "j_zany":
        if hand_type in ("Three of a Kind", "Full House", "Four of a Kind"):
            mods.append({"add_mult": 12.0, "source": b})
    elif b == "j_mad":
        if hand_type == "Two Pair":
            mods.append({"add_mult": 10.0, "source": b})
    elif b == "j_crazy":
        if hand_type in ("Straight", "Straight Flush"):
            mods.append({"add_mult": 12.0, "source": b})
    elif b == "j_droll":
        if hand_type in ("Flush", "Straight Flush"):
            mods.append({"add_mult": 10.0, "source": b})
    elif b == "j_sly":
        if hand_type in ("Pair", "Two Pair", "Three of a Kind", "Full House", "Four of a Kind"):
            mods.append({"add_chips": 50.0, "source": b})
    elif b == "j_wily":
        if hand_type in ("Three of a Kind", "Full House", "Four of a Kind"):
            mods.append({"add_chips": 100.0, "source": b})
    elif b == "j_clever":
        if hand_type == "Two Pair":
            mods.append({"add_chips": 80.0, "source": b})
    elif b == "j_devious":
        if hand_type in ("Straight", "Straight Flush"):
            mods.append({"add_chips": 100.0, "source": b})
    elif b == "j_crafty":
        if hand_type in ("Flush", "Straight Flush"):
            mods.append({"add_chips": 80.0, "source": b})
    elif b == "j_half":
        if len(played) <= 3:
            mods.append({"add_mult": 20.0, "source": b})
    elif b == "j_stencil":
        empty = max(0, 5 - int(j.get("n_jokers_ctx", 1)))
        if empty:
            mods.append({"x_mult": float(empty), "source": b})
    elif b == "j_four_fingers":
        # simplified: treat as small flush/straight assist via +mult if 4 cards flush-ish
        if len(played) >= 4:
            suits = [c.suit for c in played]
            if max(suits.count(s) for s in set(suits)) >= 4:
                mods.append({"add_mult": 8.0, "source": b})
    elif b == "j_mime":
        # held steel already applies; mime approx: extra steel pass via x1.5 if any steel held ctx
        pass
    elif b == "j_credit_card":
        mods.append({"dollars": 1.0, "source": b})
    elif b == "j_banner":
        dleft = int(j.get("discards_left_ctx", 0))
        mods.append({"add_chips": 30.0 * dleft, "source": b})
    elif b == "j_mystic_summit":
        dleft = int(j.get("discards_left_ctx", 0))
        if dleft == 0:
            mods.append({"add_mult": 15.0, "source": b})
    elif b == "j_marble":
        mods.append({"add_chips": 25.0, "source": b})
    elif b == "j_loyalty_card":
        # every 6th hand approx: use play count ctx
        plays = int(j.get("plays_ctx", 0))
        if plays > 0 and plays % 6 == 0:
            mods.append({"x_mult": 4.0, "source": b})
    elif b == "j_8_ball":
        if any(c.rank == "8" for c in played):
            mods.append({"add_mult": 8.0, "source": b})
    elif b == "j_misprint":
        mods.append({"add_mult": float(j.get("misprint_mult", 8)), "source": b})
    elif b == "j_dusk":
        hands_left = int(j.get("hands_left_ctx", 1))
        if hands_left == 0:
            mods.append({"retrigger_factor": 2.0, "source": b})
    elif b == "j_raise_fist":
        if played:
            from cardgen.engine.cards import CHIP_BY_RANK, RANK_VALUE
            low = min(
                played,
                key=lambda c: 14 if c.rank == "A" else RANK_VALUE[c.rank],
            )
            mods.append({"add_mult": float(CHIP_BY_RANK[low.rank]), "source": b})
    elif b == "j_fibonacci":
        fib = {"A", "2", "3", "5", "8"}
        n = sum(1 for c in played if c.rank in fib)
        if n:
            mods.append({"add_mult": 8.0 * n, "source": b})
    elif b == "j_steel_joker":
        # +0.2 x per steel in full deck — approximate from ctx
        n_steel = int(j.get("n_steel_ctx", 0))
        if n_steel:
            mods.append({"x_mult": 1.0 + 0.2 * n_steel, "source": b})
    elif b == "j_scary_face":
        faces = sum(1 for c in played if c.rank in ("J", "Q", "K"))
        if faces:
            mods.append({"add_chips": 30.0 * faces, "source": b})
    elif b == "j_abstract":
        n = int(j.get("n_jokers_ctx", 1))
        mods.append({"add_mult": 3.0 * n, "source": b})
    elif b == "j_delayed_grat":
        # end-round money if no discards — handled separately
        pass
    elif b == "j_even_steven":
        n = sum(1 for c in played if c.rank in ("2", "4", "6", "8", "10"))
        if n:
            mods.append({"add_mult": 4.0 * n, "source": b})
    elif b == "j_odd_todd":
        n = sum(1 for c in played if c.rank in ("A", "3", "5", "7", "9"))
        if n:
            mods.append({"add_chips": 31.0 * n, "source": b})
    elif b == "j_scholar":
        n = sum(1 for c in played if c.rank == "A")
        if n:
            mods.append({"add_chips": 20.0 * n, "add_mult": 4.0 * n, "source": b})
    elif b == "j_business":
        faces = sum(1 for c in played if c.rank in ("J", "Q", "K"))
        if faces:
            mods.append({"dollars": float(faces), "source": b})  # simplify always pays
    elif b == "j_supernova":
        # +mult = times this hand type played — use level as proxy
        lv = int(j.get("hand_level_ctx", 1))
        mods.append({"add_mult": float(lv), "source": b})
    elif b == "j_ride_the_bus":
        streak = int(j.get("bus_streak", 0))
        mods.append({"add_mult": float(streak), "source": b})
    elif b == "j_space":
        # chance to upgrade — handled in game after play
        pass
    elif b == "j_egg":
        mods.append({"dollars": 3.0, "source": b})  # sell value proxy as small earn
    elif b == "j_runner":
        if hand_type in ("Straight", "Straight Flush"):
            # cumulative chips — use ante as proxy growth
            ante = int(j.get("ante_ctx", 1))
            mods.append({"add_chips": 15.0 + 10.0 * ante, "source": b})
    elif b == "j_ice_cream":
        chips = float(j.get("ice_chips", 100))
        if chips > 0:
            mods.append({"add_chips": chips, "source": b})
    elif b == "j_dna":
        if len(played) == 1:
            mods.append({"add_chips": 40.0, "add_mult": 4.0, "source": b})
    elif b == "j_blue_joker":
        rem = int(j.get("deck_left_ctx", 0))
        mods.append({"add_chips": 2.0 * rem, "source": b})
    elif b == "j_sixth_sense":
        if any(c.rank == "6" for c in played) and hand_type == "Three of a Kind":
            mods.append({"add_mult": 16.0, "source": b})
    elif b == "j_constellation":
        planet_buys = int(j.get("planet_buys_ctx", 0))
        if planet_buys:
            mods.append({"x_mult": 1.0 + 0.1 * planet_buys, "source": b})
    elif b == "j_hiker":
        mods.append({"add_chips": 5.0 * len(played), "source": b})
    elif b == "j_faceless":
        faces = sum(1 for c in played if c.rank in ("J", "Q", "K"))
        if faces >= 3:
            mods.append({"dollars": 5.0, "source": b})
    elif b == "j_green_joker":
        gm = int(j.get("green_mult", 0))
        mods.append({"add_mult": float(gm), "source": b})
    elif b == "j_superposition":
        if hand_type in ("Straight", "Straight Flush") and any(c.rank == "A" for c in played):
            mods.append({"add_mult": 20.0, "source": b})
        # also would create tarot — skip
    elif b == "j_to_the_moon":
        pass  # interest
    elif b == "j_rocket":
        pass
    elif b == "j_cavendish":
        mods.append({"x_mult": 3.0, "source": b})
    elif b == "j_photograph":
        if any(c.rank in ("J", "Q", "K") for c in played):
            mods.append({"x_mult": 2.0, "source": b})
    elif b == "j_hanging_chad":
        mods.append({"retrigger_factor": 2.0, "source": b})  # first card twice approx
    elif b == "j_flower_pot":
        suits = {c.suit for c in played}
        if len(suits) >= 4:
            mods.append({"x_mult": 3.0, "source": b})
    elif b == "j_seeing_double":
        if len({c.suit for c in played}) >= 2 and any(c.suit == "Clubs" for c in played):
            mods.append({"x_mult": 2.0, "source": b})
    elif b == "j_smiley":
        faces = sum(1 for c in played if c.rank in ("J", "Q", "K"))
        if faces:
            mods.append({"add_mult": 5.0 * faces, "source": b})
    elif b == "j_sock_and_buskin":
        if any(c.rank in ("J", "Q", "K") for c in played):
            mods.append({"retrigger_factor": 2.0, "source": b})
    elif b == "j_swashbuckler":
        # +mult = sell value of owned — approximate 2 per joker
        n = int(j.get("n_jokers_ctx", 1))
        mods.append({"add_mult": 2.0 * n, "source": b})
    elif b == "j_fortune_teller":
        mods.append({"add_mult": float(j.get("fortune_mult", 5)), "source": b})
    elif b == "j_juggler":
        pass  # hand size — not modeled
    elif b == "j_drunkard":
        pass  # discards — not modeled as score
    elif b == "j_acrobat":
        hands_left = int(j.get("hands_left_ctx", 1))
        if hands_left == 0:
            mods.append({"x_mult": 3.0, "source": b})
    elif b == "j_bootstraps":
        dollars = int(j.get("dollars_ctx", 0))
        mods.append({"add_mult": 2.0 * (dollars // 5), "source": b})
    return mods


def _bj(key: str, name: str, rarity: str, cost: int, builtin: str, effect_type: str) -> dict[str, Any]:
    return {
        "key": key,
        "name": name,
        "rarity": rarity,
        "cost": cost,
        "builtin": builtin,
        "effect_type": effect_type,
    }


BUILTIN_POOL: list[dict[str, Any]] = [
    _bj("j_joker", "Joker", "Common", 2, "j_joker", "+Mult"),
    _bj("j_greedy_joker", "Greedy Joker", "Common", 5, "j_greedy_joker", "+Mult"),
    _bj("j_lusty_joker", "Lusty Joker", "Common", 5, "j_lusty_joker", "+Mult"),
    _bj("j_wrathful_joker", "Wrathful Joker", "Common", 5, "j_wrathful_joker", "+Mult"),
    _bj("j_gluttonous_joker", "Gluttonous Joker", "Common", 5, "j_gluttonous_joker", "+Mult"),
    _bj("j_jolly", "Jolly Joker", "Common", 3, "j_jolly", "+Mult"),
    _bj("j_zany", "Zany Joker", "Common", 4, "j_zany", "+Mult"),
    _bj("j_mad", "Mad Joker", "Common", 4, "j_mad", "+Mult"),
    _bj("j_crazy", "Crazy Joker", "Common", 4, "j_crazy", "+Mult"),
    _bj("j_droll", "Droll Joker", "Common", 4, "j_droll", "+Mult"),
    _bj("j_sly", "Sly Joker", "Common", 3, "j_sly", "+Chips"),
    _bj("j_wily", "Wily Joker", "Common", 4, "j_wily", "+Chips"),
    _bj("j_clever", "Clever Joker", "Common", 4, "j_clever", "+Chips"),
    _bj("j_devious", "Devious Joker", "Common", 4, "j_devious", "+Chips"),
    _bj("j_crafty", "Crafty Joker", "Common", 4, "j_crafty", "+Chips"),
    _bj("j_half", "Half Joker", "Common", 5, "j_half", "+Mult"),
    _bj("j_credit_card", "Credit Card", "Common", 1, "j_credit_card", "Economy"),
    _bj("j_banner", "Banner", "Common", 5, "j_banner", "+Chips"),
    _bj("j_mystic_summit", "Mystic Summit", "Common", 5, "j_mystic_summit", "+Mult"),
    _bj("j_8_ball", "8 Ball", "Common", 5, "j_8_ball", "+Mult"),
    _bj("j_misprint", "Misprint", "Common", 4, "j_misprint", "+Mult"),
    _bj("j_raised_fist", "Raised Fist", "Common", 5, "j_raise_fist", "+Mult"),
    _bj("j_fibonacci", "Fibonacci", "Uncommon", 8, "j_fibonacci", "+Mult"),
    _bj("j_steel_joker", "Steel Joker", "Uncommon", 7, "j_steel_joker", "xMult"),
    _bj("j_scary_face", "Scary Face", "Common", 4, "j_scary_face", "+Chips"),
    _bj("j_abstract", "Abstract Joker", "Common", 4, "j_abstract", "+Mult"),
    _bj("j_even_steven", "Even Steven", "Common", 4, "j_even_steven", "+Mult"),
    _bj("j_odd_todd", "Odd Todd", "Common", 4, "j_odd_todd", "+Chips"),
    _bj("j_scholar", "Scholar", "Common", 4, "j_scholar", "Hybrid"),
    _bj("j_business", "Business Card", "Common", 4, "j_business", "Economy"),
    _bj("j_supernova", "Supernova", "Common", 5, "j_supernova", "+Mult"),
    _bj("j_ride_the_bus", "Ride the Bus", "Common", 6, "j_ride_the_bus", "+Mult"),
    _bj("j_runner", "Runner", "Common", 5, "j_runner", "+Chips"),
    _bj("j_ice_cream", "Ice Cream", "Common", 5, "j_ice_cream", "+Chips"),
    _bj("j_dna", "DNA", "Rare", 8, "j_dna", "Special"),
    _bj("j_blue_joker", "Blue Joker", "Common", 5, "j_blue_joker", "+Chips"),
    _bj("j_constellation", "Constellation", "Uncommon", 6, "j_constellation", "xMult"),
    _bj("j_hiker", "Hiker", "Uncommon", 5, "j_hiker", "+Chips"),
    _bj("j_faceless", "Faceless Joker", "Common", 4, "j_faceless", "Economy"),
    _bj("j_green_joker", "Green Joker", "Common", 4, "j_green_joker", "+Mult"),
    _bj("j_superposition", "Superposition", "Common", 4, "j_superposition", "+Mult"),
    _bj("j_to_the_moon", "To the Moon", "Uncommon", 5, "j_to_the_moon", "Economy"),
    _bj("j_rocket", "Rocket", "Uncommon", 6, "j_rocket", "Economy"),
    _bj("j_cavendish", "Cavendish", "Common", 4, "j_cavendish", "xMult"),
    _bj("j_photograph", "Photograph", "Common", 5, "j_photograph", "xMult"),
    _bj("j_hanging_chad", "Hanging Chad", "Common", 4, "j_hanging_chad", "Retrigger"),
    _bj("j_flower_pot", "Flower Pot", "Uncommon", 6, "j_flower_pot", "xMult"),
    _bj("j_seeing_double", "Seeing Double", "Uncommon", 6, "j_seeing_double", "xMult"),
    _bj("j_smiley", "Smiley Face", "Common", 4, "j_smiley", "+Mult"),
    _bj("j_sock_and_buskin", "Sock and Buskin", "Uncommon", 6, "j_sock_and_buskin", "Retrigger"),
    _bj("j_swashbuckler", "Swashbuckler", "Common", 4, "j_swashbuckler", "+Mult"),
    _bj("j_acrobat", "Acrobat", "Uncommon", 6, "j_acrobat", "xMult"),
    _bj("j_bootstraps", "Bootstraps", "Uncommon", 7, "j_bootstraps", "+Mult"),
    _bj("j_stencil", "Joker Stencil", "Uncommon", 8, "j_stencil", "xMult"),
    _bj("j_loyalty_card", "Loyalty Card", "Uncommon", 5, "j_loyalty_card", "xMult"),
]


def load_spec_as_joker(spec: dict[str, Any]) -> dict[str, Any]:
    j = dict(spec)
    j.setdefault("key", f"j_gen_{spec.get('name', 'card').lower().replace(' ', '_')}")
    if j.get("implementation") and not j.get("builtin"):
        j["generated"] = True
    impl = j.get("implementation") or {}
    tmpl = str(impl.get("template") or "")
    values = impl.get("values") or {}
    code = values.get("effect_code") or j.get("effect_code")
    if tmpl == "python_effect" and code:
        from cardgen.effects.effect_runtime import attach_effect_fn

        j = attach_effect_fn(j, str(code))
        j.setdefault("state", {})
    return j
