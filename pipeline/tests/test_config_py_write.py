"""Regression: Browser Config must persist annotated assignments in config.py."""

from __future__ import annotations

from pipeline.component_settings import _write_config_py_value


def test_write_config_py_value_updates_annotated_assignment():
    source = (
        "# header\n"
        "API_CONCURRENCY: int = 2\n"
        "EVASION_REQUEST_DELAY_S: float = 0.5\n"
        "POOL_SIZE = 1\n"
    )
    out = _write_config_py_value(source, "API_CONCURRENCY", 8)
    assert "API_CONCURRENCY: int = 8\n" in out
    assert "EVASION_REQUEST_DELAY_S: float = 0.5\n" in out
    assert "POOL_SIZE = 1\n" in out


def test_write_config_py_value_updates_plain_assignment():
    source = "POOL_SIZE = 1\nAPI_CONCURRENCY = 2\n"
    out = _write_config_py_value(source, "API_CONCURRENCY", 8)
    assert "API_CONCURRENCY = 8\n" in out


def test_write_config_py_value_missing_key_raises():
    try:
        _write_config_py_value("POOL_SIZE = 1\n", "API_CONCURRENCY", 8)
    except ValueError as exc:
        assert "API_CONCURRENCY" in str(exc)
    else:
        raise AssertionError("expected ValueError for missing assignment")
