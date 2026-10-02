# -*- coding: utf-8 -*-
"""Scoring unit tests vs known Balatro level-1 bases."""
from __future__ import annotations

from cardgen.engine.cards import Card, classify_hand, score_hand
from cardgen.effects.interpreter import apply_joker_effects


def C(rank: str, suit: str) -> Card:
    return Card(rank=rank, suit=suit)


def test_pair_base():
    cards = [C("9", "Hearts"), C("9", "Clubs")]
    ht, _ = classify_hand(cards)
    assert ht == "Pair"
    br = score_hand(cards, [])
    # base 10x2 + 9+9 chips = 28 chips * 2 = 56
    assert br.hand_type == "Pair"
    assert br.chips == 28
    assert br.mult == 2
    assert br.score == 56


def test_flush_base():
    cards = [
        C("2", "Hearts"), C("5", "Hearts"), C("7", "Hearts"),
        C("9", "Hearts"), C("J", "Hearts"),
    ]
    ht, _ = classify_hand(cards)
    assert ht == "Flush"
    br = score_hand(cards, [])
    # 35 + 2+5+7+9+10 = 68 chips * 4 = 272
    assert br.chips == 68
    assert br.mult == 4
    assert br.score == 272


def test_flat_mult_joker():
    cards = [C("A", "Spades")]
    mods = apply_joker_effects(
        [{"key": "x", "implementation": {"template": "flat_mult", "values": {"mult": 4}}}],
        "High Card",
        cards,
    )
    br = score_hand(cards, mods)
    # high card 5+11=16 chips, mult 1+4=5 -> 80
    assert br.score == 80


def test_xmult():
    cards = [C("K", "Hearts"), C("K", "Clubs")]
    mods = [{"x_mult": 2.0}]
    br = score_hand(cards, mods)
    # pair 10+10+10=30 chips * 2 * 2 = 120
    assert br.chips == 30
    assert br.score == 120


def test_planet_level_pair():
    cards = [C("9", "Hearts"), C("9", "Clubs")]
    levels = {ht: 1 for ht in [
        "High Card", "Pair", "Two Pair", "Three of a Kind", "Straight",
        "Flush", "Full House", "Four of a Kind", "Straight Flush",
    ]}
    levels["Pair"] = 3  # +15 chips +1 mult per level → L3: 10+30 chips base, 2+2 mult
    br = score_hand(cards, [], levels)
    assert br.chips == 10 + 30 + 9 + 9  # 58
    assert br.mult == 4
    assert br.score == 58 * 4


def test_retrigger_rescores_card_chips_not_whole_score():
    """retrigger_count=1 re-adds scored face chips; joker +mult applied once."""
    cards = [C("9", "Hearts"), C("9", "Clubs")]
    base = score_hand(cards, [])
    assert base.score == 56  # 28 chips * 2
    # one extra pass: +9+9 chips → 46 chips * 2 = 92
    br = score_hand(cards, [{"retrigger_count": 1}])
    assert br.chips == 46
    assert br.mult == 2
    assert br.score == 92
    # legacy factor 2.0 == one extra pass
    br_f = score_hand(cards, [{"retrigger_factor": 2.0}])
    assert br_f.score == br.score
    # joker +mult not doubled by retrigger
    br_j = score_hand(cards, [{"add_mult": 4}, {"retrigger_count": 1}])
    assert br_j.mult == 6  # 2+4 once
    assert br_j.chips == 46
    assert br_j.score == 46 * 6


def test_retrigger_glass_and_steel_held():
    played = [
        Card("2", "Hearts", enhancement="glass"),
        Card("5", "Hearts"),
        Card("7", "Hearts"),
        Card("9", "Hearts"),
        Card("J", "Hearts"),
    ]
    held = [Card("A", "Spades", enhancement="steel")]
    base = score_hand(played, [], held_unplayed=held)
    # flush chips 68, mult 4, glass×2, steel×1.5
    assert abs(base.score - 68 * 4 * 2 * 1.5) < 1e-6
    rt = score_hand(played, [{"retrigger_count": 1}], held_unplayed=held)
    # extra pass: +2+5+7+9+10 chips, glass ×2 again; steel still once
    assert rt.chips == 68 + (2 + 5 + 7 + 9 + 10)
    assert abs(rt.x_mult - 2 * 2 * 1.5) < 1e-6


def test_earn_dollars():
    cards = [C("9", "Hearts"), C("9", "Clubs")]
    mods = apply_joker_effects(
        [{
            "key": "eco",
            "implementation": {
                "template": "earn_dollars_if_hand",
                "condition": {"hand_types": ["Pair"]},
                "values": {"dollars": 3},
            },
        }],
        "Pair",
        cards,
    )
    br = score_hand(cards, mods)
    assert br.dollars_earned == 3


