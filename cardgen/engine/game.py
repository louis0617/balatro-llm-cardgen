# -*- coding: utf-8 -*-
"""Headless MiniBalatro: planets, enhancements, economy, expanded shop."""
from __future__ import annotations

import math
import random
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Callable

from cardgen.effects.interpreter import (
    BUILTIN_POOL,
    apply_discard_effects,
    apply_joker_effects,
    apply_round_start_penalties,
    interest_bonus_from_jokers,
    load_spec_as_joker,
)
from cardgen.engine.cards import (
    HAND_TYPES,
    Card,
    all_play_combos,
    default_hand_levels,
    make_deck,
    score_hand,
)

BLIND_TARGETS = {
    1: [300, 450, 600],
    2: [800, 1200, 1600],
    3: [2000, 3000, 4000],
    4: [5000, 7500, 10000],
    5: [11000, 16500, 22000],
    6: [20000, 30000, 40000],
    7: [35000, 52500, 70000],
    8: [50000, 75000, 100000],
}
BLIND_NAMES = ["Small", "Big", "Boss"]
HAND_SIZE = 8
HANDS_PER_BLIND = 4
DISCARDS_PER_BLIND = 4
MAX_JOKERS = 5
PLANET_COST = 2
# Fingerprint for stale-import detection (old ante-end mega-shop is gone).
SHOP_PROTOCOL = "post_blind_v2"


def assert_shop_protocol(event_log: list[dict[str, Any]] | None) -> str:
    """Fail hard if a process still runs the retired ante-end shop.

    Runs that never clear a blind have no shop_enter — that is not a stale-import
    signal (unlucky seeds / short batches). Only reject wrong fingerprints.
    """
    events = event_log or []
    for e in events:
        src = e.get("source")
        if src == "ante_end_celestial":
            raise RuntimeError(
                "检测到旧商店指纹 source=ante_end_celestial。"
                "请重启 Streamlit（旧进程缓存了 game.py）。"
            )
    for e in events:
        if e.get("event") == "shop_enter" and e.get("shop_protocol") == SHOP_PROTOCOL:
            return SHOP_PROTOCOL
    for e in events:
        if e.get("event") == "shop_enter":
            raise RuntimeError(
                f"shop_enter 协议异常: got={e.get('shop_protocol')!r}, "
                f"expected={SHOP_PROTOCOL!r}。"
            )
    if SHOP_PROTOCOL != "post_blind_v2":
        raise RuntimeError(f"SHOP_PROTOCOL 异常: {SHOP_PROTOCOL!r}")
    return SHOP_PROTOCOL


@dataclass
class HandActionRecord:
    ante: int
    blind: str
    hand_index: int
    action: str
    cards: list[str]
    hand_type: str | None
    score: float
    alternative_scores: list[float]
    action_entropy: float
    jokers_held: list[str]
    ante_f: float
    blind_type_cat: str
    hands_left: float
    discards_left: float
    dollars: float
    n_jokers: float
    hand_index_in_round: float
    score_pressure: float
    n_xmult: float
    n_additive: float
    archetype_entropy: float


@dataclass
class RunResult:
    seed: int
    outcome: str
    final_ante: int
    total_score: float
    jokers_acquired: list[str]
    per_hand_actions: list[HandActionRecord] = field(default_factory=list)
    n_discards: int = 0
    n_plays: int = 0
    hand_levels: dict[str, int] = field(default_factory=dict)
    event_log: list[dict[str, Any]] = field(default_factory=list)
    # MiniBalatro is headless; no measured think time.


def _entropy(scores: list[float]) -> float:
    if len(scores) < 2:
        return 0.0
    s = list(scores)
    m = max(s)
    ex = [math.exp((x - m) / max(abs(m), 1.0)) for x in s]
    z = sum(ex) or 1.0
    p = [e / z for e in ex]
    h = -sum(pi * math.log(pi + 1e-12) for pi in p)
    return float(h / math.log(len(p)))


