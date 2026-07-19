"""Unit tests for profile_service — safe/unsafe profile queries."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from aisc.application.profile_service import (
    run_profile_list,
    run_profile_show,
    ProfileListResult,
    ProfileShowResult,
)


class TestProfileList(unittest.TestCase):
    def test_returns_both_profiles(self):
        result = run_profile_list()
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(len(result.data["profiles"]), 2)
        names = [p["name"] for p in result.data["profiles"]]
        self.assertIn("safe", names)
        self.assertIn("unsafe", names)

    def test_safe_profile(self):
        result = run_profile_list()
        safe = [p for p in result.data["profiles"] if p["name"] == "safe"][0]
        self.assertFalse(safe["dangerously_skip_permissions"])
        self.assertIn("description", safe)

    def test_unsafe_profile(self):
        result = run_profile_list()
        unsafe = [p for p in result.data["profiles"] if p["name"] == "unsafe"][0]
        self.assertTrue(unsafe["dangerously_skip_permissions"])


class TestProfileShow(unittest.TestCase):
    def test_show_safe(self):
        result = run_profile_show("safe")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["name"], "safe")
        self.assertFalse(result.data["dangerously_skip_permissions"])

    def test_show_unsafe(self):
        result = run_profile_show("unsafe")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.data["name"], "unsafe")
        self.assertTrue(result.data["dangerously_skip_permissions"])

    def test_show_unknown(self):
        result = run_profile_show("nonexistent")
        self.assertEqual(result.exit_code, 1)
        self.assertIn("not found", result.error_message)

    def test_show_returns_copy(self):
        """Each call returns independent dicts."""
        r1 = run_profile_show("safe")
        r2 = run_profile_show("safe")
        r1.data["modified"] = True
        self.assertNotIn("modified", r2.data)


if __name__ == "__main__":
    unittest.main()
