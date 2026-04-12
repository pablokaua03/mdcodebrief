"""
renderer.py - Context pack rendering and token estimation for Contexta.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from context_engine import (
    APP_NAME,
    AI_PROFILE_OPTIONS,
    COMPRESSION_OPTIONS,
    CONTEXT_MODE_OPTIONS,
    MODEL_PROMPT_GUIDANCE,
    PACK_OPTIONS,
    TASK_PROFILE_OPTIONS,
    ExportConfig,
    build_analysis,
    extract_relevant_excerpt,
    extract_signatures,
)
from scanner import build_diff_tree, build_tree, count_files, get_git_changed_files, load_gitignore_patterns

__version__ = "1.4.0"


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def token_label(n: int) -> str:
    if n < 8_000:
        hint = "roughly fits most chat and coding models"
    elif n < 32_000:
        hint = "roughly in range for ChatGPT-class chats, Claude Sonnet, Gemini Flash, and similar tools"
    elif n < 128_000:
        hint = "roughly in range for larger-context sessions; latency and reasoning effort can vary a lot"
    else:
        hint = "very large pack; prefer long-context workflows or a tighter export"
    return f"~{n/1000:.1f}k tokens (rough estimate: {hint})"


def render_tree_ascii(node: dict, prefix: str = "", is_root: bool = True) -> str:
    lines: list[str] = []

    if is_root:
        lines.append(f"📦 {node['name']}/")
        child_prefix = ""
    else:
        lines.append(f"{prefix}📁 {node['name']}/")
        child_prefix = prefix.replace("├── ", "│   ").replace("└── ", "    ")

    for i, item in enumerate(node["dirs"]):
        connector = "├── " if i < len(node["dirs"]) - 1 or node["files"] else "└── "
        lines.append(render_tree_ascii(item, child_prefix + connector, False))

    for i, file_item in enumerate(node["files"]):
        connector = "└── " if i == len(node["files"]) - 1 else "├── "
        lines.append(f"{child_prefix}{connector}📄 {file_item['name']}")

    return "\n".join(lines)


def show_score_details(config: ExportConfig) -> bool:
    return config.context_mode in {"debug", "refactor"} or config.task_profile in {"ai_handoff", "code_review", "refactor_request"}


def refine_onboarding_excerpt_reason(reason: str, item) -> str:
    if "embedded asset" in reason.lower():
        return reason
    if "entrypoint" in item.tags:
        return "Guided onboarding excerpt showing the opening entry flow and the lines most useful for orientation."
    if "docs" in item.tags:
        return "Guided onboarding excerpt showing the opening documentation lines worth reading first."
    if "test" in item.tags:
        return "Guided onboarding excerpt showing the test shape and the behavior it validates."
    if reason.startswith("Focused excerpt based on matching symbols"):
        return "Guided onboarding excerpt centered on the main symbols that explain this file's role."
    if reason.startswith("Focused excerpt based on keywords"):
        return "Guided onboarding excerpt centered on the lines that best explain this file's purpose."
    return "Guided onboarding excerpt showing the opening structure you would read first."


def render_file_section(item, config: ExportConfig, include_score_details: bool = False) -> str:
    rel = item.relpath.as_posix()
    tags = ", ".join(sorted(item.tags)) if item.tags else "general"
    size_label = f"{item.line_count} lines"
    if item.truncated:
        size_label = f"{item.line_count} total lines ({item.rendered_line_count} exported)"
    reason_label = ", ".join(item.selection_reasons) if getattr(item, "selection_reasons", None) else "selected by pack heuristics"
    parts = [
        f"### 📄 `{rel}`",
        f"- Role: {item.summary}",
        f"- Selected because: {reason_label}",
        f"- Signals: `{tags}`",
        f"- Size: {size_label}",
    ]
    if include_score_details and getattr(item, "score_breakdown", None):
        parts.append(f"- Score breakdown: {'; '.join(item.score_breakdown[:6])}")

    signatures = extract_signatures(item)
    focus_query = config.focus_query or config.system_prompt

    if config.context_mode == "onboarding":
        excerpt_lines = 28 if "entrypoint" in item.tags or item.score >= 9 else 18
        excerpt, reason = extract_relevant_excerpt(item, focus_query, excerpt_lines)
        if signatures:
            parts.append("\n```text")
            parts.extend(signatures[:5])
            parts.append("```")
        parts.append(f"\n> {refine_onboarding_excerpt_reason(reason, item)}")
        parts.append(f"\n```{item.lang or 'text'}\n{excerpt}\n```")
        return "\n".join(parts) + "\n"

    if "embedded_asset" in item.tags:
        excerpt, reason = extract_relevant_excerpt(item, focus_query, 24)
        parts.append(f"\n> {reason}")
        parts.append(f"\n```{item.lang or 'text'}\n{excerpt}\n```")
        return "\n".join(parts) + "\n"

    if config.compression == "signatures":
        if signatures:
            parts.append("\n```text")
            parts.extend(signatures)
            parts.append("```")
        else:
            excerpt, reason = extract_relevant_excerpt(item, focus_query, 40)
            parts.append(f"\n> {reason}")
            parts.append(f"\n```{item.lang or 'text'}\n{excerpt}\n```")
        return "\n".join(parts) + "\n"

    if config.compression == "focused":
        if item.matched_focus or item.score >= 9 or "entrypoint" in item.tags:
            excerpt, reason = extract_relevant_excerpt(item, focus_query, 80)
            if signatures:
                parts.append("\n```text")
                parts.extend(signatures[:10])
                parts.append("```")
            parts.append(f"\n> {reason}")
            parts.append(f"\n```{item.lang or 'text'}\n{excerpt}\n```")
        elif signatures:
            parts.append("\n```text")
            parts.extend(signatures[:10])
            parts.append("```")
        else:
            excerpt, reason = extract_relevant_excerpt(item, focus_query, 30)
            parts.append(f"\n> {reason}")
            parts.append(f"\n```{item.lang or 'text'}\n{excerpt}\n```")
        return "\n".join(parts) + "\n"

    if config.compression == "balanced":
        if item.line_count <= 180 or item.score >= 9:
            body = item.content
            if item.truncated:
                parts.append(f"\n> File has {item.line_count} total lines; exported the first {item.rendered_line_count} lines.")
            parts.append(f"\n```{item.lang or 'text'}\n{body}\n```")
        else:
            excerpt, reason = extract_relevant_excerpt(item, focus_query, 90)
            if signatures:
                parts.append("\n```text")
                parts.extend(signatures[:12])
                parts.append("```")
            parts.append(f"\n> {reason}")
            parts.append(f"\n```{item.lang or 'text'}\n{excerpt}\n```")
        return "\n".join(parts) + "\n"

    if item.truncated:
        parts.append(f"\n> File has {item.line_count} total lines; exported the first {item.rendered_line_count} lines.")
    parts.append(f"\n```{item.lang or 'text'}\n{item.content}\n```")
    return "\n".join(parts) + "\n"


def rank_primary_files(analysis) -> list:
    candidates = [item for item in analysis.selected_files if "test" not in item.tags and "docs" not in item.tags]
    task = analysis.config.task_profile
    mode = analysis.config.context_mode

    if task == "find_dead_code":
        return sorted(
            candidates,
            key=lambda item: (
                "entrypoint" in item.tags,
                item.dependents,
                item.score,
                item.relpath.as_posix(),
            ),
        )
    if task == "write_tests":
        return sorted(
            candidates,
            key=lambda item: (
                has_related_selected_test(item, analysis.selected_files),
                -(item.line_count),
                -(item.score),
                item.relpath.as_posix(),
            ),
        )
    if task in {"code_review", "pr_summary"} or mode == "diff":
        return sorted(
            candidates,
            key=lambda item: (
                item.path.resolve() not in analysis.changed_paths,
                "related to changed files" not in item.selection_reasons,
                -item.score,
                item.relpath.as_posix(),
            ),
        )
    if task == "bug_report" or mode == "debug":
        return sorted(
            candidates,
            key=lambda item: (
                item.path.resolve() not in analysis.changed_paths,
                not item.matched_focus,
                not ({"async", "integration", "analysis", "scanner"} & item.tags),
                -item.score,
                item.relpath.as_posix(),
            ),
        )
    if task == "refactor_request" or mode == "refactor":
        return sorted(
            candidates,
            key=lambda item: (
                -item.dependents,
                -len(item.local_imports),
                -item.line_count,
                item.relpath.as_posix(),
            ),
        )
    if mode == "feature":
        return sorted(
            candidates,
            key=lambda item: (
                not item.matched_focus,
                item.path.resolve() not in analysis.changed_paths,
                -item.score,
                item.relpath.as_posix(),
            ),
        )
    if mode == "onboarding":
        return sorted(
            candidates,
            key=lambda item: (
                "entrypoint" not in item.tags,
                -item.score,
                item.relpath.as_posix(),
            ),
        )
    return sorted(candidates, key=lambda item: (-item.score, item.relpath.as_posix()))


def group_selected_files(analysis) -> tuple[list, list, list, list]:
    primary_candidates = rank_primary_files(analysis)
    core_limit = 6 if analysis.config.context_mode == "onboarding" else 8
    test_limit = 2 if analysis.config.context_mode == "onboarding" else 6
    core_lookup = {
        item.relpath.as_posix() for item in primary_candidates[:core_limit]
    }
    core_files = [
        item for item in analysis.selected_files
        if item.relpath.as_posix() in core_lookup and "test" not in item.tags and "docs" not in item.tags
    ]
    related_tests = [item for item in analysis.selected_files if "test" in item.tags]
    docs = [item for item in analysis.selected_files if "docs" in item.tags]
    supporting = [
        item for item in analysis.selected_files
        if item not in core_files and item not in related_tests and item not in docs
    ]
    return core_files[:core_limit], supporting[:8], related_tests[:test_limit], docs[:6]


def ordered_payload_files(analysis, core_files: list, supporting_files: list, related_tests: list, docs_included: list) -> list:
    ordered_groups: list[list] = []
    if analysis.config.context_mode == "onboarding":
        ordered_groups = [core_files, docs_included, supporting_files, related_tests]
    elif analysis.config.task_profile in {"code_review", "pr_summary"} and analysis.config.context_mode == "diff":
        changed = [item for item in analysis.selected_files if item.path.resolve() in analysis.changed_paths]
        related_changed = [
            item
            for item in analysis.selected_files
            if item.path.resolve() not in analysis.changed_paths and "related to changed files" in item.selection_reasons
        ]
        ordered_groups = [changed, related_changed, related_tests, core_files, supporting_files, docs_included]
    else:
        ordered_groups = [core_files, supporting_files, related_tests, docs_included]

    seen: set[str] = set()
    ordered: list = []
    for group in ordered_groups:
        for item in group:
            rel = item.relpath.as_posix()
            if rel in seen:
                continue
            ordered.append(item)
            seen.add(rel)
    for item in analysis.selected_files:
        rel = item.relpath.as_posix()
        if rel in seen:
            continue
        ordered.append(item)
        seen.add(rel)
    return ordered


def has_related_selected_test(item, selected_files) -> bool:
    if "test" in item.tags:
        return False
    for candidate in selected_files:
        if "test" not in candidate.tags:
            continue
        if item.path.stem.lower() in candidate.path.stem.lower() or item.path.stem.lower() in candidate.content.lower():
            return True
    return False


def build_read_this_first(analysis) -> list[str]:
    ordered: list = []
    seen: set[str] = set()

    def push(item):
        rel = item.relpath.as_posix()
        if rel not in seen:
            ordered.append(item)
            seen.add(rel)

    for item in analysis.entrypoints[:1]:
        push(item)

    for tag in ("ui", "cli"):
        for item in analysis.selected_files:
            if tag in item.tags:
                push(item)

    for stem in ("renderer", "context_engine", "scanner"):
        for item in analysis.selected_files:
            if item.path.stem == stem:
                push(item)

    for item in analysis.selected_files:
        if "test" in item.tags:
            push(item)
            break

    lines: list[str] = []
    for index, item in enumerate(ordered[:6], start=1):
        reason = item.selection_reasons[0] if item.selection_reasons else "important context"
        lines.append(f"{index}. `{item.relpath.as_posix()}` — {item.summary} Selected because: {reason}.")
    return lines


def build_main_flow(analysis) -> list[str]:
    selected_by_stem = {item.path.stem: item for item in analysis.selected_files}
    flow: list[str] = []
    entry = analysis.entrypoints[0] if analysis.entrypoints else None
    ui_item = next((item for item in analysis.selected_files if "ui" in item.tags), None)
    cli_item = next((item for item in analysis.selected_files if "cli" in item.tags), None)
    renderer_item = selected_by_stem.get("renderer")
    engine_item = selected_by_stem.get("context_engine")
    scanner_item = selected_by_stem.get("scanner")

    if entry and ui_item and cli_item:
        flow.append(f"`{entry.relpath.as_posix()}` appears to start the app and route into either `{ui_item.relpath.as_posix()}` or `{cli_item.relpath.as_posix()}`.")
    elif entry and ui_item:
        flow.append(f"`{entry.relpath.as_posix()}` appears to start the app and hand control to `{ui_item.relpath.as_posix()}`.")
    elif entry and cli_item:
        flow.append(f"`{entry.relpath.as_posix()}` appears to start the app and hand control to `{cli_item.relpath.as_posix()}`.")
    elif entry:
        flow.append(f"`{entry.relpath.as_posix()}` appears to be the main entry point.")

    if ui_item:
        flow.append(f"`{ui_item.relpath.as_posix()}` drives the GUI workflow and gathers the export settings from the desktop interface.")
    if cli_item:
        flow.append(f"`{cli_item.relpath.as_posix()}` handles the CLI workflow, arguments, and output destinations.")
    if renderer_item and engine_item:
        flow.append(f"`{renderer_item.relpath.as_posix()}` assembles the pack, calls `build_analysis()`, and later formats the final Markdown output.")
        flow.append(f"`{engine_item.relpath.as_posix()}` classifies files, scores relevance, infers relationships, and chooses which context to export.")
    elif renderer_item:
        flow.append(f"`{renderer_item.relpath.as_posix()}` formats the selected project context into the exported Markdown.")
    if scanner_item:
        flow.append(f"`{scanner_item.relpath.as_posix()}` scans the tree, applies ignore rules, reads file contents, and surfaces git diff context when available.")
    if renderer_item and scanner_item and engine_item:
        flow.append(f"The final pass returns to `{renderer_item.relpath.as_posix()}`, which renders the chosen files, summaries, and token guidance into the finished pack.")
    return flow[:6]


def build_where_to_change(analysis) -> list[str]:
    by_stem = {item.path.stem: item for item in analysis.selected_files}
    by_tag: dict[str, list] = {}
    for item in analysis.selected_files:
        for tag in item.tags:
            by_tag.setdefault(tag, []).append(item)

    lines: list[str] = []
    if "ui" in by_tag or "theme" in by_tag or "ui" in by_stem or "theme" in by_stem:
        ui_targets = [name for name in ("ui", "theme") if name in by_stem]
        if ui_targets:
            lines.append(f"UI changes → {', '.join(f'`{by_stem[name].relpath.as_posix()}`' for name in ui_targets)}")
    if "context_engine" in by_stem:
        lines.append(f"Selection logic → `{by_stem['context_engine'].relpath.as_posix()}`")
    if "scanner" in by_stem:
        lines.append(f"Scanning and filters → `{by_stem['scanner'].relpath.as_posix()}`")
    if "renderer" in by_stem:
        lines.append(f"Export format → `{by_stem['renderer'].relpath.as_posix()}`")
    if "cli" in by_stem:
        lines.append(f"CLI behavior → `{by_stem['cli'].relpath.as_posix()}`")
    tests = [item for item in analysis.selected_files if "test" in item.tags][:2]
    if tests:
        lines.append(f"Behavior validation → {', '.join(f'`{item.relpath.as_posix()}`' for item in tests)}")
    return lines[:6]


def build_score_breakdown(analysis) -> list[str]:
    lines: list[str] = []
    for item in analysis.selected_files[:5]:
        if not item.score_breakdown:
            continue
        lines.append(f"`{item.relpath.as_posix()}` — score {item.score:.2f} ({'; '.join(item.score_breakdown[:6])})")
    return lines


def build_changed_context(analysis) -> tuple[list[str], list[str], list[str]]:
    changed_selected = [item for item in analysis.selected_files if item.path.resolve() in analysis.changed_paths]
    related_files = [
        item for item in analysis.selected_files
        if item.path.resolve() not in analysis.changed_paths and "related to changed files" in item.selection_reasons
    ]
    impacted_tests = [
        item for item in analysis.selected_files
        if "test" in item.tags and any(reason in item.selection_reasons for reason in ("related test", "related to changed files"))
    ]
    changed_lines = [
        f"`{item.relpath.as_posix()}` — {item.summary}"
        for item in changed_selected[:8]
    ]
    related_lines = [
        f"`{item.relpath.as_posix()}` — selected because {', '.join(item.selection_reasons)}."
        for item in related_files[:8]
    ]
    test_lines = [
        f"`{item.relpath.as_posix()}` — likely impacted coverage or verification path."
        for item in impacted_tests[:6]
    ]
    return changed_lines, related_lines, test_lines


def build_task_lens(analysis) -> list[str]:
    task = analysis.config.task_profile
    if task == "explain_project":
        return [
            "Start with the execution flow and core files before reading the raw payload.",
            "Use the Read This First list as the shortest onboarding path through the repository.",
        ]
    if task == "bug_report":
        return [
            "Look at changed files, hotspots, UI/threading paths, and subprocess or git integration first.",
            "Treat central files without nearby tests as the highest-risk debugging surface.",
        ]
    if task == "pr_summary":
        return [
            "Summarize what changed first, then explain the local impact and likely review surface.",
            "Prefer changed files, nearby dependencies, and affected tests over broad project narration.",
        ]
    if task == "code_review":
        return [
            "Lead with correctness risks, regressions, missing tests, and brittle heuristics.",
            "Use selection reasons and score breakdowns to audit whether the pack is centered on the right modules.",
        ]
    if task == "refactor_request":
        return [
            "Look for high-dependency modules, large files, and places where tests already give you a safe seam.",
            "Prefer coupling and dependency shape over recent edits or docs.",
        ]
    if task == "write_tests":
        return [
            "Prioritize central modules, execution entry points, and behaviors without obvious direct test coverage.",
            "Use related tests as examples, not proof that coverage is already complete.",
        ]
    if task == "find_dead_code":
        return [
            "Treat low-dependency files as suspects, not proof of dead code.",
            "Check for dynamic imports, packaging hooks, compatibility shims, and entrypoint wiring before removal.",
        ]
    if task == "ai_handoff":
        return [
            "This export is shaped to be pasted directly into another AI before asking for implementation or analysis help.",
            "Read the AI handoff section first, then follow the Read This First sequence before scanning the payload.",
        ]
    return [
        "Use the summary sections first, then confirm details in the payload where needed.",
        "Selection reasons show why each file entered the pack and where to trust or question the curation.",
    ]


def build_ai_handoff(analysis, project_name: str) -> list[str]:
    focus = analysis.config.focus_query.strip()
    lines = [
        f"I'm sending you a curated context pack of the `{project_name}` project.",
        f"The project looks like: {analysis.summary_lines[0]}" if analysis.summary_lines else f"The project purpose appears to be: {analysis.likely_purpose}",
        "Please use the architecture summary, main flow, read-this-first list, and file selection reasons before analyzing the full code payload.",
    ]
    if focus:
        lines.append(f"Focus especially on: {focus}.")
    lines.append(f"Task intent: {TASK_PROFILE_OPTIONS.get(analysis.config.task_profile, analysis.config.task_profile)}.")
    return lines


def build_suggested_prompts(analysis, project_name: str) -> list[str]:
    prompts = [
        f"Explain the architecture and main runtime flow of {project_name} using the summaries first and the payload only when needed.",
        f"Identify the most bug-prone or regression-prone areas in {project_name}, with attention to the highlighted risks and selected core files.",
        f"Suggest a safe refactor or implementation plan for the central modules in {project_name}, using the relationship map and selection reasons.",
    ]
    if analysis.config.task_profile == "write_tests":
        prompts[1] = f"Suggest the next best tests to add in {project_name}, focusing on central modules, edge cases, and missing direct coverage."
    if analysis.config.task_profile == "bug_report":
        prompts[2] = f"Trace the most likely failure path in {project_name} and propose the smallest safe fix based on changed files and nearby context."
    if analysis.config.task_profile == "ai_handoff":
        prompts[0] = f"Read this curated handoff for {project_name} and continue the work without re-auditing the entire repository from scratch."
    return prompts


def build_ignored_context(analysis) -> list[str]:
    selected = {item.relpath.as_posix() for item in analysis.selected_files}
    ignored_candidates = []
    for item in analysis.all_files:
        if item.relpath.as_posix() in selected:
            continue
        if item.path.resolve() in analysis.changed_paths or item.matched_focus:
            continue
        if {"docs", "utility", "init", "embedded_asset"} & item.tags or item.score < 3.5:
            ignored_candidates.append(item)

    lines = []
    for item in sorted(ignored_candidates, key=lambda candidate: (candidate.score, candidate.relpath.as_posix()))[:8]:
        reason = "low current relevance"
        if "docs" in item.tags:
            reason = "supporting documentation outside the current pack scope"
        elif "embedded_asset" in item.tags:
            reason = "embedded asset data that does not help understand behavior"
        elif "init" in item.tags:
            reason = "package boilerplate with low standalone value"
        elif "utility" in item.tags:
            reason = "small helper with low impact on the current task"
        lines.append(f"`{item.relpath.as_posix()}` — {reason}.")
    return lines


def build_selected_context_lines(analysis, total_files: int) -> list[str]:
    selected_files = len(analysis.selected_files)
    lines = [
        f"This pack includes **{selected_files}** file(s) out of **{total_files}** scanned file(s).",
    ]
    if analysis.config.context_mode == "full" and selected_files == total_files:
        lines.append("Full context includes the complete scanned project payload, ordered by likely importance.")
    elif analysis.config.context_mode == "diff":
        lines.append("Selection starts from changed files and expands to nearby dependencies, related tests, and high-risk context.")
    else:
        lines.append("Selection prioritizes entry points, central modules, focus matches, changed files, and related tests.")
    return lines


def build_coverage_gaps(analysis) -> list[str]:
    targets = [item for item in rank_primary_files(analysis) if "test" not in item.tags][:8]
    gaps: list[str] = []
    for item in targets:
        related_tests = [
            candidate for candidate in analysis.selected_files
            if "test" in candidate.tags and has_related_selected_test(item, [candidate])
        ]
        if related_tests:
            if analysis.config.task_profile == "code_review":
                gaps.append(f"`{item.relpath.as_posix()}` has nearby selected tests, but review whether they really cover the changed or risky paths.")
            continue
        if analysis.config.task_profile == "write_tests":
            gaps.append(f"`{item.relpath.as_posix()}` has no obvious related test in the selected pack and looks worth covering next.")
        else:
            gaps.append(f"`{item.relpath.as_posix()}` appears in the review surface without an obvious related test in the selected pack.")
    return gaps[:6]


def build_safe_refactor_seams(analysis) -> list[str]:
    seams: list[str] = []
    for item in rank_primary_files(analysis):
        if "test" in item.tags or "docs" in item.tags:
            continue
        if 1 <= item.dependents <= 5 and len(item.local_imports) <= 5:
            test_hint = "with nearby selected tests" if has_related_selected_test(item, analysis.selected_files) else "without obvious nearby test coverage"
            seams.append(
                f"`{item.relpath.as_posix()}` looks like a workable seam: {item.dependents} dependent(s), {len(item.local_imports)} local import(s), {test_hint}."
            )
        if len(seams) >= 5:
            break
    return seams


def build_possible_false_positives(analysis) -> list[str]:
    lines = [
        "Compatibility shims, launcher aliases, and packaging helpers can look weakly connected even when they still matter.",
        "Config, docs, and policy files are low-graph by nature and should not be treated as dead code just because imports are sparse.",
        "Dynamic imports, subprocess calls, and string-based entry hooks can hide usage from static heuristics.",
    ]
    if any(item.path.name.lower() == "mdcodebrief.py" for item in analysis.selected_files + analysis.all_files):
        lines.append("Legacy entrypoint shims like `mdcodebrief.py` should be verified before removal because external users may still call them.")
    return lines[:4]


def build_verification_checklist(analysis) -> list[str]:
    return [
        "Search for imports, string references, CLI wiring, and packaging hooks before removing a suspect file.",
        "Check whether GUI, CLI, or compatibility entrypoints route through the module indirectly.",
        "Confirm tests, docs, or release notes are not still pointing users at the suspect path.",
        "Remove only after the project still runs end-to-end without the candidate files.",
    ]


@dataclass(frozen=True)
class SectionSpec:
    key: str
    title: str
    style: str = "bullets"


SECTION_SPECS: dict[str, SectionSpec] = {
    "project_summary": SectionSpec("project_summary", "Project Summary"),
    "ai_task_brief": SectionSpec("ai_task_brief", "AI Task Brief", "paragraph"),
    "model_guidance": SectionSpec("model_guidance", "Model Guidance", "raw"),
    "architecture": SectionSpec("architecture", "Architecture Overview"),
    "read_this_first": SectionSpec("read_this_first", "Read This First", "raw"),
    "main_flow": SectionSpec("main_flow", "Main Flow"),
    "where_to_change": SectionSpec("where_to_change", "Where To Change What"),
    "task_lens": SectionSpec("task_lens", "Task Lens"),
    "ai_handoff": SectionSpec("ai_handoff", "AI Handoff"),
    "core_files": SectionSpec("core_files", "Core Files"),
    "supporting_files": SectionSpec("supporting_files", "Supporting Files"),
    "related_tests": SectionSpec("related_tests", "Related Tests"),
    "documentation": SectionSpec("documentation", "Documentation Included"),
    "score_breakdown": SectionSpec("score_breakdown", "Selection Reason Score Breakdown"),
    "folder_summaries": SectionSpec("folder_summaries", "Folder Summaries"),
    "relationship_map": SectionSpec("relationship_map", "Relationship Map"),
    "risks": SectionSpec("risks", "Potential Risks / Hotspots"),
    "coverage_gaps": SectionSpec("coverage_gaps", "Missing Coverage / Gaps"),
    "safe_refactor_seams": SectionSpec("safe_refactor_seams", "Safe Refactor Seams"),
    "possible_false_positives": SectionSpec("possible_false_positives", "Possible False Positives"),
    "verification_checklist": SectionSpec("verification_checklist", "Safe Verification Checklist"),
    "changed_context": SectionSpec("changed_context", "Changed Files + Context", "raw"),
    "selected_context": SectionSpec("selected_context", "Selected Context"),
    "directory_tree": SectionSpec("directory_tree", "Directory Tree", "codeblock"),
    "file_summaries": SectionSpec("file_summaries", "File Summaries"),
    "ignored_context": SectionSpec("ignored_context", "What Can Be Ignored"),
    "suggested_prompts": SectionSpec("suggested_prompts", "Suggested Prompts for AI"),
    "context_payload": SectionSpec("context_payload", "Context Payload", "payload"),
}


FULL_SECTION_KEYS = [
    "project_summary",
    "architecture",
    "read_this_first",
    "main_flow",
    "core_files",
    "supporting_files",
    "related_tests",
    "documentation",
    "relationship_map",
    "risks",
    "file_summaries",
    "context_payload",
]

ONBOARDING_SECTION_KEYS = [
    "project_summary",
    "architecture",
    "read_this_first",
    "main_flow",
    "where_to_change",
    "core_files",
    "documentation",
    "relationship_map",
    "folder_summaries",
    "related_tests",
    "context_payload",
    "suggested_prompts",
]

AI_HANDOFF_SECTION_KEYS = [
    "ai_handoff",
    "ai_task_brief",
    "model_guidance",
    "read_this_first",
    "main_flow",
    "core_files",
    "relationship_map",
    "risks",
    "ignored_context",
    "suggested_prompts",
    "context_payload",
]

DIFF_SECTION_KEYS = [
    "changed_context",
    "relationship_map",
    "risks",
    "selected_context",
    "context_payload",
]

REVIEW_SECTION_KEYS = [
    "ai_task_brief",
    "changed_context",
    "risks",
    "related_tests",
    "coverage_gaps",
    "relationship_map",
    "core_files",
    "score_breakdown",
    "context_payload",
]

DEBUG_SECTION_KEYS = [
    "ai_task_brief",
    "core_files",
    "changed_context",
    "main_flow",
    "related_tests",
    "risks",
    "context_payload",
]

FEATURE_SECTION_KEYS = [
    "ai_task_brief",
    "core_files",
    "main_flow",
    "supporting_files",
    "related_tests",
    "context_payload",
]

REFACTOR_SECTION_KEYS = [
    "ai_task_brief",
    "core_files",
    "relationship_map",
    "risks",
    "safe_refactor_seams",
    "related_tests",
    "score_breakdown",
    "context_payload",
]

WRITE_TESTS_SECTION_KEYS = [
    "ai_task_brief",
    "core_files",
    "related_tests",
    "coverage_gaps",
    "risks",
    "context_payload",
]

DEAD_CODE_SECTION_KEYS = [
    "ai_task_brief",
    "core_files",
    "relationship_map",
    "possible_false_positives",
    "verification_checklist",
    "context_payload",
]

DEFAULT_SECTION_KEYS = [
    "project_summary",
    "architecture",
    "read_this_first",
    "main_flow",
    "core_files",
    "supporting_files",
    "related_tests",
    "relationship_map",
    "risks",
    "context_payload",
]


def section_keys_for_analysis(analysis) -> list[str]:
    return section_keys_for_preview(
        analysis.config.context_mode,
        analysis.config.task_profile,
        bool(analysis.config.system_prompt.strip()),
    )


def section_keys_for_preview(
    context_mode: str,
    task_profile: str,
    has_custom_goal: bool = False,
) -> list[str]:
    if task_profile == "ai_handoff":
        return AI_HANDOFF_SECTION_KEYS
    if task_profile == "find_dead_code":
        return DEAD_CODE_SECTION_KEYS
    if task_profile == "write_tests":
        return WRITE_TESTS_SECTION_KEYS
    if task_profile == "refactor_request" or context_mode == "refactor":
        return REFACTOR_SECTION_KEYS
    if task_profile in {"code_review", "pr_summary"} and context_mode == "diff":
        return REVIEW_SECTION_KEYS
    if task_profile == "bug_report" or context_mode == "debug":
        return DEBUG_SECTION_KEYS
    if context_mode == "feature":
        return FEATURE_SECTION_KEYS
    if context_mode == "diff":
        return DIFF_SECTION_KEYS
    if context_mode == "full":
        keys = list(FULL_SECTION_KEYS)
        if has_custom_goal or task_profile != "general":
            keys.insert(1, "ai_task_brief")
        return keys
    if context_mode == "onboarding":
        return ONBOARDING_SECTION_KEYS
    keys = list(DEFAULT_SECTION_KEYS)
    if context_mode in {"debug", "refactor"} and "score_breakdown" not in keys:
        keys.insert(keys.index("relationship_map"), "score_breakdown")
    if context_mode == "diff":
        for key in ("changed_context", "relationship_map"):
            if key not in keys:
                keys.append(key)
    return keys


def section_titles_for_preview(
    context_mode: str,
    task_profile: str,
    has_custom_goal: bool = False,
) -> list[str]:
    return [section_title_for(key, task_profile, context_mode) for key in section_keys_for_preview(context_mode, task_profile, has_custom_goal)]


def section_title_for(key: str, task_profile: str, context_mode: str) -> str:
    if key == "ai_task_brief" and task_profile == "code_review":
        return "Review Objective"
    if key == "ai_task_brief" and task_profile == "pr_summary":
        return "Summary Objective"
    if key == "ai_task_brief" and task_profile == "bug_report":
        return "Bug Focus / Report Lens"
    if key == "ai_task_brief" and task_profile == "refactor_request":
        return "Refactor Goal"
    if key == "ai_task_brief" and task_profile == "write_tests":
        return "Testing Lens"
    if key == "ai_task_brief" and task_profile == "find_dead_code":
        return "Dead Code Lens"
    if key == "ai_task_brief" and context_mode == "feature":
        return "Focus Summary"
    if key == "ai_task_brief":
        return SECTION_SPECS[key].title
    if key == "core_files" and context_mode == "feature":
        return "Matched Files"
    if key == "core_files" and task_profile == "bug_report":
        return "Suspect Files"
    if key == "core_files" and task_profile == "refactor_request":
        return "Core Modules"
    if key == "core_files" and task_profile == "write_tests":
        return "Core Modules Worth Testing"
    if key == "core_files" and task_profile == "find_dead_code":
        return "Low-Signal Files"
    if key == "core_files" and task_profile in {"code_review", "pr_summary", "general", "explain_project", "ai_handoff"}:
        return "Core Files"
    if key == "core_files":
        return "Core Files"
    if key == "supporting_files" and context_mode == "feature":
        return "Related Files"
    if key == "related_tests" and task_profile == "code_review":
        return "Related Tests / Missing Tests"
    if key == "related_tests" and task_profile == "write_tests":
        return "Existing Related Tests"
    if key == "main_flow" and context_mode == "feature":
        return "Main Flow for Focus Area"
    if key == "main_flow" and task_profile == "bug_report":
        return "Failure Path / Main Flow"
    if key == "relationship_map" and task_profile == "refactor_request":
        return "Coupling / Relationship Map"
    if key == "relationship_map" and task_profile == "find_dead_code":
        return "Weakly Connected Modules"
    if key == "risks" and task_profile == "code_review":
        return "Key Risks / Review Notes"
    if key == "risks" and task_profile == "write_tests":
        return "High-Risk Behaviors"
    return SECTION_SPECS[key].title


def build_changed_context_lines(changed_lines: list[str], related_lines: list[str], impacted_test_lines: list[str]) -> list[str]:
    lines: list[str] = []
    if changed_lines:
        lines.append("Changed Files:")
        lines.extend(f"- {line}" for line in changed_lines)
    if related_lines:
        lines.append("Related Files:")
        lines.extend(f"- {line}" for line in related_lines)
    if impacted_test_lines:
        lines.append("Likely Impacted Tests:")
        lines.extend(f"- {line}" for line in impacted_test_lines)
    return lines


def render_section(md: list[str], spec: SectionSpec, content, config: ExportConfig) -> None:
    if not content:
        return
    md.extend(["", f"## {section_title_for(spec.key, config.task_profile, config.context_mode)}"])
    if spec.style == "paragraph":
        md.append(content)
        return
    if spec.style == "raw":
        md.extend(content)
        return
    if spec.style == "codeblock":
        md.extend(["```text", content, "```"])
        return
    if spec.style == "payload":
        for item in content:
            md.append(render_file_section(item, config, include_score_details=show_score_details(config)))
        return
    for line in content:
        md.append(f"- {line}")


def build_model_guidance_lines(ai_profile: str) -> list[str]:
    guidance = MODEL_PROMPT_GUIDANCE.get(ai_profile, MODEL_PROMPT_GUIDANCE["generic"])
    label = guidance["label"]
    works_well = guidance["works_well"]
    avoid = guidance["avoid"]
    usage = guidance["usage"]
    lines = [str(label)]
    lines.append("Usually works well:")
    lines.extend(f"- {entry}" for entry in works_well)
    lines.append("Usually avoid:")
    lines.extend(f"- {entry}" for entry in avoid)
    lines.append("Rough usage profile:")
    lines.extend(f"- {entry}" for entry in usage)
    return lines


def generate_markdown(
    project_path: Path,
    include_hidden: bool = False,
    include_unknown: bool = False,
    diff_mode: bool = False,
    staged_only: bool = False,
    system_prompt: str = "",
    log_cb=None,
    context_mode: str = "full",
    ai_profile: str = "generic",
    task_profile: str = "general",
    compression: str = "balanced",
    pack_profile: str = "custom",
    focus_query: str = "",
) -> str:
    if log_cb is None:
        log_cb = lambda msg, tag="": None

    config = ExportConfig(
        include_hidden=include_hidden,
        include_unknown=include_unknown,
        diff_mode=diff_mode,
        staged_only=staged_only,
        system_prompt=system_prompt,
        context_mode=context_mode,
        ai_profile=ai_profile,
        task_profile=task_profile,
        compression=compression,
        pack_profile=pack_profile,
        focus_query=focus_query,
    )

    gitignore_patterns = load_gitignore_patterns(project_path)
    if gitignore_patterns:
        log_cb(f"Loaded {len(gitignore_patterns)} .gitignore rule(s).", "info")

    changed_files = get_git_changed_files(project_path, staged_only=staged_only)
    if changed_files is None:
        log_cb("Git diff context not available here.", "muted")
        changed_files = []
    else:
        log_cb(f"Detected {len(changed_files)} changed file(s) for smart selection.", "info")

    log_cb("Scanning project structure...", "info")
    counter = [0]
    full_tree = build_tree(
        project_path,
        include_hidden,
        include_unknown,
        log_cb,
        counter,
        gitignore_patterns,
        project_path,
    )

    analysis = build_analysis(project_path, full_tree, changed_files, config, log_cb)
    selected_tree = build_diff_tree(
        analysis.selected_paths,
        project_path,
        include_hidden=True,
        include_unknown=True,
        gitignore_patterns=[],
    )

    total_files = count_files(full_tree)
    selected_files = len(analysis.selected_files)
    core_files, supporting_files, related_tests, docs_included = group_selected_files(analysis)
    payload_files = ordered_payload_files(analysis, core_files, supporting_files, related_tests, docs_included)
    read_this_first = build_read_this_first(analysis)
    main_flow = build_main_flow(analysis)
    where_to_change = build_where_to_change(analysis)
    task_lens = build_task_lens(analysis)
    score_breakdown = build_score_breakdown(analysis)
    changed_lines, related_changed_lines, impacted_test_lines = build_changed_context(analysis)
    ai_handoff = build_ai_handoff(analysis, project_path.name)
    model_guidance = build_model_guidance_lines(analysis.config.ai_profile)
    suggested_prompts = build_suggested_prompts(analysis, project_path.name)
    ignored_context = build_ignored_context(analysis)
    coverage_gaps = build_coverage_gaps(analysis)
    safe_refactor_seams = build_safe_refactor_seams(analysis)
    possible_false_positives = build_possible_false_positives(analysis)
    verification_checklist = build_verification_checklist(analysis)
    selected_context = build_selected_context_lines(analysis, total_files)
    changed_context_lines = build_changed_context_lines(changed_lines, related_changed_lines, impacted_test_lines)
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    md: list[str] = [
        f"# 🧭 {APP_NAME} Project Context Pack: `{project_path.name}`",
        "",
        f"> Generated by **{APP_NAME} {__version__}**  ",
        f"> Date: **{now}**  ",
        f"> Files: **{selected_files}**  ",
        f"> Files scanned: **{total_files}**  ",
        f"> Files selected: **{selected_files}**  ",
        f"> Pack: **{PACK_OPTIONS.get(analysis.config.pack_profile, PACK_OPTIONS['custom'])}**  ",
        f"> Context mode: **{CONTEXT_MODE_OPTIONS.get(analysis.config.context_mode, analysis.config.context_mode)}**  ",
        f"> AI target: **{AI_PROFILE_OPTIONS.get(analysis.config.ai_profile, analysis.config.ai_profile)}**  ",
        f"> Task mode: **{TASK_PROFILE_OPTIONS.get(analysis.config.task_profile, analysis.config.task_profile)}**  ",
        f"> Compression: **{COMPRESSION_OPTIONS.get(analysis.config.compression, analysis.config.compression)}**",
        "",
        "---",
        "",
        "## Project Context",
    ]

    if analysis.config.context_mode == "diff":
        md.insert(10, "> Mode: **Git diff**  ")
        if selected_files == 0:
            md.insert(11, "> Result: **No changed files matched the current filters**  ")

    section_content = {
        "project_summary": analysis.summary_lines,
        "ai_task_brief": analysis.task_prompt,
        "model_guidance": model_guidance if analysis.config.task_profile == "ai_handoff" else [],
        "architecture": analysis.architecture_lines,
        "read_this_first": read_this_first or ["1. Start with the highest-scoring selected file and follow its local relationships."],
        "main_flow": main_flow,
        "where_to_change": where_to_change,
        "task_lens": task_lens,
        "ai_handoff": ai_handoff,
        "core_files": [f"`{item.relpath.as_posix()}` — {item.summary} Selected because: {', '.join(item.selection_reasons)}." for item in core_files],
        "supporting_files": [f"`{item.relpath.as_posix()}` — {item.summary} Selected because: {', '.join(item.selection_reasons)}." for item in supporting_files],
        "related_tests": [f"`{item.relpath.as_posix()}` — {item.summary} Selected because: {', '.join(item.selection_reasons)}." for item in related_tests],
        "documentation": [f"`{item.relpath.as_posix()}` — {item.summary} Selected because: {', '.join(item.selection_reasons)}." for item in docs_included],
        "score_breakdown": score_breakdown if show_score_details(analysis.config) else [],
        "folder_summaries": analysis.folder_summaries,
        "relationship_map": analysis.relationships,
        "risks": analysis.risks,
        "coverage_gaps": coverage_gaps,
        "safe_refactor_seams": safe_refactor_seams,
        "possible_false_positives": possible_false_positives,
        "verification_checklist": verification_checklist,
        "changed_context": changed_context_lines,
        "selected_context": selected_context if analysis.config.context_mode != "full" else [],
        "directory_tree": render_tree_ascii(selected_tree),
        "file_summaries": [f"`{item.relpath.as_posix()}` — {item.summary}" for item in payload_files],
        "ignored_context": ignored_context,
        "suggested_prompts": suggested_prompts,
        "context_payload": payload_files,
    }

    for key in section_keys_for_analysis(analysis):
        spec = SECTION_SPECS[key]
        render_section(md, spec, section_content.get(key), analysis.config)

    full_md = "\n".join(md).strip() + "\n"
    tokens = estimate_tokens(full_md)
    token_hint = token_label(tokens)
    log_cb(token_hint, "info")
    full_md += f"\n---\n_Generated by **{APP_NAME} {__version__}** · {now} · {token_hint}_\n"
    return full_md
