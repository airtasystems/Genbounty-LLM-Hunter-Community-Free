"""Theory-history clear_elite query flag."""

from __future__ import annotations

import inspect
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_clear_theory_history_accepts_clear_elite_flag():
    import sys

    if str(_ROOT) not in sys.path:
        sys.path.insert(0, str(_ROOT))
    from web.routers import operator as op

    sig = inspect.signature(op.api_clear_theory_history)
    assert "clear_elite" in sig.parameters
    src = inspect.getsource(op.api_clear_theory_history)
    assert "clear_elite_genomes" in src
    assert 'not in (\n        "0"' in src or '"0"' in src
    assert "clear_elite_flag" in src
