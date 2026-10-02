# -*- coding: utf-8 -*-
from cardgen.agents.greedy import greedy_agent
from cardgen.engine.game import MiniBalatro


def test_run_completes():
    g = MiniBalatro(seed=1, agent=greedy_agent)
    r = g.run()
    assert r.outcome in ("win", "death")
    assert r.final_ante >= 1
    assert len(r.per_hand_actions) > 0
    assert r.hand_levels["Pair"] >= 1


def test_seed_reproducible():
    a = MiniBalatro(seed=7, agent=greedy_agent).run()
    b = MiniBalatro(seed=7, agent=greedy_agent).run()
    assert a.outcome == b.outcome
    assert a.final_ante == b.final_ante
    assert a.total_score == b.total_score


def test_baseline_mean_ante_at_least_4():
    """Calibration gate: greedy baseline should typically reach ante ≥ 4."""
    antes = [
        MiniBalatro(seed=100 + i, agent=greedy_agent).run().final_ante
        for i in range(40)
    ]
    mean_ante = sum(antes) / len(antes)
    assert mean_ante >= 4.0, f"mean final_ante={mean_ante:.2f} < 4; antes={antes[:10]}..."
    assert sum(1 for a in antes if a >= 4) >= 20