def _roster_counts(jokers: list[dict]) -> tuple[int, int, float]:
    n_x = sum(1 for j in jokers if j.get("effect_type") == "xMult")
    n_add = sum(1 for j in jokers if j.get("effect_type") in ("+Mult", "+Chips", "Hybrid"))
    types = [j.get("effect_type") or "Other" for j in jokers]
    if not types:
        return 0, 0, 0.0
    c = Counter(types)
    total = sum(c.values())
    probs = [v / total for v in c.values()]
    h = -sum(p * math.log(p) for p in probs)
    ent = h / math.log(len(c)) if len(c) > 1 else 0.0
    return n_x, n_add, float(ent)


class MiniBalatro:
    def __init__(
        self,
        seed: int = 0,
        extra_jokers: list[dict] | None = None,
        agent: Callable[..., Any] | None = None,
        force_hold_jokers: list[dict] | None = None,
        enhance_rate: float = 0.22,
        enhance_weights: list[str] | None = None,
    ):
        self.rng = random.Random(seed)
        self.seed = seed
        self.enhance_rate = float(enhance_rate)
        self.enhance_weights = list(enhance_weights) if enhance_weights else None
        self.pool = [deepcopy(j) for j in BUILTIN_POOL]
        if extra_jokers:
            for spec in extra_jokers:
                self.pool.append(load_spec_as_joker(spec))
        self.force_hold_jokers = [deepcopy(j) for j in (force_hold_jokers or [])]
        self.agent = agent
        self.reset_run()

    def reset_run(self) -> None:
        self.dollars = 4
        self.ante = 1
        self.jokers: list[dict] = []
        self.acquired: list[str] = []
        self.deck: list[Card] = []
        self.hand: list[Card] = []
        self.actions: list[HandActionRecord] = []
        self.n_discards = 0
        self.n_plays = 0
        self.total_score = 0.0
        self.hand_levels = default_hand_levels()
        self.planet_buys = 0
        self._ante_hand_plays: Counter[str] = Counter()
        self._full_deck_template = make_deck(
            self.rng,
            enhance_rate=self.enhance_rate,
            enhance_weights=self.enhance_weights,
        )
        self.event_log: list[dict[str, Any]] = []
        self.round_hand_types_used: set[str] = set()
        self.temp_mult_bonus: float = 0.0
        self._blind_target: float = 0.0
        self._cum_score: float = 0.0

    def _log(self, event: str, **payload: Any) -> None:
        row = {"event": event, "ante": self.ante, "dollars": self.dollars, **payload}
        self.event_log.append(row)
    def _count_steel_in_run(self) -> int:
        return sum(1 for c in self._full_deck_template if c.enhancement == "steel")

    def _shuffle_deck(self) -> None:
        # rebuild from template (glass may have been destroyed)
        self.deck = [c.copy() for c in self._full_deck_template]
        self.rng.shuffle(self.deck)

    def _draw(self, n: int) -> None:
        for _ in range(n):
            if not self.deck:
                break
            self.hand.append(self.deck.pop())

    def _enrich_jokers(self, hands_left: int = 1) -> list[dict]:
        enriched = []
        n_steel = self._count_steel_in_run()
        for j in self.jokers:
            jj = dict(j)
            jj["discards_left_ctx"] = getattr(self, "_discards_left", 0)
            jj["n_jokers_ctx"] = len(self.jokers)
            jj["deck_left_ctx"] = len(self.deck)
            jj["hands_left_ctx"] = hands_left
            jj["plays_ctx"] = self.n_plays
            jj["ante_ctx"] = self.ante
            jj["dollars_ctx"] = self.dollars
            jj["n_steel_ctx"] = n_steel
            jj["planet_buys_ctx"] = self.planet_buys
            jj["round_hand_types_ctx"] = list(self.round_hand_types_used)
            jj["temp_mult_bonus_ctx"] = float(self.temp_mult_bonus)
            if jj.get("builtin") == "j_misprint":
                jj["misprint_mult"] = self.rng.randint(0, 23)
            enriched.append(jj)
        return enriched

    def _score_play(self, cards: list[Card], hands_left: int = 1) -> Any:
        played_ids = {id(c) for c in cards}
        held = [c for c in self.hand if id(c) not in played_ids]
        enriched = self._enrich_jokers(hands_left=hands_left)
        # hand_level_ctx for supernova: level of classified type — classify first
        base = score_hand(cards, [], self.hand_levels, held)
        for jj in enriched:
            jj["hand_level_ctx"] = self.hand_levels.get(base.hand_type, 1)
        mods = apply_joker_effects(enriched, base.hand_type, cards, held=held)
        return score_hand(cards, mods, self.hand_levels, held)

    def evaluate_combos(self) -> list[tuple[tuple[Card, ...], float, str]]:
        out = []
        # Match actual play scoring: hands_left_ctx is remaining AFTER this play
        hands_now = getattr(self, "_hands_left", 1)
        after = max(0, hands_now - 1)
        for combo in all_play_combos(self.hand):
            br = self._score_play(list(combo), hands_left=after)
            out.append((combo, br.score, br.hand_type))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    def upgrade_hand(self, hand_type: str, n: int = 1) -> None:
        if hand_type not in self.hand_levels:
            return
        self.hand_levels[hand_type] = min(20, self.hand_levels[hand_type] + n)

    def _post_play_joker_state(self, hand_type: str, used_discard_this_blind: bool) -> None:
        for j in self.jokers:
            b = j.get("builtin")
            if b == "j_ride_the_bus":
                if hand_type in ("Pair", "Two Pair", "Three of a Kind", "Full House", "Four of a Kind"):
                    j["bus_streak"] = 0
                else:
                    j["bus_streak"] = int(j.get("bus_streak", 0)) + 1
            elif b == "j_green_joker":
                j["green_mult"] = int(j.get("green_mult", 0)) + 1
            elif b == "j_ice_cream":
                j["ice_chips"] = max(0, int(j.get("ice_chips", 100)) - 5)
            elif b == "j_space" and self.rng.random() < 0.25:
                self.upgrade_hand(hand_type, 1)

    def _maybe_break_glass(self, scored: list[Card]) -> None:
        for c in scored:
            if c.enhancement == "glass" and self.rng.random() < 0.25:
                self._full_deck_template = [
                    x for x in self._full_deck_template if x.id != c.id
                ]

    def _gold_payout(self) -> None:
        # end of blind: $3 per gold card still in hand
        n = sum(1 for c in self.hand if c.enhancement == "gold")
        self.dollars += 3 * n

    def _record(
        self,
        blind: str,
        hand_index: int,
        action: str,
        cards: list[Card],
        hand_type: str | None,
        score: float,
        alt_scores: list[float],
        hands_left: int,
        discards_left: int,
        cum_score: float,
        target: float,
    ) -> None:
        n_x, n_add, ent = _roster_counts(self.jokers)
        remaining = max(0.0, target - cum_score)
        pressure = (remaining / target) if target > 0 else 0.0
        self.actions.append(
            HandActionRecord(
                ante=self.ante,
                blind=blind,
                hand_index=hand_index,
                action=action,
                cards=[c.label() for c in cards],
                hand_type=hand_type,
                score=score,
                alternative_scores=alt_scores[:12],
                action_entropy=_entropy(alt_scores) if alt_scores else 0.0,
                jokers_held=[j.get("key", j.get("name", "?")) for j in self.jokers],
                ante_f=float(self.ante),
                blind_type_cat=blind,
                hands_left=float(hands_left),
                discards_left=float(discards_left),
                dollars=float(self.dollars),
                n_jokers=float(len(self.jokers)),
                hand_index_in_round=float(hand_index + 1),
                score_pressure=float(min(1.0, pressure)),
                n_xmult=float(n_x),
                n_additive=float(n_add),
                archetype_entropy=float(ent),
            )
        )

    def play_blind(self, blind_idx: int) -> bool:
        blind = BLIND_NAMES[blind_idx]
        target = BLIND_TARGETS[self.ante][blind_idx]
        self._shuffle_deck()
        self.hand = []
        self._draw(HAND_SIZE)
        hands_left = HANDS_PER_BLIND
        discards_left = DISCARDS_PER_BLIND
        # round-start penalty hooks (xmult_with_penalty)
        penalties = apply_round_start_penalties(self.jokers)
        hands_left = max(1, hands_left - int(penalties.get("penalty_hands", 0)))
        discards_left = max(0, discards_left - int(penalties.get("penalty_discards", 0)))
        self.dollars = max(0, self.dollars - int(penalties.get("penalty_dollars", 0)))
        self.round_hand_types_used = set()
        self.temp_mult_bonus = 0.0
        cum = 0.0
        hand_index = 0
        used_discard = False
        self._blind_target = float(target)
        self._cum_score = 0.0
        self._log(
            "blind_start",
            blind=blind,
            target=target,
            hands_left=hands_left,
            discards_left=discards_left,
            penalties=penalties,
            jokers=[j.get("key") or j.get("name") for j in self.jokers],
        )

        while hands_left > 0 and cum < target:
            self._discards_left = discards_left
            self._hands_left = hands_left
            self._cum_score = cum
            if self.agent is None:
                raise RuntimeError("agent required")
            decision = self.agent(self, "blind")
            action = decision.get("action", "play")
            if action == "discard" and discards_left > 0:
                idxs = decision.get("card_indices") or []
                idxs = sorted(set(idxs), reverse=True)
                discarded = []
                for i in idxs:
                    if 0 <= i < len(self.hand):
                        discarded.append(self.hand.pop(i))
                n = len(discarded)
                discards_left -= 1
                used_discard = True
                self.n_discards += 1
                # discard-time joker hooks
                dmod = apply_discard_effects(
                    self.jokers,
                    discarded,
                    held=self.hand,
                    money=int(self.dollars),
                    discards_left=discards_left,
                    hands_left=hands_left,
                    ante=self.ante,
                )
                self.dollars += int(dmod.get("dollars", 0))
                self.temp_mult_bonus += float(dmod.get("temp_mult_bonus", 0))
                for j in self.jokers:
                    if j.get("builtin") == "j_green_joker":
                        j["green_mult"] = max(0, int(j.get("green_mult", 0)) - 1)
                alts = [s for _, s, _ in self.evaluate_combos()[:8]]
                self._record(
                    blind, hand_index, "discard", discarded, None, 0.0, alts,
                    hands_left, discards_left, cum, target,
                )
                self._log(
                    "discard",
                    blind=blind,
                    cards=[c.label() for c in discarded],
                    discards_left=discards_left,
                    cum_score=cum,
                    target=target,
                    dollars_from_discard=int(dmod.get("dollars", 0)),
                    temp_mult_bonus=self.temp_mult_bonus,
                )
                self._draw(n)
                hand_index += 1
                continue

            idxs = decision.get("card_indices")
            if idxs is None:
                combos = self.evaluate_combos()
                best = list(combos[0][0]) if combos else self.hand[:1]
            else:
                best = [self.hand[i] for i in idxs if 0 <= i < len(self.hand)]
            if not best:
                best = self.hand[:1]
            br = self._score_play(best, hands_left=hands_left - 1)
            # consume discard→next-hand temp mult after it was applied in this score
            self.temp_mult_bonus = 0.0
            alts = [s for _, s, _ in self.evaluate_combos()]
            played_ids = {id(c) for c in best}
            self.hand = [c for c in self.hand if id(c) not in played_ids]
            cum += br.score
            self.total_score += br.score
            self.dollars += int(br.dollars_earned)
            hands_left -= 1
            self.n_plays += 1
            self._ante_hand_plays[br.hand_type] += 1
            self.round_hand_types_used.add(br.hand_type)
            self._post_play_joker_state(br.hand_type, used_discard)
            self._maybe_break_glass(best)
            self._record(
                blind, hand_index, "play", best, br.hand_type, br.score, alts,
                hands_left, discards_left, cum, target,
            )
            self._log(
                "play",
                blind=blind,
                cards=[c.label() for c in best],
                hand_type=br.hand_type,
                hand_score=br.score,
                cum_score=cum,
                target=target,
                hands_left=hands_left,
                dollars_from_jokers=int(br.dollars_earned),
                hand_level=self.hand_levels.get(br.hand_type, 1),
            )
            self._draw(len(best))
            hand_index += 1

        cleared = cum >= target
        if cleared:
            self._gold_payout()
            if not used_discard:
                for j in self.jokers:
                    if j.get("builtin") == "j_delayed_grat":
                        self.dollars += 2 * DISCARDS_PER_BLIND
        self._log(
            "blind_end",
            blind=blind,
            cleared=cleared,
            blind_score=cum,
            target=target,
            total_score=self.total_score,
        )
        return cleared

    def shop(self, free_planet: bool = False) -> None:
        """Post-blind shop only (retired: ante-end mega-shop / gen-card shelf boost).

        - open after each cleared blind
        - at most 1 joker purchase per visit (sell-then-buy still allowed)
        - at most 3 actions total (sell / buy / planet)
        """
        weights = [
            {"Common": 4.0, "Uncommon": 2.0, "Rare": 0.8, "Legendary": 0.2}.get(
                j.get("rarity", "Common"), 1.0
            )
            for j in self.pool
        ]
        if free_planet and self._ante_hand_plays:
            ht = self._ante_hand_plays.most_common(1)[0][0]
            before = self.hand_levels.get(ht, 1)
            self.upgrade_hand(ht, 1)
            self.planet_buys += 1
            self._log(
                "planet_free",
                hand_type=ht,
                level_before=before,
                level_after=self.hand_levels.get(ht, 1),
                source="boss_celestial",
            )
        if self.agent is None:
            return

        self._log(
            "shop_enter",
            dollars=self.dollars,
            n_jokers=len(self.jokers),
            free_planet=bool(free_planet),
            shop_protocol=SHOP_PROTOCOL,
        )
        joker_buys = 0
        for _ in range(3):
            offers = [
                deepcopy(self.rng.choices(self.pool, weights=weights, k=1)[0])
                for _ in range(2)
            ]
            planet_type = self.rng.choice(HAND_TYPES)
            if self._ante_hand_plays:
                planet_type = self._ante_hand_plays.most_common(1)[0][0]
            planet = {
                "kind": "planet",
                "hand_type": planet_type,
                "cost": PLANET_COST,
                "name": f"Planet:{planet_type}",
            }
            decision = self.agent(
                self,
                "shop",
                offers=offers,
                planet=planet,
                joker_buys_this_shop=joker_buys,
                max_joker_buys=1,
            )
            action = decision.get("action", "skip")
            if action == "skip":
                self._log(
                    "shop_skip",
                    offers=[o.get("name") or o.get("key") for o in offers],
                    planet=planet_type,
                )
                break
            if action == "buy_planet":
                ht = decision.get("hand_type") or planet_type
                if self.dollars >= PLANET_COST:
                    self.dollars -= PLANET_COST
                    before = self.hand_levels.get(ht, 1)
                    self.upgrade_hand(ht, 1)
                    self.planet_buys += 1
                    self._log(
                        "planet_buy",
                        hand_type=ht,
                        cost=PLANET_COST,
                        level_before=before,
                        level_after=self.hand_levels.get(ht, 1),
                    )
                else:
                    break
            elif action == "buy":
                if joker_buys >= 1:
                    self._log("shop_buy_blocked", reason="max_joker_buys")
                    break
                idx = int(decision.get("offer_index", 0))
                if not (0 <= idx < len(offers)):
                    break
                card = offers[idx]
                cost = int(card.get("cost", 5))
                if self.dollars < cost or len(self.jokers) >= MAX_JOKERS:
                    break
                self.dollars -= cost
                if card.get("builtin") == "j_ice_cream":
                    card["ice_chips"] = 100
                if card.get("builtin") == "j_ride_the_bus":
                    card["bus_streak"] = 0
                if card.get("builtin") == "j_green_joker":
                    card["green_mult"] = 0
                self.jokers.append(card)
                key = card.get("key", card.get("name", "?"))
                self.acquired.append(key)
                joker_buys += 1
                self._log(
                    "joker_buy",
                    key=key,
                    name=card.get("name"),
                    cost=cost,
                    generated=bool(card.get("generated")),
                    effect_type=card.get("effect_type"),
                    jokers_now=[j.get("key") or j.get("name") for j in self.jokers],
                    dollars_left=self.dollars,
                )
            elif action == "sell" and self.jokers:
                idx = int(decision.get("joker_index", 0))
                if 0 <= idx < len(self.jokers):
                    sold = self.jokers.pop(idx)
                    gain = max(1, int(sold.get("cost", 4)) // 2)
                    self.dollars += gain
                    self._log(
                        "joker_sell",
                        key=sold.get("key"),
                        name=sold.get("name"),
                        dollars_gained=gain,
                        dollars_after=self.dollars,
                        jokers_now=[j.get("key") or j.get("name") for j in self.jokers],
                    )
            else:
                break
        self._log(
            "shop_leave",
            dollars=self.dollars,
            n_jokers=len(self.jokers),
            joker_buys=joker_buys,
        )

    def _after_blind_planet(self, blind_hand_plays: Counter) -> None:
        if blind_hand_plays:
            ht = blind_hand_plays.most_common(1)[0][0]
            before = self.hand_levels.get(ht, 1)
            self.upgrade_hand(ht, 1)
            self.planet_buys += 1
            self._log(
                "planet_free",
                hand_type=ht,
                level_before=before,
                level_after=self.hand_levels.get(ht, 1),
                source="after_blind",
            )

    def run(self) -> RunResult:
        self.reset_run()
        self._log("run_start", seed=self.seed)
        # 不开局赠送 j_joker：与真局「空槽开买」更接近，避免免费 +4 Mult 抬高基线、冲淡新卡信号
        for fj in self.force_hold_jokers:
            card = load_spec_as_joker(deepcopy(fj))
            if len(self.jokers) < MAX_JOKERS:
                self.jokers.append(card)
                key = card.get("key", card.get("name", "?"))
                self.acquired.append(key)
                self._log(
                    "joker_start",
                    key=key,
                    name=card.get("name"),
                    source="force_hold",
                )

        final_ante = 1
        for ante in range(1, 9):
            self.ante = ante
            final_ante = ante
            self._ante_hand_plays = Counter()
            self._log("ante_start", ante=ante)
            for bi in range(3):
                before = Counter(self._ante_hand_plays)
                cleared = self.play_blind(bi)
                blind_plays: Counter = Counter()
                for k, v in self._ante_hand_plays.items():
                    blind_plays[k] = v - before.get(k, 0)
                if not cleared:
                    self._log(
                        "run_end",
                        outcome="death",
                        final_ante=final_ante,
                        total_score=self.total_score,
                        jokers_acquired=list(self.acquired),
                        hand_levels=dict(self.hand_levels),
                    )
                    return RunResult(
                        seed=self.seed,
                        outcome="death",
                        final_ante=final_ante,
                        total_score=self.total_score,
                        jokers_acquired=list(self.acquired),
                        per_hand_actions=self.actions,
                        n_discards=self.n_discards,
                        n_plays=self.n_plays,
                        hand_levels=dict(self.hand_levels),
                        event_log=list(self.event_log),
                    )
                reward = 3 + bi
                interest = min(self.dollars // 5, 5) + interest_bonus_from_jokers(self.jokers)
                self.dollars += reward + interest
                self._log(
                    "blind_reward",
                    reward=reward,
                    interest=interest,
                    dollars_after=self.dollars,
                )
                self._after_blind_planet(blind_plays)
                # Shop after *each* blind (Balatro-like). Free celestial pack only after Boss.
                self.shop(free_planet=(bi == 2))
        self._log(
            "run_end",
            outcome="win",
            final_ante=8,
            total_score=self.total_score,
            jokers_acquired=list(self.acquired),
            hand_levels=dict(self.hand_levels),
        )
        return RunResult(
            seed=self.seed,
            outcome="win",
            final_ante=8,
            total_score=self.total_score,
            jokers_acquired=list(self.acquired),
            per_hand_actions=self.actions,
            n_discards=self.n_discards,
            n_plays=self.n_plays,
            hand_levels=dict(self.hand_levels),
            event_log=list(self.event_log),
        )
