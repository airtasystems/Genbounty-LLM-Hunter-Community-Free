"""Startup port bind helpers and reclaim of prior Genbounty web/app.py holders."""

from __future__ import annotations

import os
import re as _re
import signal
import socket
import subprocess
import time
from pathlib import Path

from web.paths import ROOT


def _can_bind(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def _next_available_port(host: str, preferred_port: int) -> int:
    port = preferred_port
    while True:
        if _can_bind(host, port):
            return port
        port += 1


def _port_holder_hint(port: int) -> str:
    """Best-effort hint for who is holding a TCP port (Linux/ss)."""
    try:
        out = subprocess.check_output(
            ["ss", "-ltnp", f"sport = :{port}"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        return (
            f"Find/kill the holder with: ss -ltnp | grep :{port} "
            f"&& kill -9 <pid>"
        )
    lines = [ln.strip() for ln in out.splitlines() if ln.strip() and "pid=" in ln]
    if not lines:
        return (
            f"Find/kill the holder with: ss -ltnp | grep :{port} "
            f"&& kill -9 <pid>"
        )
    return "Holder: " + " | ".join(lines[:2])


def _proc_cmdline(pid: int) -> str:
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return ""
    return raw.replace(b"\0", b" ").decode("utf-8", "replace").strip()


def _proc_cwd(pid: int) -> Path | None:
    try:
        return Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return None


def _proc_state(pid: int) -> str:
    try:
        # /proc/<pid>/stat: pid (comm) state ...
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
        close = text.rfind(")")
        if close < 0:
            return ""
        parts = text[close + 1 :].split()
        return parts[0] if parts else ""
    except OSError:
        return ""


def _is_our_web_server(pid: int) -> bool:
    """True when pid looks like this checkout's web/app.py (incl. stopped orphans)."""
    if pid <= 0 or pid == os.getpid():
        return False
    cmd = _proc_cmdline(pid)
    if "web/app.py" not in cmd and "web\\app.py" not in cmd:
        return False
    root = ROOT.resolve()
    if str(root) in cmd:
        return True
    cwd = _proc_cwd(pid)
    return cwd is not None and cwd == root


def _child_pids(pid: int) -> set[int]:
    kids: set[int] = set()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return kids
    for entry in entries:
        if not entry.name.isdigit():
            continue
        child = int(entry.name)
        try:
            status = (entry / "status").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in status.splitlines():
            if line.startswith("PPid:"):
                try:
                    ppid = int(line.split()[1])
                except (IndexError, ValueError):
                    break
                if ppid == pid:
                    kids.add(child)
                    kids |= _child_pids(child)
                break
    return kids


def _pids_listening_on(port: int) -> set[int]:
    pids: set[int] = set()
    try:
        out = subprocess.check_output(
            ["ss", "-ltnp", f"sport = :{port}"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except Exception:
        return pids
    for match in _re.finditer(r"pid=(\d+)", out):
        try:
            pids.add(int(match.group(1)))
        except ValueError:
            continue
    return pids


def _all_our_web_server_pids() -> set[int]:
    found: set[int] = set()
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if _is_our_web_server(pid):
            found.add(pid)
    return found


def _kill_pids(pids: set[int]) -> None:
    # SIGKILL so STOPPED (Ctrl+Z / SIGTSTP) leftovers die immediately.
    for pid in sorted(pids):
        if pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            print(f"Could not kill pid {pid} (permission denied).", flush=True)


def reclaim_project_port(port: int) -> list[int]:
    """Kill prior Genbounty web/app.py holders (and stopped orphans) for this checkout.

    Returns the pids that were targeted. Safe to call on every startup so Cancel /
    restart never leaves :8000 owned by a dead or duplicate UI process.
    """
    ours: set[int] = set()
    for pid in _pids_listening_on(port):
        if _is_our_web_server(pid):
            ours.add(pid)
    for pid in _all_our_web_server_pids():
        # Ctrl+Z / SIGTSTP leftovers stay in T and ignore plain kill until CONT.
        if _proc_state(pid) in {"T", "t"}:
            ours.add(pid)
    if not ours:
        return []
    to_kill: set[int] = set()
    for pid in ours:
        to_kill.add(pid)
        to_kill |= _child_pids(pid)
    print(
        f"Reclaiming :{port} from prior Genbounty server pid(s): "
        f"{', '.join(str(p) for p in sorted(to_kill))}",
        flush=True,
    )
    _kill_pids(to_kill)
    # Give the kernel a moment to release the listen socket.
    for _ in range(40):
        if not (_pids_listening_on(port) & to_kill):
            break
        time.sleep(0.05)
    return sorted(to_kill)


def ensure_preferred_port(host: str, preferred_port: int, *, attempts: int = 12) -> int:
    """Reclaim+bind the preferred port, retrying if another Genbounty UI races in.

    Only falls back to the next free port when a non-Genbounty process still holds
    the preferred port after retries.
    """
    for _ in range(max(1, attempts)):
        reclaim_project_port(preferred_port)
        if _can_bind(host, preferred_port):
            return preferred_port
        holders = _pids_listening_on(preferred_port)
        ours = {pid for pid in holders if _is_our_web_server(pid)}
        if ours:
            # Another Genbounty UI bound between reclaim and bind - loop again.
            time.sleep(0.1)
            continue
        if holders:
            # Foreign holder (or ss lag). Brief wait, then one more bind probe.
            time.sleep(0.2)
            if _can_bind(host, preferred_port):
                return preferred_port
            break
        # No LISTEN pid but bind failed (slow close / race) - retry.
        time.sleep(0.1)
    return _next_available_port(host, preferred_port)

