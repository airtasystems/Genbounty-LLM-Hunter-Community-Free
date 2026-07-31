"""Tests for project cache cleanup."""

from __future__ import annotations

import unittest
from pathlib import Path

from pipeline.cleanup import (
    clear_project_dev_caches,
    clear_project_pycache,
    iter_project_cache_dirs,
)


class CleanupCachesTest(unittest.TestCase):
    def test_clears_pycache_and_pytest_cache_skips_venv(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pkg" / "__pycache__").mkdir(parents=True)
            (root / "pkg" / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
            (root / "tests" / ".pytest_cache").mkdir(parents=True)
            (root / "tests" / ".pytest_cache" / "v").write_text("1", encoding="utf-8")
            (root / "airta-venv" / "lib" / "__pycache__").mkdir(parents=True)
            (root / "airta-venv" / "lib" / "__pycache__" / "keep.pyc").write_text(
                "k", encoding="utf-8"
            )
            (root / ".ruff_cache").mkdir()

            found = {p.name for p in iter_project_cache_dirs(root)}
            self.assertIn("__pycache__", found)
            self.assertIn(".pytest_cache", found)
            self.assertIn(".ruff_cache", found)

            counts = clear_project_dev_caches(root)
            self.assertEqual(counts.get("__pycache__"), 1)
            self.assertEqual(counts.get(".pytest_cache"), 1)
            self.assertEqual(counts.get(".ruff_cache"), 1)
            self.assertFalse((root / "pkg" / "__pycache__").exists())
            self.assertFalse((root / "tests" / ".pytest_cache").exists())
            self.assertTrue((root / "airta-venv" / "lib" / "__pycache__").exists())

    def test_clear_project_pycache_only_bytecode(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a" / "__pycache__").mkdir(parents=True)
            (root / ".pytest_cache").mkdir()
            n = clear_project_pycache(root)
            self.assertEqual(n, 1)
            self.assertFalse((root / "a" / "__pycache__").exists())
            self.assertTrue((root / ".pytest_cache").exists())


if __name__ == "__main__":
    unittest.main()
