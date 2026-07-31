"""Metrics collection for fetcher performance."""

from collections import defaultdict
from typing import Dict, List


class Metrics:
    """Track fetch times by tier."""

    def __init__(self):
        self._times: Dict[str, List[float]] = defaultdict(list)

    def record(self, tier: str, elapsed: float):
        self._times[tier].append(elapsed)

    def summary(self) -> str:
        lines = []
        for tier in sorted(self._times.keys()):
            times = self._times[tier]
            total = sum(times)
            avg = total / len(times)
            lines.append(
                f"{tier.upper()}: total {total:.2f}s avg {avg:.2f}s count {len(times)}"
            )
        return "\n".join(lines) if lines else "No metrics"
