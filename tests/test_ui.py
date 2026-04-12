"""
tests/test_ui.py - Focused tests for preview estimation helpers.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ui import estimate_selected_files, estimate_tokens_for_preview, resolve_pack_focus


class TestUiHelpers(unittest.TestCase):
    def test_resolve_pack_focus_preserves_manual_value(self):
        focus, auto = resolve_pack_focus("custom auth flow", "backend api server", "frontend ui screen")
        self.assertEqual((focus, auto), ("custom auth flow", "backend api server"))

    def test_estimate_selected_files_for_full_uses_total(self):
        self.assertEqual(estimate_selected_files(42, 3, "full", False), 42)

    def test_estimate_selected_files_for_diff_tracks_changes(self):
        self.assertEqual(estimate_selected_files(50, 4, "diff", False), 8)

    def test_estimate_tokens_drop_with_stronger_compression(self):
        full_tokens = estimate_tokens_for_preview(12, "full")
        focused_tokens = estimate_tokens_for_preview(12, "focused")
        self.assertGreater(full_tokens, focused_tokens)


if __name__ == "__main__":
    unittest.main()
