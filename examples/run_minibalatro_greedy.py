# -*- coding: utf-8 -*-
"""Minimal MiniBalatro + greedy agent run (no BC weights, no API)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cardgen.agents.greedy import greedy_agent  # noqa: E402
from cardgen.engine.game import MiniBalatro  # noqa: E402


def main() -> None:
    result = MiniBalatro(seed=0, agent=greedy_agent).run()
    print(
        f"outcome={result.outcome} final_ante={result.final_ante} "
        f"total_score={result.total_score} hands={len(result.per_hand_actions)}"
    )
    print("ok")


if __name__ == "__main__":
    main()
