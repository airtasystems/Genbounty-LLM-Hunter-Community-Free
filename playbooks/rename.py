"""Rename a playbook id on disk and relink suites / intel."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from playbooks.registry import normalize_playbook_id
from playbooks.suite_cache import playbook_suite_filename


class PlaybookRenameError(ValueError):
    """Operator-facing rename failure."""


def _playbook_path(root: Path, playbook_id: str) -> Path:
    pid = normalize_playbook_id(playbook_id)
    return root / "playbooks" / f"{pid}.json"


def _relink_suite_files(root: Path, old_id: str, new_id: str) -> list[str]:
    """Rename suite JSON files and stamp playbook_id inside them."""
    old_name = playbook_suite_filename(old_id)
    new_name = playbook_suite_filename(new_id)
    moved: list[str] = []
    if old_name == new_name:
        # Still refresh stamped playbook_id when only underscore/hyphen differs.
        for path in sorted((root / "browser-bot" / "sites").glob(f"*/*/tests/*/{old_name}")):
            if not path.is_file():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            if str(data.get("playbook_id") or "").strip() == new_id:
                continue
            data["playbook_id"] = new_id
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            try:
                moved.append(str(path.relative_to(root)))
            except ValueError:
                moved.append(str(path))
        return moved

    for old_path in sorted((root / "browser-bot" / "sites").glob(f"*/*/tests/*/{old_name}")):
        if not old_path.is_file():
            continue
        new_path = old_path.with_name(new_name)
        if new_path.exists():
            raise PlaybookRenameError(
                f"Suite already exists at {new_path.relative_to(root)}; resolve conflict before renaming"
            )
        try:
            data = json.loads(old_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            data["playbook_id"] = new_id
            new_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.unlink()
        else:
            old_path.rename(new_path)
        try:
            moved.append(str(new_path.relative_to(root)))
        except ValueError:
            moved.append(str(new_path))
    return moved


def _relink_intel_files(root: Path, old_id: str, new_id: str) -> list[str]:
    """Rename intel/{playbook_id}.json across all site/component trees."""
    old_pid = normalize_playbook_id(old_id)
    new_pid = normalize_playbook_id(new_id)
    moved: list[str] = []
    if not old_pid or not new_pid:
        return moved
    for old_path in sorted((root / "browser-bot" / "sites").glob(f"*/*/intel/{old_pid}.json")):
        if not old_path.is_file():
            continue
        new_path = old_path.with_name(f"{new_pid}.json")
        if new_path.exists():
            raise PlaybookRenameError(
                f"Intel already exists at {new_path.relative_to(root)}; resolve conflict before renaming"
            )
        try:
            data = json.loads(old_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            data["playbook_id"] = new_pid
            new_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            old_path.unlink()
        else:
            old_path.rename(new_path)
        try:
            moved.append(str(new_path.relative_to(root)))
        except ValueError:
            moved.append(str(new_path))
    return moved


def rename_playbook(
    old_playbook_id: str,
    new_playbook_id: str,
    root: Path | str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Rename playbook JSON and relink suites + intel. Returns a result summary."""
    root_path = Path(root)
    old_id = normalize_playbook_id(old_playbook_id)
    new_id = normalize_playbook_id(new_playbook_id)
    if not old_id:
        raise PlaybookRenameError("Current playbook_id is required")
    if not new_id:
        raise PlaybookRenameError("New playbook_id is required")
    if old_id.startswith("_") or new_id.startswith("_"):
        raise PlaybookRenameError("Reference playbooks (underscore prefix) cannot be renamed")
    if old_id == new_id:
        raise PlaybookRenameError("New playbook_id must differ from the current id")

    old_path = _playbook_path(root_path, old_id)
    new_path = _playbook_path(root_path, new_id)
    if not old_path.is_file():
        raise PlaybookRenameError(f"Playbook not found: {old_id}")
    if new_path.exists():
        raise PlaybookRenameError(f"Playbook already exists: {new_id}")

    if data is None:
        try:
            payload = json.loads(old_path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlaybookRenameError(f"Invalid playbook JSON: {exc}") from exc
    else:
        if not isinstance(data, dict):
            raise PlaybookRenameError("Playbook data must be a JSON object")
        payload = json.loads(json.dumps(data))

    payload.pop("_comment", None)
    payload["playbook_id"] = new_id
    if not str(payload.get("playbook") or "").strip():
        payload["playbook"] = new_id.replace("_", " ").title()
    schema = payload.get("required_output_schema")
    if isinstance(schema, dict) and schema.get("playbook") is not None:
        schema["playbook"] = payload["playbook"]

    # Validate after id rewrite. Prefer the real project generate-tests/ on sys.path
    # (root_path may be a temp workspace that only has playbooks/).
    import sys
    from pathlib import Path as _Path

    _project_root = _Path(__file__).resolve().parent.parent
    for candidate in (_project_root / "generate-tests", _project_root, root_path / "generate-tests", root_path):
        text = str(candidate)
        if candidate.is_dir() and text not in sys.path:
            sys.path.insert(0, text)
    from playbook_generator import validate_playbook
    from playbooks.playbook_config import canonicalize_playbook_config_storage

    canonicalize_playbook_config_storage(payload)
    errors = validate_playbook(payload, new_id)
    if errors:
        raise PlaybookRenameError("Playbook failed validation: " + "; ".join(errors[:6]))

    # Relink side artifacts before deleting the old playbook file so a mid-flight
    # failure leaves the original play intact.
    suites = _relink_suite_files(root_path, old_id, new_id)
    intel = _relink_intel_files(root_path, old_id, new_id)

    playbooks_dir = root_path / "playbooks"
    playbooks_dir.mkdir(parents=True, exist_ok=True)
    new_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old_path.unlink()

    return {
        "ok": True,
        "old_playbook_id": old_id,
        "playbook_id": new_id,
        "path": str(new_path.relative_to(root_path)),
        "moved_suites": suites,
        "moved_intel": intel,
    }
