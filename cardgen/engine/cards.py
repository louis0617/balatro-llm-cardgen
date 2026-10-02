# -*- coding: utf-8 -*-
"""Cards, hand ranking, planet levels, enhancements, chips×mult scoring."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations
from typing import Iterable

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["Hearts", "Diamonds", "Clubs", "Spades"]
RANK_VALUE = {r: i for i, r in enumerate(RANKS, start=2)}
RANK_VALUE["A"] = 14
CHIP_BY_RANK = {
    "2": 2, "3": 3, "4": 4, "5": 5, "6": 6, "7": 7, "8": 8, "9": 9, "10": 10,
    "J": 10, "Q": 10, "K": 10, "A": 11,
}

# Balatro-ish level-1 bases
HAND_BASE: dict[str, tuple[int, int]] = {
    "High Card": (5, 1),
    "Pair": (10, 2),
    "Two Pair": (20, 2),
    "Three of a Kind": (30, 3),
    "Straight": (30, 4),
    "Flush": (35, 4),
    "Full House": (40, 4),
    "Four of a Kind": (60, 7),
    "Straight Flush": (100, 8),
}

# Per planet level above 1: (+chips, +mult) — approximate Balatro
HAND_LEVEL_DELTA: dict[str, tuple[int, int]] = {
    "High Card": (10, 1),
    "Pair": (15, 1),
    "Two Pair": (20, 1),
    "Three of a Kind": (20, 2),
    "Straight": (30, 3),
    "Flush": (15, 2),
    "Full House": (25, 2),
    "Four of a Kind": (30, 3),
    "Straight Flush": (40, 4),
}

HAND_TYPES = list(HAND_BASE.keys())

ENHANCEMENTS = ("none", "bonus", "mult", "steel", "glass", "gold")


@dataclass(slots=True)
class Card:
    rank: str
    suit: str
    id: int = 0
    enhancement: str = "none"  # none|bonus|mult|steel|glass|gold

    def label(self) -> str:
        suit_letter = {"Hearts": "H", "Diamonds": "D", "Clubs": "C", "Spades": "S"}[self.suit]
        enh = "" if self.enhancement == "none" else f"[{self.enhancement[0].upper()}]"
        return f"{self.rank}{suit_letter}{enh}"

    def copy(self) -> "Card":
        return Card(self.rank, self.suit, self.id, self.enhancement)


def make_deck(
    rng=None,
    enhance_rate: float = 0.18,
    enhance_weights: list[str] | None = None,
) -> list[Card]:
    """Standard 52; optionally stamp bonus/mult/steel/glass/gold on a fraction of cards."""
    cards: list[Card] = []
    i = 0
    for suit in SUITS:
        for rank in RANKS:
            cards.append(Card(rank=rank, suit=suit, id=i))
            i += 1
    if rng is not None and enhance_rate > 0:
        n = max(0, int(round(len(cards) * enhance_rate)))
        picks = rng.sample(cards, min(n, len(cards)))
        # weight toward scoring enhancers; steel/glass for steel_glass archetype
        choices = enhance_weights or [
            "bonus",
            "bonus",
            "mult",
            "mult",
            "steel",
            "steel",
            "glass",
            "gold",
        ]
        for c in picks:
            c.enhancement = rng.choice(choices)
    return cards


def default_hand_levels() -> dict[str, int]:
    return {ht: 1 for ht in HAND_TYPES}


def hand_base_at_level(hand_type: str, level: int) -> tuple[float, float]:
    chips, mult = HAND_BASE[hand_type]
    dc, dm = HAND_LEVEL_DELTA[hand_type]
    lv = max(1, int(level))
    return float(chips + (lv - 1) * dc), float(mult + (lv - 1) * dm)


def _is_straight(values: list[int]) -> bool:
    vals = sorted(set(values))
    if len(vals) != 5:
        return False
    if vals[-1] - vals[0] == 4:
        return True
    if vals == [2, 3, 4, 5, 14]:
        return True
    return False


def classify_hand(cards: list[Card]) -> tuple[str, list[Card]]:
    if not cards:
        return "High Card", []
    cards = list(cards)[:5]
    values = [14 if c.rank == "A" else RANK_VALUE[c.rank] for c in cards]

    by_rank: dict[int, list[Card]] = {}
    for c, v in zip(cards, values):
        by_rank.setdefault(v, []).append(c)
    counts = sorted(((len(cs), v, cs) for v, cs in by_rank.items()), reverse=True)
    is_flush = len({c.suit for c in cards}) == 1 and len(cards) == 5
    is_straight = len(cards) == 5 and _is_straight(values)

    if is_straight and is_flush:
        return "Straight Flush", cards
    if counts[0][0] == 4:
        return "Four of a Kind", counts[0][2] + (counts[1][2] if len(counts) > 1 else [])
    if counts[0][0] == 3 and len(counts) > 1 and counts[1][0] == 2:
        return "Full House", counts[0][2] + counts[1][2]
    if is_flush:
        return "Flush", cards
    if is_straight:
        return "Straight", cards
    if counts[0][0] == 3:
        return "Three of a Kind", counts[0][2]
    if counts[0][0] == 2 and len(counts) > 1 and counts[1][0] == 2:
        return "Two Pair", counts[0][2] + counts[1][2]
    if counts[0][0] == 2:
        return "Pair", counts[0][2]
    top = max(cards, key=lambda c: (14 if c.rank == "A" else RANK_VALUE[c.rank]))
    return "High Card", [top]


@dataclass
class ScoreBreakdown:
    hand_type: str
    chips: float
    mult: float
    x_mult: float
    score: float
    notes: list[str]
    dollars_earned: float = 0.0


def score_hand(
    played: list[Card],
    joker_mods: Iterable[dict] | None = None,
    hand_levels: dict[str, int] | None = None,
    held_unplayed: list[Card] | None = None,
) -> ScoreBreakdown:
    """
    Order: planet base + scored card chips (+bonus/mult enh) + joker chips/mult/x,
    × glass (scored) × steel (held), then scored-card retrigger passes.

    Retrigger (Mini): ``retrigger_count`` / legacy ``retrigger_factor`` means extra
    passes that re-add scored-card face chips + bonus/mult enh and re-apply glass
    ×2 per glass card. Joker flat/x mods and held steel are NOT re-applied.
    ``retrigger_factor`` 2.0 == one extra pass (backward compatible with 1+n mapping).
    """
    hand_type, scoring_cards = classify_hand(played)
    levels = hand_levels or default_hand_levels()
    base_chips, base_mult = hand_base_at_level(hand_type, levels.get(hand_type, 1))
    chips = float(base_chips)
    mult = float(base_mult)
    lv = levels.get(hand_type, 1)
    notes = [f"base {hand_type} L{lv} {base_chips:.0f}x{base_mult:.0f}"]

    def _apply_scored_card_pass(pass_label: str) -> None:
        nonlocal chips, mult, x_product
        for c in scoring_cards:
            chips += CHIP_BY_RANK[c.rank]
            notes.append(f"{pass_label} card {c.label()}+{CHIP_BY_RANK[c.rank]}")
            if c.enhancement == "bonus":
                chips += 30
                notes.append(f"{pass_label} bonus +30 chips")
            if c.enhancement == "mult":
                mult += 4
                notes.append(f"{pass_label} mult enh +4")
        for c in scoring_cards:
            if c.enhancement == "glass":
                x_product *= 2.0
                notes.append(f"{pass_label} glass {c.label()} x2")

    x_product = 1.0
    dollars = 0.0

    _apply_scored_card_pass("score")

    # Steel: held in hand (not played) each ×1.5 — once, not retriggered
    for c in held_unplayed or []:
        if c.enhancement == "steel":
            x_product *= 1.5
            notes.append(f"steel held {c.label()} x1.5")

    retrigger_extra = 0
    for mod in joker_mods or []:
        if not mod.get("active", True):
            continue
        if mod.get("add_chips"):
            chips += float(mod["add_chips"])
            notes.append(f"joker +{mod['add_chips']} chips")
        if mod.get("add_mult"):
            mult += float(mod["add_mult"])
            notes.append(f"joker +{mod['add_mult']} mult")
        if mod.get("x_mult"):
            x_product *= float(mod["x_mult"])
            notes.append(f"joker x{mod['x_mult']}")
        if mod.get("retrigger_count") is not None:
            retrigger_extra += max(0, int(mod["retrigger_count"]))
        elif mod.get("retrigger_factor"):
            # legacy: factor 2.0 => 1 extra scored-card pass
            f = float(mod["retrigger_factor"])
            retrigger_extra += max(0, int(round(f)) - 1)
        if mod.get("dollars"):
            dollars += float(mod["dollars"])
            notes.append(f"joker +${mod['dollars']}")

    for i in range(retrigger_extra):
        notes.append(f"retrigger pass {i + 1}/{retrigger_extra}")
        _apply_scored_card_pass(f"retrigger{i + 1}")

    score = chips * mult * x_product
    return ScoreBreakdown(
        hand_type=hand_type,
        chips=chips,
        mult=mult,
        x_mult=x_product,
        score=score,
        notes=notes,
        dollars_earned=dollars,
    )


def all_play_combos(hand: list[Card]) -> list[tuple[Card, ...]]:
    combos: list[tuple[Card, ...]] = []
    n = len(hand)
    for k in range(1, min(5, n) + 1):
        combos.extend(combinations(hand, k))
    return combos
