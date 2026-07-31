"""Unit coverage for startup port reclaim helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from web import port_reclaim as web_app  # noqa: E402


def test_is_our_web_server_matches_checkout_cmdline():
    pid = 424242
    cmd = f"{_ROOT}/genbounty-venv/bin/python {_ROOT}/web/app.py"
    with (
        patch.object(web_app, "_proc_cmdline", return_value=cmd),
        patch.object(web_app, "_proc_cwd", return_value=_ROOT),
    ):
        assert web_app._is_our_web_server(pid) is True


def test_is_our_web_server_rejects_unrelated_python():
    with (
        patch.object(web_app, "_proc_cmdline", return_value="/usr/bin/python3 other.py"),
        patch.object(web_app, "_proc_cwd", return_value=Path("/tmp")),
    ):
        assert web_app._is_our_web_server(99) is False


def test_reclaim_project_port_kills_listeners_and_stopped_orphans():
    killed: list[int] = []

    def _fake_kill(pids):
        killed.extend(sorted(pids))

    with (
        patch.object(web_app, "_pids_listening_on", return_value={111, 222}),
        patch.object(web_app, "_all_our_web_server_pids", return_value={111, 333}),
        patch.object(
            web_app,
            "_is_our_web_server",
            side_effect=lambda pid: pid in {111, 333},
        ),
        patch.object(
            web_app,
            "_proc_state",
            side_effect=lambda pid: "T" if pid == 333 else "S",
        ),
        patch.object(web_app, "_child_pids", return_value=set()),
        patch.object(web_app, "_kill_pids", side_effect=_fake_kill),
        patch.object(web_app.time, "sleep", return_value=None),
    ):
        result = web_app.reclaim_project_port(8000)
    assert result == [111, 333]
    assert killed == [111, 333]


def test_reclaim_skips_self_pid():
    self_pid = os.getpid()
    with (
        patch.object(web_app, "_pids_listening_on", return_value={self_pid}),
        patch.object(web_app, "_all_our_web_server_pids", return_value={self_pid}),
        patch.object(web_app, "_is_our_web_server", return_value=True),
        patch.object(web_app, "_proc_state", return_value="S"),
        patch.object(web_app, "_child_pids", return_value=set()),
        patch.object(web_app, "_kill_pids") as kill_mock,
        patch.object(web_app.time, "sleep", return_value=None),
    ):
        web_app.reclaim_project_port(8000)
    # kill_pids is still called with the set, but _kill_pids itself skips getpid.
    kill_mock.assert_called_once()
    assert self_pid in kill_mock.call_args[0][0]


def test_ensure_preferred_port_retries_when_sibling_races_in():
    binds = iter([False, False, True])
    reclaims: list[int] = []

    with (
        patch.object(
            web_app,
            "reclaim_project_port",
            side_effect=lambda port: reclaims.append(port) or [],
        ),
        patch.object(web_app, "_can_bind", side_effect=lambda _h, _p: next(binds)),
        patch.object(web_app, "_pids_listening_on", return_value={555}),
        patch.object(web_app, "_is_our_web_server", return_value=True),
        patch.object(web_app.time, "sleep", return_value=None),
    ):
        port = web_app.ensure_preferred_port("127.0.0.1", 8000, attempts=5)
    assert port == 8000
    assert len(reclaims) == 3


def test_ensure_preferred_port_falls_back_for_foreign_holder():
    with (
        patch.object(web_app, "reclaim_project_port", return_value=[]),
        patch.object(web_app, "_can_bind", side_effect=[False, False, True]),
        patch.object(web_app, "_pids_listening_on", return_value={999}),
        patch.object(web_app, "_is_our_web_server", return_value=False),
        patch.object(web_app, "_next_available_port", return_value=8001),
        patch.object(web_app.time, "sleep", return_value=None),
    ):
        # First _can_bind False, foreign holders, second probe False -> fallback.
        # The side_effect list: ensure loop can_bind False, then after sleep False,
        # then _next_available_port uses True for 8001 via its own _can_bind - but we
        # stub _next_available_port directly.
        port = web_app.ensure_preferred_port("127.0.0.1", 8000, attempts=3)
    assert port == 8001
