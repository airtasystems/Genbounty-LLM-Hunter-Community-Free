"""Repository-owned playbooks conform to the strict leaf data contract."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_GEN = _ROOT / "generate-tests"
for path in (str(_ROOT), str(_GEN)):
    if path not in sys.path:
        sys.path.insert(0, path)

from playbook_generator import validate_playbook  # noqa: E402
from playbooks.category_catalog import CAPABILITY_FAMILIES, LEAF_CATALOG  # noqa: E402


def _shipped_playbooks() -> list[Path]:
    paths: list[Path] = []
    for path in sorted((_ROOT / "playbooks").glob("**/*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("playbook_id"):
            paths.append(path)
    return paths


def test_shipped_playbooks_use_exact_leaf_metadata_and_scoped_oracles():
    assert _shipped_playbooks()
    for path in _shipped_playbooks():
        data = json.loads(path.read_text(encoding="utf-8"))
        playbook_id = str(data.get("playbook_id") or "")
        assert validate_playbook(data, playbook_id) == [], path

        leaf = str(data.get("play_category") or "")
        assert leaf in LEAF_CATALOG, path
        family = CAPABILITY_FAMILIES[LEAF_CATALOG[leaf].capability_family]
        expected = {
            "required_capabilities": list(family.required),
            "optional_capabilities": list(family.optional),
            "capability_profile": family.profile,
            "category_vectors": list(family.vectors),
        }

        categories = data["categories"]
        oracles = data["playbook_config"]["assessment"]["oracles"]
        for category in categories:
            assert "vectors_to_try" not in category, path
            assert "file_vectors_to_try" not in category, path
            for key, value in expected.items():
                got = category.get(key)
                # Shipped JSON may omit empty capability/vector/profile fields.
                if got is None and value in ([], ""):
                    got = value
                assert got == value, (path, category["id"], key)

            category_id = category["id"]
            scoped = [
                oracle
                for oracle in oracles
                if oracle.get("type") == "semantic_rubric"
                and oracle.get("category_ids") == [category_id]
            ]
            assert scoped, (path, category_id)
            rubric_text = "\n".join(str(oracle.get("rubric") or "") for oracle in scoped)
            for condition in category["attack_triggers"]["exploited_if"]:
                assert condition in rubric_text, (path, category_id, condition)
