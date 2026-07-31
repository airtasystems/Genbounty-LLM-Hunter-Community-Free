"""Fetchers: tiered strategies from pool to human-mimicking browser."""

from browser_bot.fetchers.pool import PoolFetcher
from browser_bot.fetchers.cluster import ClusterFetcher
from browser_bot.fetchers.human import HumanFetcher

__all__ = [
    "PoolFetcher",
    "ClusterFetcher",
    "HumanFetcher",
]