def test_bonus_if_last_hand():
    cards = [C("A", "Spades")]
    jokers = [{
        "key": "duskish",
        "hands_left_ctx": 0,
        "implementation": {
            "template": "bonus_if_last_hand",
            "values": {"mult": 12, "chips": 50},
        },
    }]
    mods = apply_joker_effects(jokers, "High Card", cards)
    br = score_hand(cards, mods)
    # base HC: 5+11=16 chips, mult 1+12=13 → (16+50)*13 = 858
    assert br.chips == 66
    assert br.mult == 13
    assert br.score == 66 * 13

    jokers_mid = [{**jokers[0], "hands_left_ctx": 2}]
    mods_mid = apply_joker_effects(jokers_mid, "High Card", cards)
    br_mid = score_hand(cards, mods_mid)
    assert br_mid.score == 16  # no bonus mid-round


def test_bonus_if_last_hand_respects_hand_types():
    cards = [C("A", "Spades"), C("A", "Hearts")]
    base = {
        "key": "pair_dusk",
        "hands_left_ctx": 0,
        "implementation": {
            "template": "bonus_if_last_hand",
            "values": {"mult": 12, "chips": 50},
            "condition": {"hand_types": ["Pair"]},
        },
    }
    mods_ok = apply_joker_effects([base], "Pair", cards)
    assert any(m.get("add_mult") == 12 for m in mods_ok)
    assert any(m.get("add_chips") == 50 for m in mods_ok)

    mods_bad = apply_joker_effects([base], "High Card", [C("A", "Spades")])
    assert not any(m.get("add_mult") == 12 for m in mods_bad)
    assert not any(m.get("add_chips") == 50 for m in mods_bad)

    # empty hand_types → still fires on any last hand
    any_ht = {
        "key": "any_dusk",
        "hands_left_ctx": 0,
        "implementation": {
            "template": "bonus_if_last_hand",
            "values": {"mult": 5},
            "condition": {},
        },
    }
    mods_any = apply_joker_effects([any_ht], "Flush", cards)
    assert any(m.get("add_mult") == 5 for m in mods_any)

    # dollars on last hand (aligned with Lua)
    j_dollar = [{
        "key": "cash_dusk",
        "hands_left_ctx": 0,
        "implementation": {
            "template": "bonus_if_last_hand",
            "values": {"dollars": 3},
        },
    }]
    mods_d = apply_joker_effects(j_dollar, "High Card", [C("A", "Spades")])
    assert any(m.get("dollars") == 3 for m in mods_d)


def test_held_card_bonus():
    played = [C("9", "Hearts"), C("9", "Clubs")]
    held = [C("K", "Spades"), C("Q", "Hearts"), C("2", "Clubs")]
    jokers = [{
        "key": "baronish",
        "implementation": {
            "template": "held_card_bonus",
            "values": {"x_mult": 1.5, "card_filter": "face"},
        },
    }]
    mods = apply_joker_effects(jokers, "Pair", played, held=held)
    br = score_hand(played, mods, held_unplayed=held)
    # 2 faces held → 1.5^2 = 2.25× on base 56
    assert abs(br.score - 56 * 2.25) < 1e-6


def test_mult_per_unique_type():
    cards = [C("9", "Hearts"), C("9", "Clubs")]
    jokers = [{
        "key": "variety",
        "round_hand_types_ctx": ["Flush"],
        "implementation": {
            "template": "mult_per_unique_type",
            "values": {"mult_per_type": 4},
        },
    }]
    mods = apply_joker_effects(jokers, "Pair", cards)
    br = score_hand(cards, mods)
    # Pair + Flush already used → 2 unique ×4 = +8 mult; base mult 2 → 10; chips 28 → 280
    assert br.mult == 10
    assert br.score == 280


def test_xmult_with_penalty_and_discard_hooks():
    from cardgen.effects.interpreter import apply_discard_effects, apply_round_start_penalties

    cards = [C("K", "Hearts"), C("K", "Clubs")]
    jokers = [{
        "key": "costly",
        "implementation": {
            "template": "xmult_with_penalty",
            "values": {"x_mult": 2.0, "penalty_hands": 1},
        },
    }]
    mods = apply_joker_effects(jokers, "Pair", cards)
    br = score_hand(cards, mods)
    assert br.score == 120  # 30*2*2

    pen = apply_round_start_penalties(jokers)
    assert pen["penalty_hands"] == 1

    discard_j = [{
        "key": "trash",
        "implementation": {
            "template": "earn_on_discard",
            "values": {"dollars": 2, "mult": 3},
        },
    }]
    dmod = apply_discard_effects(discard_j, [C("2", "Hearts"), C("3", "Clubs")])
    assert dmod["dollars"] == 4
    assert dmod["temp_mult_bonus"] == 6
