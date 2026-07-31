"""Loader for the exploit seed corpus (curated + learned).

Seeds are concrete, known-effective attack shapes used as few-shot exemplars
that the generator MUTATES into novel variants (never copies verbatim).

Curated seeds live in ``generate-tests/corpus/`` named by exact play-category
dot-path (e.g. ``mission.hunt.json`` when present). Broad L1 corpus files are not
loaded for a leaf.

Learned seeds - prompts that demonstrably exploited a target in a prior run -
are persisted by the closed-loop feedback under ``generate-tests/corpus/learned/``
using the same naming. ``load_corpus`` interleaves curated + learned with
per-source caps so feedback seeds are not crowded out by large L1 files.

Breakthrough attempts - untested divergent prompts from stuck runs - are kept
separately under ``generate-tests/corpus/breakthrough/``. They are an "already
tried, do not reproduce" avoid-list (newest-first, recency-capped), surfaced via
:func:`load_breakthrough_seeds` rather than as mutate-these exemplars.
"""
from __future__ import annotations

import json
import hashlib
import os
import shutil
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from playbooks.categories import PLAY_CATEGORY_IDS

from strategies.corpus_seed_quality import (
    dedupe_seeds_newest_first,
    is_near_duplicate,
    seed_dict_usable,
    seed_is_usable,
    seed_text_signature,
)

_CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus"
_LEARNED_DIR = _CORPUS_DIR / "learned"
_BREAKTHROUGH_DIR = _CORPUS_DIR / "breakthrough"
_HISTORY_DIR = _CORPUS_DIR / "history"

CORPUS_STORE_IDS = ("learned", "breakthrough", "history", "curated")
_DIR_STORES = frozenset({"learned", "breakthrough", "history"})

_WRITE_LOCK = threading.Lock()

_MERGED_CAP = 12
_CURATED_MERGE_CAP = 6
_LEARNED_MERGE_CAP = 6
_LEARNED_FILE_CAP = 20
_BREAKTHROUGH_SIMILARITY = 0.88
# v2: identity excludes model_hint_signature - recon model_hints churn was
# forking a new hs1-* tree per run for the same target/playbook.
_SCOPE_VERSION = 2
_SCOPE_LOCAL = threading.local()
_SCOPE_METADATA_KEYS = (
    "version",
    "id",
    "site",
    "component",
    "transport",
    "capability_signature",
    "playbook",
    "objective_hash",
)

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "informational": 4}


def corpus_dir() -> Path:
    return _CORPUS_DIR


def learned_dir() -> Path:
    return _LEARNED_DIR


def breakthrough_dir() -> Path:
    return _BREAKTHROUGH_DIR


def history_dir() -> Path:
    return _HISTORY_DIR


def _stable_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(k): _stable_value(v)
            for k, v in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        return sorted(
            (_stable_value(v) for v in value),
            key=lambda item: json.dumps(item, sort_keys=True, default=str),
        )
    if isinstance(value, bool) or value is None:
        return value
    return str(value).strip().lower()


