"""Shared load/save helpers for site/component probe suite JSON files."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from fastapi import HTTPException

from web.paths import BB_DIR


def test_suite_path(site: str, component: str, strategy: str, playbook: str) -> Path:
    """BB_DIR/sites/{site}/{component}/tests/{strategy}/{playbook}.json"""
    return BB_DIR / "sites" / site / component / "tests" / strategy / f"{playbook}.json"


def load_test_suite(site: str, component: str, strategy: str, playbook: str) -> dict:
    """Load JSON or raise HTTPException 404."""
    path = test_suite_path(site, component, strategy, playbook)
    if not path.exists():
        raise HTTPException(404, "Test file not found")
    return json.loads(path.read_text(encoding="utf-8"))


def save_test_suite(path: Path, data: dict) -> None:
    """Write pretty JSON with trailing newline."""
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def apply_suite_transform(
    site: str,
    component: str,
    strategy: str,
    playbook: str,
    transform_fn: Callable[[dict], tuple[dict, int]],
    *,
    empty_message: str,
) -> tuple[dict, int]:
    """
    load suite, call transform_fn(data) -> (new_data, count),
    if count==0 raise HTTPException 400 with empty_message,
    save and return (new_data, count).
    Propagate ValueError as 400, RuntimeError as 503.
    """
    path = test_suite_path(site, component, strategy, playbook)
    data = load_test_suite(site, component, strategy, playbook)
    try:
        new_data, count = transform_fn(data)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    if count == 0:
        raise HTTPException(400, empty_message)
    save_test_suite(path, new_data)
    return new_data, count
