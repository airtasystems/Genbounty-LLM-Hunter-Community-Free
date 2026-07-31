"""Tests for pool/cluster UI parallel submission sizing."""

from dataclasses import dataclass

from browser_bot.submit.common import (
    normalize_ui_submit_result,
    resolve_ui_parallel_concurrency,
)


@dataclass
class _Bundle:
    _pool_size: int = 0
    _cluster_workers: int = 0
    _use_cdp: bool = False
    _launch_headless: bool | None = True


def _strategies(*tiers: str):
    return [(object(), False, tier) for tier in tiers]


def test_parallel_concurrency_uses_pool_workers():
    bundle = _Bundle(_pool_size=4, _launch_headless=True)
    n = resolve_ui_parallel_concurrency(
        site="example.com",
        component="chat",
        strategies=_strategies("pool", "human"),
        work_count=10,
        stop_words=[],
        fetcher_bundle=bundle,
    )
    assert n == 4


def test_parallel_concurrency_capped_by_work_count():
    bundle = _Bundle(_pool_size=8, _launch_headless=True)
    n = resolve_ui_parallel_concurrency(
        site="example.com",
        component="chat",
        strategies=_strategies("pool"),
        work_count=3,
        stop_words=[],
        fetcher_bundle=bundle,
    )
    assert n == 3


def test_stop_words_do_not_force_sequential():
    """Success markers must not serialize pool/cluster runs — concurrency wins."""
    bundle = _Bundle(_pool_size=4, _launch_headless=True)
    n = resolve_ui_parallel_concurrency(
        site="example.com",
        component="chat",
        strategies=_strategies("pool"),
        work_count=10,
        stop_words=["FLAG{"],
        fetcher_bundle=bundle,
    )
    assert n == 4


def test_cdp_and_headed_force_sequential():
    bundle = _Bundle(_pool_size=4, _use_cdp=True, _launch_headless=False)
    n = resolve_ui_parallel_concurrency(
        site="example.com",
        component="chat",
        strategies=_strategies("pool"),
        work_count=10,
        stop_words=[],
        fetcher_bundle=bundle,
    )
    assert n == 1


def test_normalize_ui_submit_result():
    assert normalize_ui_submit_result(None, "prompt") == ("prompt", None, {})
    assert normalize_ui_submit_result(("a", "b", {"x": 1}), "z") == ("a", "b", {"x": 1})
