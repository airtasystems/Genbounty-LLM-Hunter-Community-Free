"""Cross-generation prompt history: dedup new suites against prior generations.

Independent generations for the same playbook+strategy tend to re-converge on the
same attack families - especially under breakthrough mode, where the loop only
diverges from the *latest* run and swings back onto an earlier run's techniques.
This records a rolling, most-recent-first set of normalized prompt signatures per
``(playbook, strategy)`` so the generator can drop / backfill prompts that
duplicate *any* recent generation, not just other categories in the current run.

The store is independent of the output file, so it survives the common case of
regenerating into the same path (overwrite). Signatures are computed by the caller
(via ``security_common.prompt_signature``) and stored as opaque strings here.

Files live under ``generate-tests/corpus/history/<playbook>.<strategy>.json`` as a
capped list of signature strings (newest first). Scoped files use
``history/<scope-id>/<playbook>.<strategy>.json`` and carry scope provenance.
``GENBOUNTY_GEN_HISTORY=0``
disables both reading and writing.
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path

_HISTORY_DIR = Path(__file__).resolve().parent.parent / "corpus" / "history"

# Serializes read-modify-write: category workers run in parallel, but history is
# written once per suite from the main thread; the lock guards against any future
# concurrent callers clobbering the file.
_WRITE_LOCK = threading.Lock()

# Bound how many signatures persist per (playbook, strategy) so the dedup pass
# stays fast and only the recent generation window influences new runs.
_HISTORY_CAP = 240


def history_enabled() -> bool:
    return True


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _history_path(
    playbook_id: str,
    strategy: str,
    context: dict | None = None,
) -> Path | None:
    try:
        from strategies.corpus_loader import current_hunt_scope
    except ImportError:
        from corpus_loader import current_hunt_scope  # type: ignore
    scope = current_hunt_scope(context)
    scope_id = str((scope or {}).get("id") or "")
    pb = _slug(playbook_id)
    st = _slug(strategy)
    if not pb or not st or not scope_id:
        return None
    return _HISTORY_DIR / scope_id / f"{pb}.{st}.json"


def _read_history_file(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if isinstance(data, dict):
        data = data.get("signatures")
    if isinstance(data, list):
        return [str(s) for s in data if isinstance(s, str) and s]
    return []


def load_history_signatures(
    playbook_id: str,
    strategy: str,
    *,
    context: dict | None = None,
) -> list[str]:
    """Return prior-generation prompt signatures for a (playbook, strategy)."""
    if not history_enabled():
        return []
    path = _history_path(playbook_id, strategy, context)
    return _read_history_file(path)


def append_history_signatures(
    playbook_id: str,
    strategy: str,
    signatures: list[str],
    *,
    context: dict | None = None,
) -> int:
    """Prepend new signatures (newest first), dedupe, cap, and persist.

    Returns the number of new (previously unseen) signatures recorded. No-op when
    disabled or there is nothing new to add.
    """
    if not history_enabled():
        return 0
    path = _history_path(playbook_id, strategy, context)
    if path is None:
        return 0
    fresh = [s for s in signatures if isinstance(s, str) and s]
    if not fresh:
        return 0

    with _WRITE_LOCK:
        existing = load_history_signatures(
            playbook_id, strategy, context=context
        )
        existing_set = set(existing)
        # Unique, order-preserving set of signatures not already recorded.
        added: list[str] = []
        added_set: set[str] = set()
        for sig in fresh:
            if sig in existing_set or sig in added_set:
                continue
            added_set.add(sig)
            added.append(sig)
        if not added:
            return 0
        # Newest first so the cap retains the most recent generation window.
        merged = (added + existing)[:_HISTORY_CAP]

        try:
            from strategies.corpus_loader import current_hunt_scope
        except ImportError:
            from corpus_loader import current_hunt_scope  # type: ignore
        scope = current_hunt_scope(context)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "hunt_scope": str((scope or {}).get("id") or ""),
                    "scope_provenance": scope,
                    "signatures": merged,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return len(added)