def build_hunt_scope(context: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Build a stable, target-specific learning scope and its provenance.

    Identity is site/component/transport/capabilities/playbook/objective only.
    Recon ``model_hints`` are intentionally excluded: they vary across runs for
    the same target and previously forked learned/breakthrough/history stores.
    """
    ctx = dict(context or {})
    site = str(ctx.get("site") or os.getenv("GENBOUNTY_SITE") or "").strip().lower()
    component = str(
        ctx.get("component") or os.getenv("GENBOUNTY_COMPONENT") or ""
    ).strip().lower()
    if not site or not component:
        return None

    playbook = str(
        ctx.get("playbook")
        or ctx.get("playbook_id")
        or os.getenv("GENBOUNTY_PLAYBOOK")
        or ""
    ).strip().lower()
    transport = str(ctx.get("transport") or "").strip().lower()
    capabilities = _stable_value(ctx.get("capabilities") or {})
    objective = str(ctx.get("objective") or "").strip()
    objective_hash = str(ctx.get("objective_hash") or "").strip().lower()
    if not objective_hash:
        objective_hash = hashlib.sha256(objective.encode("utf-8")).hexdigest()[:16]
    capability_signature = hashlib.sha256(
        json.dumps(capabilities, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    identity = {
        "site": site,
        "component": component,
        "transport": transport,
        "capability_signature": capability_signature,
        "playbook": playbook,
        "objective_hash": objective_hash,
    }
    scope_id = "hs1-" + hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]
    return {
        "version": _SCOPE_VERSION,
        "id": scope_id,
        **identity,
    }


def set_hunt_scope_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    """Set the current thread's scope, returning the normalized scope."""
    scope = context if context and context.get("id") else build_hunt_scope(context)
    _SCOPE_LOCAL.value = dict(scope) if scope else None
    return _SCOPE_LOCAL.value


def initialize_worker_hunt_scope(
    context: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """Initialize scope inside an executor worker (thread locals are not inherited)."""
    return set_hunt_scope_context(context)


def current_hunt_scope(
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if context is not None:
        return context if context.get("id") else build_hunt_scope(context)
    current = getattr(_SCOPE_LOCAL, "value", None)
    return dict(current) if isinstance(current, dict) else build_hunt_scope()


def hunt_scope_metadata(
    context: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Return the non-sensitive reproducibility fields safe to stamp on artifacts."""
    scope = current_hunt_scope(context)
    if not scope:
        return None
    return {key: scope[key] for key in _SCOPE_METADATA_KEYS if key in scope}


def _scope_id(context: dict[str, Any] | None = None) -> str:
    scope = current_hunt_scope(context)
    return str((scope or {}).get("id") or "")


def _normalize_category(play_category: str) -> str:
    return (play_category or "").strip().lower()


def _is_exact_leaf(play_category: str) -> bool:
    return _normalize_category(play_category) in PLAY_CATEGORY_IDS


def _normalize_seed_text(seed: dict[str, Any]) -> str:
    return " ".join(str(seed.get("seed", "")).strip().lower().split())


_BASE_DIRS = {"learned": _LEARNED_DIR, "breakthrough": _BREAKTHROUGH_DIR}


@lru_cache(maxsize=256)
def _load_file(base: str, stem: str, scope_id: str = "") -> tuple[dict[str, Any], ...]:
    root = _BASE_DIRS.get(base, _CORPUS_DIR)
    path = root / scope_id / f"{stem}.json" if scope_id else root / f"{stem}.json"
    if not path.is_file():
        return ()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    if not isinstance(data, list):
        return ()
    return tuple(s for s in data if isinstance(s, dict))


def invalidate_cache() -> None:
    """Drop cached corpus files so freshly written learned seeds are visible."""
    _load_file.cache_clear()


def _seeds_for_base(
    base: str,
    play_category: str,
    *,
    context: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], ...]:
    pc = _normalize_category(play_category)
    if not _is_exact_leaf(pc):
        return ()
    scope_id = "" if base == "curated" else _scope_id(context)
    if base != "curated" and not scope_id:
        return ()
    return _load_file(base, pc, scope_id)


def _seed_source(seed: dict[str, Any]) -> str:
    return str(seed.get("source", "")).strip().lower()


def _matches_channel(seed: dict[str, Any], channel: str | None) -> bool:
    if not channel:
        return True
    ch = seed.get("channel")
    return not ch or ch == channel


def _collect_unique_seeds(
    base: str,
    play_category: str,
    *,
    seen: set[str],
    skip_breakthrough: bool,
    channel: str | None = None,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for seed in _seeds_for_base(base, play_category, context=context):
        if skip_breakthrough and _seed_source(seed) == "breakthrough":
            continue
        if not seed_dict_usable(seed):
            continue
        if not _matches_channel(seed, channel):
            continue
        key = _normalize_seed_text(seed)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(seed)
    return out


def _interleave(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for i in range(max(len(a), len(b))):
        if i < len(a):
            merged.append(a[i])
        if i < len(b):
            merged.append(b[i])
    return merged


def load_corpus(
    play_category: str,
    channel: str | None = None,
    *,
    include_breakthrough: bool = False,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return seed dicts for a play category (curated + learned, interleaved).

    Curated and learned are collected separately, capped per source, then
    interleaved so proven feedback seeds are not crowded out by large L1 files.
    """
    seen: set[str] = set()
    curated = _collect_unique_seeds(
        "curated", play_category, seen=seen, skip_breakthrough=not include_breakthrough,
        channel=channel,
        context=context,
    )[:_CURATED_MERGE_CAP]
    learned = _collect_unique_seeds(
        "learned", play_category, seen=seen, skip_breakthrough=not include_breakthrough,
        channel=channel,
        context=context,
    )[:_LEARNED_MERGE_CAP]
    return _interleave(curated, learned)[:_MERGED_CAP]


def load_breakthrough_seeds(
    play_category: str,
    channel: str | None = None,
    *,
    context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return the breakthrough avoid-list seeds for a category (newest first)."""
    raw = [
        s
        for s in _seeds_for_base("breakthrough", play_category, context=context)
        if seed_dict_usable(s)
    ]
    if channel:
        raw = [s for s in raw if not s.get("channel") or s.get("channel") == channel]
    return dedupe_seeds_newest_first(
        raw, cap=_LEARNED_FILE_CAP, similarity=_BREAKTHROUGH_SIMILARITY
    )


def _learned_file_path(play_category: str, scope_id: str = "") -> Path:
    root = _LEARNED_DIR / scope_id if scope_id else _LEARNED_DIR
    return root / f"{_normalize_category(play_category)}.json"


def append_learned_seeds(
    play_category: str,
    seeds: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
) -> int:
    """Persist new learned seeds for ``play_category``; return count written."""
    pc = _normalize_category(play_category)
    scope = current_hunt_scope(context)
    scope_id = str((scope or {}).get("id") or "")
    if not _is_exact_leaf(pc) or not seeds or not scope_id:
        return 0

    with _WRITE_LOCK:
        existing = list(_load_file("learned", pc, scope_id))
        seen = {_normalize_seed_text(s) for s in existing}
        seen.update(
            _normalize_seed_text(s)
            for s in _seeds_for_base("curated", pc, context=context)
        )
        existing_sigs = [seed_text_signature(str(s.get("seed") or "")) for s in existing]

        added = 0
        for seed in seeds:
            if not seed_dict_usable(seed):
                continue
            key = _normalize_seed_text(seed)
            sig = seed_text_signature(str(seed.get("seed") or ""))
            if not key or key in seen:
                continue
            if is_near_duplicate(sig, existing_sigs, similarity=_BREAKTHROUGH_SIMILARITY):
                continue
            seen.add(key)
            existing_sigs.append(sig)
            existing.append(
                {
                    **seed,
                    "hunt_scope": scope_id,
                    "scope_provenance": scope,
                }
            )
            added += 1
        if not added:
            return 0

        existing.sort(key=lambda s: _SEVERITY_RANK.get(str(s.get("risk_level", "")).lower(), 5))
        existing = existing[:_LEARNED_FILE_CAP]

        path = _learned_file_path(play_category, scope_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(existing, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        invalidate_cache()
        return added


def _breakthrough_file_path(play_category: str, scope_id: str = "") -> Path:
    root = _BREAKTHROUGH_DIR / scope_id if scope_id else _BREAKTHROUGH_DIR
    return root / f"{_normalize_category(play_category)}.json"


def append_breakthrough_seeds(
    play_category: str,
    seeds: list[dict[str, Any]],
    *,
    context: dict[str, Any] | None = None,
) -> int:
    """Persist breakthrough avoid-list seeds; newest-first with diversity cap."""
    pc = _normalize_category(play_category)
    scope = current_hunt_scope(context)
    scope_id = str((scope or {}).get("id") or "")
    if not _is_exact_leaf(pc) or not seeds or not scope_id:
        return 0

    with _WRITE_LOCK:
        existing = list(_load_file("breakthrough", pc, scope_id))
        seen = {_normalize_seed_text(s) for s in existing}
        existing_sigs = [seed_text_signature(str(s.get("seed") or "")) for s in existing]

        added: list[dict[str, Any]] = []
        for seed in seeds:
            if not seed_dict_usable(seed):
                continue
            key = _normalize_seed_text(seed)
            sig = seed_text_signature(str(seed.get("seed") or ""))
            if not key or key in seen:
                continue
            if is_near_duplicate(sig, existing_sigs, similarity=_BREAKTHROUGH_SIMILARITY):
                continue
            seen.add(key)
            existing_sigs.append(sig)
            added.append(
                {
                    **seed,
                    "hunt_scope": scope_id,
                    "scope_provenance": scope,
                }
            )
        if not added:
            return 0

        merged = dedupe_seeds_newest_first(
            added + existing,
            cap=_LEARNED_FILE_CAP,
            similarity=_BREAKTHROUGH_SIMILARITY,
        )

        path = _breakthrough_file_path(play_category, scope_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(merged, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        invalidate_cache()
        return len(added)


def _store_root(store: str) -> Path | None:
    if store == "learned":
        return learned_dir()
    if store == "breakthrough":
        return breakthrough_dir()
    if store == "history":
        return history_dir()
    if store == "curated":
        return corpus_dir()
    return None


def _iter_files(path: Path) -> list[Path]:
    if not path.is_dir():
        return []
    return sorted(p for p in path.rglob("*") if p.is_file())


def _curated_json_files() -> list[Path]:
    root = corpus_dir()
    if not root.is_dir():
        return []
    return sorted(p for p in root.glob("*.json") if p.is_file())


def _stat_files(files: list[Path]) -> dict[str, Any]:
    total_bytes = 0
    for path in files:
        try:
            total_bytes += path.stat().st_size
        except OSError:
            continue
    return {
        "exists": bool(files),
        "file_count": len(files),
        "bytes": total_bytes,
    }


def corpus_store_stats() -> dict[str, Any]:
    """Return per-store file counts and sizes under ``generate-tests/corpus/``."""
    stores: dict[str, Any] = {}
    for store in CORPUS_STORE_IDS:
        if store == "curated":
            files = _curated_json_files()
            stores[store] = _stat_files(files)
            continue
        root = _store_root(store)
        if root is None:
            stores[store] = {"exists": False, "file_count": 0, "bytes": 0}
            continue
        files = _iter_files(root)
        info = _stat_files(files)
        info["exists"] = root.is_dir()
        stores[store] = info
    return {"stores": stores}


def clear_corpus_stores(stores: list[str] | tuple[str, ...] | None) -> dict[str, Any]:
    """Delete whitelisted corpus stores. Returns removed counts and skipped ids."""
    requested = [str(s).strip().lower() for s in (stores or []) if str(s).strip()]
    allowed = set(CORPUS_STORE_IDS)
    selected = [s for s in requested if s in allowed]
    skipped = sorted({s for s in requested if s not in allowed})
    # Preserve request order, unique.
    seen: set[str] = set()
    ordered: list[str] = []
    for store in selected:
        if store in seen:
            continue
        seen.add(store)
        ordered.append(store)

    removed: dict[str, int] = {}
    with _WRITE_LOCK:
        for store in ordered:
            count = 0
            if store in _DIR_STORES:
                root = _store_root(store)
                if root is not None and root.is_dir():
                    count = len(_iter_files(root))
                    try:
                        shutil.rmtree(root)
                    except OSError:
                        count = 0
                        skipped.append(store)
                        continue
            elif store == "curated":
                for path in _curated_json_files():
                    try:
                        path.unlink()
                        count += 1
                    except OSError:
                        skipped.append(store)
                        break
            if count:
                removed[store] = count
        if removed:
            invalidate_cache()

    return {"removed": removed, "skipped": skipped, "stores": corpus_store_stats()["stores"]}
