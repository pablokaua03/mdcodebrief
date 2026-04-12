"""
tests/test_context_engine.py - Focused tests for analysis heuristics.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

TEST_TMP_ROOT = Path(__file__).parent / ".tmp"
TEST_TMP_ROOT.mkdir(exist_ok=True)

from context_engine import ExportConfig, build_analysis, build_relationship_map, build_task_prompt, classify_file, extract_relevant_excerpt, make_file_insight, summarize_file, test_relation_score
from scanner import build_tree
from ui import resolve_pack_focus


class TestAnalysisHeuristics(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=TEST_TMP_ROOT))

    def tearDown(self):
        import shutil

        shutil.rmtree(self.tmp, ignore_errors=True)

    def _insight(self, relpath: str, content: str):
        path = self.tmp / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        item = make_file_insight(self.tmp, path)
        item.tags.update(classify_file(item))
        return item

    def test_markdown_docs_stay_as_docs(self):
        item = self._insight("README.pt-BR.md", "# Contexta\n\nFerramenta desktop.\n")
        summary = summarize_file(item, {})
        self.assertIn("docs", item.tags)
        self.assertIn("project", summary.lower())
        self.assertNotIn("traverses", summary.lower())

    def test_test_package_init_gets_small_summary(self):
        item = self._insight("tests/__init__.py", "# tests package\n")
        summary = summarize_file(item, {})
        self.assertIn("init", item.tags)
        self.assertIn("tests package", summary.lower())
        self.assertNotIn("coverage", summary.lower())

    def test_embedded_asset_excerpt_omits_blob(self):
        blob = "A" * 180
        item = self._insight(
            "brand_assets.py",
            '\n'.join([
                '"""Embedded brand assets for Contexta."""',
                "",
                "ICON_PNG_B64 = (",
                f'    "{blob}"',
                f'    "{blob}"',
                f'    "{blob}"',
                f'    "{blob}"',
                f'    "{blob}"',
                f'    "{blob}"',
                f'    "{blob}"',
                f'    "{blob}"',
                ")",
            ]),
        )
        excerpt, reason = extract_relevant_excerpt(item, "icon brand")
        self.assertIn("embedded_asset", item.tags)
        self.assertIn("omitted", reason.lower())
        self.assertIn("<embedded asset data omitted>", excerpt)
        self.assertNotIn(blob, excerpt)

    def test_markdown_with_dense_line_is_not_classified_as_embedded_asset(self):
        long_line = "A" * 180
        item = self._insight(
            "CHANGELOG.md",
            "\n".join([
                "# Changelog",
                "",
                "## [1.4.0] - 2026-04-11",
                long_line,
            ]),
        )
        summary = summarize_file(item, {})
        self.assertIn("docs", item.tags)
        self.assertNotIn("embedded_asset", item.tags)
        self.assertNotIn("assets", item.tags)
        self.assertIn("releases", summary.lower())

    def test_renderer_summary_wins_over_analysis_overlap(self):
        item = self._insight(
            "renderer.py",
            "\n".join([
                "from context_engine import build_analysis",
                "",
                "def generate_markdown():",
                "    return build_analysis",
            ]),
        )
        summary = summarize_file(item, {})
        self.assertIn("renderer", item.tags)
        self.assertEqual(summary, "Formats the selected analysis into Markdown sections and token guidance.")

    def test_context_engine_keeps_analysis_summary(self):
        item = self._insight(
            "context_engine.py",
            "\n".join([
                "class ProjectAnalysis:",
                "    pass",
                "",
                "def build_analysis():",
                "    return ProjectAnalysis",
                "",
                "example = 'def generate_markdown('",
            ]),
        )
        summary = summarize_file(item, {})
        self.assertIn("analysis", item.tags)
        self.assertNotIn("renderer", item.tags)
        self.assertEqual(summary, "Scores files, infers relationships, and chooses which context to export.")

    def test_theme_summary_wins_over_generic_ui_summary(self):
        item = self._insight(
            "theme.py",
            "\n".join([
                "import tkinter as tk",
                "",
                "def apply_theme(theme):",
                "    return theme",
                "",
                "def toggle_theme():",
                "    return True",
            ]),
        )
        summary = summarize_file(item, {})
        self.assertIn("theme", item.tags)
        self.assertNotIn("ui", item.tags)
        self.assertEqual(summary, "Defines theme palettes and repaint helpers for dark/light interface rendering.")

    def test_support_file_summaries_are_specific(self):
        requirements = self._insight("requirements.txt", "pyinstaller\n")
        build_bat = self._insight("build.bat", "@echo off\npy -m PyInstaller contexta.py\n")
        build_sh = self._insight("build.sh", "#!/usr/bin/env bash\npyinstaller contexta.py\n")
        self.assertIn("dependency expectations", summarize_file(requirements, {}).lower())
        self.assertIn("windows executable packaging", summarize_file(build_bat, {}).lower())
        self.assertIn("unix-like executable packaging", summarize_file(build_sh, {}).lower())

    def test_mdcodebrief_summary_mentions_compatibility_shim(self):
        item = self._insight("mdcodebrief.py", "from contexta import main\n\nmain()\n")
        summary = summarize_file(item, {})
        self.assertIn("compatibility shim", summary.lower())
        self.assertIn("contexta.main()", summary)

    def test_relationship_map_does_not_claim_unrelated_test_covers_ui(self):
        ui_item = self._insight("ui.py", "def render_ui():\n    return True\n")
        test_item = self._insight(
            "tests/test_context_engine.py",
            "\n".join([
                "from ui import render_ui",
                "",
                "def test_pack_focus_switch():",
                "    assert render_ui() is True",
            ]),
        )
        relationships = build_relationship_map([ui_item, test_item], {ui_item.relpath.as_posix(): {test_item.relpath.as_posix()}})
        self.assertFalse(any("likely covers `ui.py`" in line for line in relationships))

    def test_test_files_do_not_accumulate_module_tags_from_snippets(self):
        item = self._insight(
            "tests/test_context_engine.py",
            "\n".join([
                "def test_classifier_noise():",
                "    sample = 'def generate_markdown('",
                "    sample2 = 'class ProjectAnalysis'",
                "    sample3 = 'toggle_theme and apply_theme'",
            ]),
        )
        self.assertEqual(item.tags, {"test"})

    def test_normal_source_excerpt_keeps_dense_import_lines(self):
        item = self._insight(
            "renderer.py",
            "from context_engine import APP_NAME, AI_PROFILE_OPTIONS, COMPRESSION_OPTIONS, CONTEXT_MODE_OPTIONS, PACK_OPTIONS, TASK_PROFILE_OPTIONS, ExportConfig, build_analysis, extract_relevant_excerpt, extract_signatures\n",
        )
        excerpt, reason = extract_relevant_excerpt(item, "")
        self.assertIn("from context_engine import", excerpt)
        self.assertNotIn("<embedded blob omitted>", excerpt)
        self.assertNotIn("omitted", reason.lower())

    def test_related_test_detection_accepts_import_plus_symbol_signal(self):
        item = self._insight(
            "scanner.py",
            "\n".join([
                "def build_tree():",
                "    return {}",
                "",
                "def read_file_safe(path):",
                "    return '', False, 0",
            ]),
        )
        candidate = self._insight(
            "tests/test_scanner_behavior.py",
            "\n".join([
                "from scanner import build_tree, read_file_safe",
                "",
                "def test_tree_scan():",
                "    assert build_tree() == {}",
                "    assert read_file_safe('x')[1] is False",
            ]),
        )
        self.assertGreaterEqual(test_relation_score(item, candidate), 3)

    def test_summary_lists_only_selected_tests(self):
        (self.tmp / "contexta.py").write_text("__name__ = '__main__'\n", encoding="utf-8")
        (self.tmp / "context_engine.py").write_text("class ProjectAnalysis:\n    pass\n", encoding="utf-8")
        (self.tmp / "renderer.py").write_text("def generate_markdown():\n    return ''\n", encoding="utf-8")
        (self.tmp / "scanner.py").write_text("def build_tree():\n    return {}\n", encoding="utf-8")
        for index in range(12):
            (self.tmp / f"module_{index}.py").write_text(f"def helper_{index}():\n    return {index}\n", encoding="utf-8")
        tests_dir = self.tmp / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_context_engine.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
        (tests_dir / "test_renderer.py").write_text("def test_b():\n    assert True\n", encoding="utf-8")
        (tests_dir / "test_scanner.py").write_text("def test_c():\n    assert True\n", encoding="utf-8")
        (tests_dir / "test_utils.py").write_text("def test_d():\n    assert True\n", encoding="utf-8")

        tree = build_tree(self.tmp, False, False, lambda *_args, **_kwargs: None, [0], [], self.tmp)
        analysis = build_analysis(
            self.tmp,
            tree,
            [],
            ExportConfig(context_mode="feature", focus_query="context_engine renderer scanner"),
            lambda *_args, **_kwargs: None,
        )
        summary_blob = "\n".join(analysis.summary_lines)

        self.assertIn("test_context_engine.py", summary_blob)
        self.assertIn("test_renderer.py", summary_blob)
        self.assertNotIn("test_utils.py", summary_blob)

    def test_diff_code_review_selection_stays_surgical(self):
        (self.tmp / "renderer.py").write_text("from context_engine import build_analysis\n\ndef generate_markdown():\n    return build_analysis()\n", encoding="utf-8")
        (self.tmp / "context_engine.py").write_text("class ProjectAnalysis:\n    pass\n\ndef build_analysis():\n    return ProjectAnalysis\n", encoding="utf-8")
        (self.tmp / "ui.py").write_text("def launch_ui():\n    return True\n", encoding="utf-8")
        (self.tmp / "README.md").write_text("# Contexta\n", encoding="utf-8")
        tests_dir = self.tmp / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_renderer.py").write_text("from renderer import generate_markdown\n\ndef test_render():\n    assert generate_markdown\n", encoding="utf-8")
        for index in range(15):
            (self.tmp / f"module_{index}.py").write_text(f"def helper_{index}():\n    return {index}\n", encoding="utf-8")

        tree = build_tree(self.tmp, False, False, lambda *_args, **_kwargs: None, [0], [], self.tmp)
        analysis = build_analysis(
            self.tmp,
            tree,
            [self.tmp / "renderer.py"],
            ExportConfig(context_mode="diff", task_profile="code_review"),
            lambda *_args, **_kwargs: None,
        )

        self.assertLessEqual(len(analysis.selected_files), 12)
        self.assertIn("renderer.py", [item.relpath.as_posix() for item in analysis.selected_files])
        self.assertNotIn("README.md", [item.relpath.as_posix() for item in analysis.selected_files])

    def test_onboarding_selection_stays_compact(self):
        (self.tmp / "contexta.py").write_text("__name__ = '__main__'\n", encoding="utf-8")
        (self.tmp / "ui.py").write_text("import tkinter as tk\n", encoding="utf-8")
        (self.tmp / "cli.py").write_text("import argparse\n", encoding="utf-8")
        (self.tmp / "renderer.py").write_text("def generate_markdown():\n    return ''\n", encoding="utf-8")
        (self.tmp / "context_engine.py").write_text("class ProjectAnalysis:\n    pass\n\ndef build_analysis():\n    return ProjectAnalysis\n", encoding="utf-8")
        (self.tmp / "scanner.py").write_text("def build_tree():\n    return {}\n", encoding="utf-8")
        (self.tmp / "README.md").write_text("# Contexta\n", encoding="utf-8")
        tests_dir = self.tmp / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_ui.py").write_text("from ui import tk\n\ndef test_ui_boot():\n    assert tk\n", encoding="utf-8")
        for index in range(20):
            (self.tmp / f"module_{index}.py").write_text(f"def helper_{index}():\n    return {index}\n", encoding="utf-8")

        tree = build_tree(self.tmp, False, False, lambda *_args, **_kwargs: None, [0], [], self.tmp)
        analysis = build_analysis(
            self.tmp,
            tree,
            [],
            ExportConfig(context_mode="onboarding", task_profile="explain_project"),
            lambda *_args, **_kwargs: None,
        )
        self.assertLessEqual(len(analysis.selected_files), 12)
        relpaths = [item.relpath.as_posix() for item in analysis.selected_files]
        self.assertIn("README.md", relpaths)
        self.assertLessEqual(sum(1 for path in relpaths if path.startswith("tests/")), 2)

    def test_task_prompt_stays_task_focused_without_model_guidance(self):
        prompt = build_task_prompt(Path("demo"), ExportConfig(task_profile="code_review", ai_profile="claude"))
        self.assertIn("Prioritize correctness risks", prompt)
        self.assertNotIn("Usually works well", prompt)

    def test_write_tests_selection_brings_existing_tests(self):
        (self.tmp / "scanner.py").write_text(
            "\n".join([
                "def build_tree():",
                "    return {}",
                "",
                "def read_file_safe(path):",
                "    return '', False, 0",
            ]),
            encoding="utf-8",
        )
        tests_dir = self.tmp / "tests"
        tests_dir.mkdir(exist_ok=True)
        (tests_dir / "test_scanner.py").write_text(
            "\n".join([
                "from scanner import build_tree, read_file_safe",
                "",
                "def test_tree():",
                "    assert build_tree() == {}",
                "    assert read_file_safe('x')[1] is False",
            ]),
            encoding="utf-8",
        )
        tree = build_tree(self.tmp, False, False, lambda *_args, **_kwargs: None, [0], [], self.tmp)
        analysis = build_analysis(
            self.tmp,
            tree,
            [],
            ExportConfig(task_profile="write_tests"),
            lambda *_args, **_kwargs: None,
        )
        relpaths = [item.relpath.as_posix() for item in analysis.selected_files]
        self.assertIn("scanner.py", relpaths)
        self.assertIn("tests/test_scanner.py", relpaths)

    def test_dead_code_selection_prefers_low_signal_files(self):
        (self.tmp / "contexta.py").write_text("__name__ = '__main__'\n", encoding="utf-8")
        (self.tmp / "utils.py").write_text("def helper():\n    return True\n", encoding="utf-8")
        (self.tmp / "orphan_helper.py").write_text("def orphan():\n    return 1\n", encoding="utf-8")
        tree = build_tree(self.tmp, False, False, lambda *_args, **_kwargs: None, [0], [], self.tmp)
        analysis = build_analysis(
            self.tmp,
            tree,
            [],
            ExportConfig(task_profile="find_dead_code"),
            lambda *_args, **_kwargs: None,
        )
        relpaths = [item.relpath.as_posix() for item in analysis.selected_files]
        self.assertIn("orphan_helper.py", relpaths)

    def test_pack_focus_switch_replaces_previous_auto_value(self):
        focus, auto = resolve_pack_focus("", "", "backend api server")
        self.assertEqual((focus, auto), ("backend api server", "backend api server"))

        focus, auto = resolve_pack_focus(focus, auto, "frontend ui screen")
        self.assertEqual((focus, auto), ("frontend ui screen", "frontend ui screen"))

    def test_pack_focus_switch_preserves_manual_value(self):
        focus, auto = resolve_pack_focus("custom auth flow", "backend api server", "frontend ui screen")
        self.assertEqual((focus, auto), ("custom auth flow", "backend api server"))


if __name__ == "__main__":
    unittest.main()
