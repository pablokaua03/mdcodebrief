"""
context_engine.py - Project analysis and smart context selection for Contexta.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from scanner import get_language, read_file_safe

APP_NAME = "Contexta"

CONTEXT_MODE_OPTIONS: dict[str, str] = {
    "full": "Full Context",
    "debug": "Debug Context",
    "feature": "Feature Context",
    "diff": "Diff Context",
    "onboarding": "Onboarding Context",
    "refactor": "Refactor Context",
}

AI_PROFILE_OPTIONS: dict[str, str] = {
    "generic": "Generic LLM",
    "chatgpt": "ChatGPT Mode",
    "claude": "Claude Mode",
    "gemini": "Gemini Mode",
    "copilot": "Copilot Mode",
}

TASK_PROFILE_OPTIONS: dict[str, str] = {
    "general": "General Context",
    "ai_handoff": "AI Handoff",
    "bug_report": "Bug Report Mode",
    "code_review": "Code Review Mode",
    "explain_project": "Explain This Project",
    "refactor_request": "Refactor Request",
    "pr_summary": "PR Summary",
    "write_tests": "Write Tests",
    "find_dead_code": "Find Dead Code",
}

COMPRESSION_OPTIONS: dict[str, str] = {
    "full": "Full Content",
    "balanced": "Balanced Compression",
    "focused": "Focused Compression",
    "signatures": "Signatures Only",
}

PACK_OPTIONS: dict[str, str] = {
    "custom": "Custom Pack",
    "chatgpt": "ChatGPT Pack",
    "onboarding": "Onboarding Pack",
    "pr_review": "PR Review Pack",
    "debug": "Debug Pack",
    "backend": "Backend Pack",
    "frontend": "Frontend Pack",
    "changes_related": "Changes + Related",
}

PACK_DEFAULTS: dict[str, dict[str, str]] = {
    "chatgpt": {
        "ai_profile": "chatgpt",
        "context_mode": "full",
        "task_profile": "general",
        "compression": "balanced",
    },
    "onboarding": {
        "ai_profile": "generic",
        "context_mode": "onboarding",
        "task_profile": "explain_project",
        "compression": "balanced",
    },
    "pr_review": {
        "ai_profile": "claude",
        "context_mode": "diff",
        "task_profile": "code_review",
        "compression": "focused",
    },
    "debug": {
        "ai_profile": "chatgpt",
        "context_mode": "debug",
        "task_profile": "bug_report",
        "compression": "focused",
    },
    "backend": {
        "ai_profile": "generic",
        "context_mode": "feature",
        "task_profile": "explain_project",
        "compression": "focused",
        "focus_query": "backend api server db service model repository",
    },
    "frontend": {
        "ai_profile": "generic",
        "context_mode": "feature",
        "task_profile": "explain_project",
        "compression": "focused",
        "focus_query": "frontend ui component page view screen style layout",
    },
    "changes_related": {
        "ai_profile": "claude",
        "context_mode": "debug",
        "task_profile": "code_review",
        "compression": "focused",
    },
}

MODEL_PROMPT_GUIDANCE: dict[str, dict[str, list[str] | str]] = {
    "generic": {
        "label": "Generic LLM",
        "summary": "Balanced default when the task and expected output are stated clearly.",
        "works_well": [
            "State the task and expected output format clearly.",
            "Keep instructions concise but precise.",
        ],
        "avoid": [
            "Vague goals with no definition of done.",
            "Overloading the prompt with unrelated asks.",
        ],
        "usage": [
            "Good default when you want balanced structure.",
            "Token and latency behavior vary a lot by provider and task.",
        ],
    },
    "chatgpt": {
        "label": "ChatGPT",
        "summary": "Works well with concise instructions, explicit deliverables, and optional short examples.",
        "works_well": [
            "Give a clear task, constraints, and final deliverable.",
            "Ask for a step-by-step explanation or reasoning summary when useful.",
        ],
        "avoid": [
            "Asking for hidden chain-of-thought.",
            "Mixing architecture questions and implementation requests without priority.",
        ],
        "usage": [
            "Likes explicit structure and concise instructions.",
            "Larger prompts can work, but visible output size and reasoning effort affect latency.",
        ],
    },
    "claude": {
        "label": "Claude",
        "summary": "Works well with structured requests, architecture context, and clearly scoped review goals.",
        "works_well": [
            "Give architecture context and a clearly scoped review or writing goal.",
            "Ask for organized sections with concrete recommendations.",
        ],
        "avoid": [
            "Broad prompts with no priority order.",
            "Asking for exhaustive output when a ranked answer would do.",
        ],
        "usage": [
            "Comfortable with richer context and structured analysis.",
            "Long prompts still benefit from a short task summary at the top.",
        ],
    },
    "gemini": {
        "label": "Gemini",
        "summary": "Works well with broader context plus explicit priorities so long inputs stay on task.",
        "works_well": [
            "Provide the project context plus explicit priorities.",
            "Tell it what to focus on before asking for conclusions.",
        ],
        "avoid": [
            "Assuming the largest context window means no prompt structure is needed.",
            "Mixing many unrelated tasks in one pass.",
        ],
        "usage": [
            "Comfortable with broader context packs.",
            "Latency and output quality still depend heavily on task shape.",
        ],
    },
    "copilot": {
        "label": "Copilot / Coding Agent",
        "summary": "Works well when files, constraints, and the expected end state are concrete and implementation-oriented.",
        "works_well": [
            "Specify the files, constraints, and expected final state.",
            "Ask for concrete code changes, tests, or a patch plan.",
        ],
        "avoid": [
            "High-level goals with no file or behavior target.",
            "Asking for hidden reasoning instead of a brief rationale.",
        ],
        "usage": [
            "Strong for implementation-first workflows.",
            "Benefits from smaller, well-scoped tasks and explicit acceptance criteria.",
        ],
    },
}

TASK_GUIDANCE: dict[str, str] = {
    "general": "Understand the project quickly and answer follow-up questions with accurate file references.",
    "ai_handoff": "Prepare a handoff-ready context pack that another AI can consume immediately with minimal extra prompting.",
    "bug_report": "Identify likely failure paths, root causes, and the smallest useful fix area.",
    "code_review": "Prioritize correctness risks, regressions, missing tests, and maintainability issues.",
    "explain_project": "Explain the architecture, main flows, and how the core modules fit together.",
    "refactor_request": "Find central abstractions, coupling hotspots, and safe refactor seams.",
    "pr_summary": "Summarize the meaningful changes, impacted files, and any review concerns.",
    "write_tests": "Spot untested paths, likely edge cases, and the best modules to cover next.",
    "find_dead_code": "Look for low-signal modules, disconnected utilities, and code that appears unused.",
}

STOPWORDS = {
    "the", "and", "for", "with", "this", "that", "from", "into", "your", "what",
    "when", "where", "just", "more", "only", "have", "uses", "using", "mode",
    "pack", "project", "context", "code", "file", "files", "task", "request",
    "review", "write", "tests", "find", "debug", "feature", "refactor", "bug",
}

DOC_FILENAMES = {
    "readme",
    "readme.md",
    "readme.pt-br.md",
    "changelog.md",
    "contributing.md",
    "security.md",
    "license",
    "license.md",
}

TECH_LABELS = {
    "python": "Python",
    "javascript": "JavaScript",
    "jsx": "React JSX",
    "typescript": "TypeScript",
    "tsx": "React TSX",
    "html": "HTML",
    "css": "CSS",
    "scss": "SCSS",
    "vue": "Vue",
    "svelte": "Svelte",
    "json": "JSON config",
    "yaml": "YAML",
    "toml": "TOML",
    "powershell": "PowerShell",
    "bash": "Shell scripts",
    "markdown": "Markdown docs",
    "dockerfile": "Docker",
}


@dataclass
class ExportConfig:
    include_hidden: bool = False
    include_unknown: bool = False
    diff_mode: bool = False
    staged_only: bool = False
    system_prompt: str = ""
    context_mode: str = "full"
    ai_profile: str = "generic"
    task_profile: str = "general"
    compression: str = "balanced"
    pack_profile: str = "custom"
    focus_query: str = ""


@dataclass
class FileInsight:
    path: Path
    relpath: Path
    lang: str | None
    content: str
    truncated: bool
    line_count: int
    rendered_line_count: int
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    local_imports: list[str] = field(default_factory=list)
    external_imports: list[str] = field(default_factory=list)
    tags: set[str] = field(default_factory=set)
    summary: str = ""
    score: float = 0.0
    score_breakdown: list[str] = field(default_factory=list)
    dependents: int = 0
    matched_focus: bool = False
    focus_score: float = 0.0
    selection_reasons: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class ProjectAnalysis:
    config: ExportConfig
    all_files: list[FileInsight]
    selected_files: list[FileInsight]
    selected_paths: list[Path]
    changed_paths: set[Path]
    technologies: list[str]
    entrypoints: list[FileInsight]
    important_files: list[FileInsight]
    architecture_lines: list[str]
    risks: list[str]
    relationships: list[str]
    folder_summaries: list[str]
    task_prompt: str
    likely_purpose: str
    summary_lines: list[str]


def resolve_config(config: ExportConfig) -> ExportConfig:
    resolved = replace(config)
    if resolved.pack_profile in PACK_DEFAULTS:
        for key, value in PACK_DEFAULTS[resolved.pack_profile].items():
            setattr(resolved, key, value)
    if resolved.diff_mode and resolved.context_mode == "full":
        resolved.context_mode = "diff"
    return resolved


def flatten_tree(node: dict) -> list[Path]:
    files = [item["path"] for item in node["files"]]
    for sub in node["dirs"]:
        files.extend(flatten_tree(sub))
    return files


def build_analysis(
    project_path: Path,
    full_tree: dict,
    changed_files: list[Path] | None,
    config: ExportConfig,
    log_cb=None,
) -> ProjectAnalysis:
    if log_cb is None:
        log_cb = lambda msg, tag="": None

    config = resolve_config(config)
    file_paths = flatten_tree(full_tree)
    insights = [make_file_insight(project_path, path) for path in file_paths]
    module_map = build_module_map(insights)
    rel_index, reverse_index = resolve_local_relationships(insights, module_map)
    changed_set = {path.resolve() for path in changed_files or []}

    for insight in insights:
        insight.local_imports = sorted(rel_index[insight.relpath.as_posix()])
        insight.dependents = len(reverse_index[insight.relpath.as_posix()])
        insight.focus_score = compute_focus_score(insight, config.focus_query or config.system_prompt)
        insight.matched_focus = insight.focus_score > 0
        insight.tags.update(classify_file(insight))

    entrypoints = detect_entrypoints(insights)
    entry_relpaths = {item.relpath.as_posix() for item in entrypoints}

    for insight in insights:
        insight.score, insight.score_breakdown = score_file(insight, entry_relpaths, changed_set)
        insight.summary = summarize_file(insight, reverse_index)

    important_candidates = [item for item in insights if "test" not in item.tags and "docs" not in item.tags]
    important_files = sorted(important_candidates or insights, key=lambda item: (-item.score, item.relpath.as_posix()))[:8]
    selected_files = select_files(insights, config, changed_set, reverse_index)
    selected_paths = [item.path for item in selected_files]
    technologies = detect_technologies(insights)
    likely_purpose = detect_likely_purpose(insights)
    architecture = build_architecture_overview(project_path, insights, entrypoints, technologies, likely_purpose)
    risk_source = insights if config.context_mode == "full" else selected_files
    risks = build_risks(risk_source, reverse_index)
    relationships = build_relationship_map(selected_files, reverse_index)
    folder_summaries = build_folder_summaries(selected_files)
    task_prompt = build_task_prompt(project_path, config)
    summary_lines = build_summary_lines(
        project_path,
        insights,
        selected_files,
        entrypoints,
        important_files,
        technologies,
        likely_purpose,
    )

    for item in selected_files:
        item.selection_reasons = infer_selection_reasons(
            item,
            selected_files,
            config,
            changed_set,
            reverse_index,
        )

    log_cb(f"Insight layer ready: {len(selected_files)} curated file(s) selected.", "ok")

    return ProjectAnalysis(
        config=config,
        all_files=insights,
        selected_files=selected_files,
        selected_paths=selected_paths,
        changed_paths=changed_set,
        technologies=technologies,
        entrypoints=entrypoints,
        important_files=important_files,
        architecture_lines=architecture,
        risks=risks,
        relationships=relationships,
        folder_summaries=folder_summaries,
        task_prompt=task_prompt,
        likely_purpose=likely_purpose,
        summary_lines=summary_lines,
    )


def make_file_insight(project_path: Path, path: Path) -> FileInsight:
    content, truncated, total_line_count = read_file_safe(path)
    lang = get_language(path)
    functions, classes, imports = extract_symbols(content, lang)
    external_imports = [item for item in imports if not item.startswith(".")]
    return FileInsight(
        path=path,
        relpath=path.relative_to(project_path),
        lang=lang,
        content=content,
        truncated=truncated,
        line_count=total_line_count,
        rendered_line_count=len(content.splitlines()),
        functions=functions,
        classes=classes,
        imports=imports,
        external_imports=external_imports,
    )


def extract_symbols(content: str, lang: str | None) -> tuple[list[str], list[str], list[str]]:
    if lang == "python":
        functions = re.findall(r"^\s*(?:async\s+def|def)\s+([A-Za-z_]\w*)", content, re.MULTILINE)
        classes = re.findall(r"^\s*class\s+([A-Za-z_]\w*)", content, re.MULTILINE)
        imports = []
        imports.extend(re.findall(r"^\s*import\s+([A-Za-z0-9_\.]+)", content, re.MULTILINE))
        imports.extend(re.findall(r"^\s*from\s+([A-Za-z0-9_\.]+|\.+[A-Za-z0-9_\.]*)\s+import", content, re.MULTILINE))
        return functions[:12], classes[:8], imports[:24]

    if lang in {"javascript", "jsx", "typescript", "tsx"}:
        functions = re.findall(r"(?:function|const|let|var)\s+([A-Za-z_]\w*)", content)
        classes = re.findall(r"class\s+([A-Za-z_]\w*)", content)
        imports = re.findall(r"""from\s+['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)""", content)
        flat_imports = [left or right for left, right in imports]
        return functions[:12], classes[:8], flat_imports[:24]

    return [], [], []


def build_module_map(insights: list[FileInsight]) -> dict[str, str]:
    module_map: dict[str, str] = {}
    for item in insights:
        parts = list(item.relpath.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if not parts:
            continue
        dotted = ".".join(parts)
        module_map[dotted] = item.relpath.as_posix()
        if len(parts) == 1:
            module_map.setdefault(parts[0], item.relpath.as_posix())
    return module_map


def resolve_local_relationships(
    insights: list[FileInsight],
    module_map: dict[str, str],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    rel_index: dict[str, set[str]] = defaultdict(set)
    reverse_index: dict[str, set[str]] = defaultdict(set)

    for item in insights:
        for imported in item.imports:
            target = resolve_local_import(item, imported, module_map)
            if not target or target == item.relpath.as_posix():
                continue
            rel_index[item.relpath.as_posix()].add(target)
            reverse_index[target].add(item.relpath.as_posix())

        related_tests = resolve_related_tests(item, insights)
        for test_rel in related_tests:
            reverse_index[item.relpath.as_posix()].add(test_rel)

    return rel_index, reverse_index


def resolve_local_import(item: FileInsight, imported: str, module_map: dict[str, str]) -> str | None:
    if item.lang == "python":
        if imported.startswith("."):
            base_parts = list(item.relpath.parent.parts)
            dots = len(imported) - len(imported.lstrip("."))
            tail = imported.lstrip(".")
            if dots <= len(base_parts):
                base_parts = base_parts[: len(base_parts) - dots + 1]
            else:
                base_parts = []
            if tail:
                base_parts.extend(tail.split("."))
            dotted = ".".join(part for part in base_parts if part)
            return module_map.get(dotted)
        return module_map.get(imported) or module_map.get(imported.split(".")[-1])
    return None


def resolve_related_tests(item: FileInsight, insights: list[FileInsight]) -> set[str]:
    related: set[str] = set()
    for candidate in insights:
        if is_related_test_for(item, candidate):
            related.add(candidate.relpath.as_posix())
    return related


def matches_focus(item: FileInsight, query: str) -> bool:
    return compute_focus_score(item, query) > 0


def compute_focus_score(item: FileInsight, query: str) -> float:
    keywords = extract_keywords(query)
    if not keywords:
        return 0.0

    score = 0.0
    rel = item.relpath.as_posix().lower()
    stem = item.path.stem.lower()
    imports_blob = " ".join(imported.lower() for imported in item.imports)
    functions_blob = " ".join(func.lower() for func in item.functions)
    classes_blob = " ".join(cls.lower() for cls in item.classes)
    content_lower = item.content.lower()

    for keyword in keywords:
        if keyword == stem or keyword in rel:
            score += 2.0
        if keyword in functions_blob or keyword in classes_blob:
            score += 1.8
        if keyword in imports_blob:
            score += 1.4
        if re.search(rf"\b{re.escape(keyword)}\b", content_lower):
            score += 0.8
        elif keyword in content_lower:
            score += 0.4

    return round(min(score, 6.0), 2)


def extract_keywords(text: str) -> list[str]:
    parts = re.findall(r"[A-Za-z0-9_/-]+", text.lower())
    keywords = [part for part in parts if len(part) > 2 and part not in STOPWORDS]
    return list(dict.fromkeys(keywords[:10]))


def _strip_wrapping_quotes(text: str) -> str:
    stripped = text.strip().strip(",")
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in {"'", '"'}:
        return stripped[1:-1]
    if len(stripped) >= 3 and stripped[0] == "b" and stripped[1] in {"'", '"'} and stripped[1] == stripped[-1]:
        return stripped[2:-1]
    return stripped


def is_blob_like_line(line: str) -> bool:
    candidate = line.strip().strip(",")
    if "=" in candidate:
        _prefix, _sep, suffix = candidate.partition("=")
        candidate = suffix.strip()
    candidate = _strip_wrapping_quotes(candidate)
    if len(candidate) < 96:
        return False
    if re.search(r"\s", candidate):
        return False
    cleaned = candidate
    allowed = re.sub(r"[^A-Za-z0-9+/=_-]", "", cleaned)
    if len(allowed) < 96:
        return False
    density = len(allowed) / max(len(cleaned), 1)
    if density < 0.97:
        return False
    return bool(re.fullmatch(r"[A-Za-z0-9+/=_-]+", allowed))


def has_embedded_asset_payload(item: FileInsight) -> bool:
    if item.lang in {"markdown", "mdx", "rst"}:
        return False
    rel = item.relpath.as_posix().lower()
    blob_lines = sum(1 for line in item.content.splitlines() if is_blob_like_line(line))
    asset_signal = any(token in rel for token in ("asset", "icon", "logo", "brand"))
    base64_signal = bool(re.search(r"\b[A-Z][A-Z0-9_]*B64\b|\bbase64\b", item.content))
    assignment_signal = bool(re.search(r"^\s*[A-Z][A-Z0-9_]{2,}\s*=\s*\(?\s*$", item.content, re.MULTILINE))
    return blob_lines >= 8 and (asset_signal or base64_signal or assignment_signal)


def should_sanitize_blob_excerpt(item: FileInsight) -> bool:
    if "embedded_asset" in item.tags:
        return True
    rel = item.relpath.as_posix().lower()
    if any(token in rel for token in ("asset", "icon", "logo", "brand")):
        return True
    if re.search(r"\b[A-Z][A-Z0-9_]*B64\b|\bbase64\b", item.content):
        return True
    return False


def is_named_test_for(item: FileInsight, candidate: FileInsight) -> bool:
    rel = candidate.relpath.as_posix().lower()
    if "test" not in rel:
        return False

    target = item.path.stem.lower()
    cand = candidate.path.stem.lower()
    if cand == f"test_{target}" or cand == f"{target}_test":
        return True
    if cand.startswith("test_") and cand.endswith(f"_{target}"):
        return True
    return False


def test_relation_score(item: FileInsight, candidate: FileInsight) -> int:
    rel = candidate.relpath.as_posix().lower()
    if "test" not in rel:
        return 0

    score = 0
    if is_named_test_for(item, candidate):
        score += 4

    item_stem = item.path.stem.lower()
    item_module = ".".join(item.relpath.with_suffix("").parts).lower()
    imports_lower = [imported.lower() for imported in candidate.imports]
    if any(
        imported == item_stem
        or imported == item_module
        or imported.endswith(f".{item_stem}")
        or item_module.endswith(imported)
        for imported in imports_lower
    ):
        score += 2

    symbol_names = [name for name in item.functions[:6] + item.classes[:4] if len(name) >= 4]
    mention_hits = sum(
        1
        for name in symbol_names
        if re.search(rf"\b{re.escape(name.lower())}\b", candidate.content.lower())
    )
    if mention_hits >= 2:
        score += 2
    elif mention_hits == 1:
        score += 1

    parent_name = item.relpath.parent.name.lower()
    if parent_name and parent_name != "." and parent_name in rel:
        score += 1

    return score


def is_related_test_for(item: FileInsight, candidate: FileInsight) -> bool:
    return test_relation_score(item, candidate) >= 4


def summarize_doc_file(item: FileInsight) -> str:
    name = item.path.name.lower()
    if name.startswith("readme"):
        return "Introduces the project, installation steps, and everyday usage."
    if name == "changelog.md":
        return "Tracks notable releases and user-visible changes across versions."
    if name == "contributing.md":
        return "Explains how contributors can work on the project safely and consistently."
    if name == "security.md":
        return "Describes security expectations, reporting, and support policy."
    if name.startswith("license"):
        return "Records the repository license terms and redistribution rules."
    return "Provides project documentation, release notes, or policy guidance."


def summarize_support_file(item: FileInsight) -> str | None:
    name = item.path.name.lower()
    rel = item.relpath.as_posix().lower()

    if name == "requirements.txt":
        return "Documents Python runtime, packaging, and test-time dependency expectations."
    if name == "build.bat":
        return "Automates Windows executable packaging through PyInstaller build steps."
    if name == "build.sh":
        return "Automates Unix-like executable packaging through PyInstaller build steps."
    if name.endswith(".spec") and "pyinstaller" in item.content.lower():
        return "Defines the PyInstaller build spec used to package the desktop application."
    if name == "contexta.py":
        return "Acts as the top-level launcher that decides between GUI and CLI execution."
    if name == "mdcodebrief.py":
        return "Legacy compatibility shim that forwards execution to contexta.main()."
    if name == "cli.py":
        return "Parses CLI flags, invokes pack generation, and handles file output or clipboard copy."
    if name == "ui.py":
        return "Implements the desktop interface, preview controls, and export workflow orchestration."
    if name == "theme.py":
        return "Defines theme palettes and repaint helpers for dark/light interface rendering."
    if name == "utils.py":
        return "Provides small desktop-path and filename helpers used by the app entry points."
    if rel.startswith("tests/") and name.startswith("test_"):
        target = item.path.stem.removeprefix("test_").replace("_", " ")
        return f"Exercises {target} behavior with focused automated checks."
    return None


def build_embedded_asset_excerpt(item: FileInsight) -> str:
    lines: list[str] = []
    docstring = re.search(r'^\s*"""([^"\n]+)"""', item.content, re.MULTILINE)
    if docstring:
        lines.append(f'"""{docstring.group(1)}"""')
    names = re.findall(r"^\s*([A-Z][A-Z0-9_]{2,})\s*=", item.content, re.MULTILINE)
    for name in names[:4]:
        lines.append(f"{name} = <embedded asset data omitted>")
    if not lines:
        lines.append("<embedded asset data omitted>")
    return "\n".join(lines)


def sanitize_excerpt_lines(item: FileInsight, lines: list[str]) -> tuple[list[str], bool]:
    sanitized: list[str] = []
    omitted_blob = False
    placeholder_open = False
    allow_blob_sanitization = should_sanitize_blob_excerpt(item)

    for line in lines:
        if allow_blob_sanitization and is_blob_like_line(line):
            omitted_blob = True
            if not placeholder_open:
                sanitized.append("<embedded blob omitted>")
                placeholder_open = True
            continue
        placeholder_open = False
        sanitized.append(line)

    return sanitized, omitted_blob


def classify_file(item: FileInsight) -> set[str]:
    rel = item.relpath.as_posix().lower()
    stem = item.path.stem.lower()
    imports_tk = bool(re.search(r"^\s*(?:from\s+tkinter|import\s+tkinter)", item.content, re.MULTILINE))
    imports_argparse = bool(re.search(r"^\s*(?:from\s+argparse|import\s+argparse)", item.content, re.MULTILINE))
    imports_threading = bool(re.search(r"^\s*(?:from\s+threading|import\s+threading)", item.content, re.MULTILINE))
    imports_subprocess = bool(re.search(r"^\s*(?:from\s+subprocess|import\s+subprocess)", item.content, re.MULTILINE))
    tags: set[str] = set()

    if "test" in rel:
        tags.add("test")
    if stem == "__init__":
        tags.add("init")

    if "test" not in tags:
        if stem in {"ui", "window", "view"} or (imports_tk and stem not in {"theme"}):
            tags.add("ui")
        if stem == "cli" or imports_argparse:
            tags.add("cli")
        if imports_threading:
            tags.add("async")
        if stem in {"scanner", "renderer", "cli"} or imports_subprocess:
            tags.add("integration")
        if stem == "context_engine" or "def build_analysis(" in item.content or "class ProjectAnalysis" in item.content:
            tags.add("analysis")
        if stem == "renderer" or (stem not in {"context_engine"} and "def generate_markdown(" in item.content):
            tags.add("renderer")
        if stem == "scanner" or "def build_tree(" in item.content or "gitignore" in item.content.lower():
            tags.add("scanner")
        if stem == "theme" or ("toggle_theme" in item.content and "apply_theme" in item.content):
            tags.add("theme")
        if "config" in rel or item.path.suffix.lower() in {".json", ".yaml", ".yml", ".toml", ".ini"}:
            tags.add("config")

    if item.lang in {"markdown", "mdx", "rst"} or item.path.name.lower() in DOC_FILENAMES:
        tags.add("docs")
    if any(token in rel for token in ("assets/", "_assets", "brand_assets")):
        tags.add("assets")
    if has_embedded_asset_payload(item):
        tags.update({"assets", "embedded_asset"})
    if "test" not in tags and ("util" in rel or "helper" in rel):
        tags.add("utility")
    if "test" not in tags and ("__name__ == \"__main__\"" in item.content or stem in {"main", "app", "index", "server", "contexta"}):
        tags.add("entrypoint")

    return tags


def detect_entrypoints(insights: list[FileInsight]) -> list[FileInsight]:
    scored: list[tuple[int, FileInsight]] = []
    for item in insights:
        if "test" in item.tags:
            continue
        score = 0
        rel = item.relpath.as_posix().lower()
        if "entrypoint" in item.tags:
            score += 5
        if item.path.name.lower() in {"main.py", "app.py", "index.js", "manage.py", "server.py", "contexta.py"}:
            score += 4
        if rel.count("/") == 0:
            score += 1
        if score >= 4:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].relpath.as_posix()))
    return [item for _, item in scored[:4]]


def score_file(item: FileInsight, entry_relpaths: set[str], changed_paths: set[Path]) -> tuple[float, list[str]]:
    score = 1.0
    breakdown = ["+1 base"]
    rel = item.relpath.as_posix()
    depth = len(item.relpath.parts)
    depth_bonus = max(0.0, 2.0 - (depth * 0.25))
    if depth_bonus:
        score += depth_bonus
        breakdown.append(f"+{depth_bonus:.1f} shallow path")
    dependent_bonus = min(item.dependents * 1.4, 8.0)
    if dependent_bonus:
        score += dependent_bonus
        breakdown.append(f"+{dependent_bonus:.1f} dependents")
    import_bonus = min(len(item.local_imports) * 0.5, 4.0)
    if import_bonus:
        score += import_bonus
        breakdown.append(f"+{import_bonus:.1f} imports")
    size_bonus = min(item.line_count / 180.0, 4.0)
    if size_bonus:
        score += size_bonus
        breakdown.append(f"+{size_bonus:.1f} size")
    if rel in entry_relpaths:
        score += 6.0
        breakdown.append("+6.0 entrypoint")
    if item.path.resolve() in changed_paths:
        score += 4.0
        breakdown.append("+4.0 changed file")
    if item.focus_score:
        score += item.focus_score
        breakdown.append(f"+{item.focus_score:.1f} focus match")
    if "test" in item.tags:
        score += 1.0
        breakdown.append("+1.0 test coverage")
    if {"ui", "cli", "renderer", "scanner", "config"} & item.tags:
        score += 2.0
        breakdown.append("+2.0 key role")
    if "analysis" in item.tags or "theme" in item.tags:
        score += 1.0
        breakdown.append("+1.0 core logic")
    if "docs" in item.tags:
        score -= 1.5
        breakdown.append("-1.5 docs")
    if "embedded_asset" in item.tags:
        score -= 2.5
        breakdown.append("-2.5 embedded asset")
    if "init" in item.tags:
        score -= 1.5
        breakdown.append("-1.5 init")
    return round(score, 2), breakdown[:8]


def summarize_file(item: FileInsight, reverse_index: dict[str, set[str]]) -> str:
    rel = item.relpath.as_posix()
    dependents = len(reverse_index.get(rel, set()))
    if "docs" in item.tags:
        return summarize_doc_file(item)
    support_summary = summarize_support_file(item)
    if support_summary:
        return support_summary
    if "embedded_asset" in item.tags:
        return "Stores embedded brand or binary-like asset payloads for the packaged GUI."
    if "test" in item.tags and "init" in item.tags:
        return "Marks the tests package for discovery and shared imports."
    if "init" in item.tags:
        return "Initializes the package namespace and shared module exports."
    if "entrypoint" in item.tags:
        return "Acts as a likely application entry point and routes the main execution flow."
    if "test" in item.tags:
        if item.path.stem.startswith("test_"):
            target = item.path.stem.removeprefix("test_").replace("_", " ")
            return f"Contains automated tests for {target} behavior."
        return "Contains supporting test helpers, fixtures, or test-only package setup."
    if "ui" in item.tags:
        return "Drives the desktop interface, user interactions, and presentation logic."
    if "cli" in item.tags:
        return "Handles command-line arguments, execution flow, and output writing."
    if item.path.stem == "context_engine" or "analysis" in item.tags:
        return "Scores files, infers relationships, and chooses which context to export."
    if item.path.stem == "renderer" or "renderer" in item.tags:
        return "Formats the selected analysis into Markdown sections and token guidance."
    if "scanner" in item.tags:
        return "Scans the project tree, applies ignore rules, and reads safe text content."
    if "theme" in item.tags:
        return "Defines theme palettes and repaint helpers for dark/light interface rendering."
    if "config" in item.tags:
        return "Holds configuration, metadata, or runtime settings used by other modules."
    if "utility" in item.tags:
        return "Provides shared helper utilities used across the codebase."

    summary_bits = []
    if item.functions:
        summary_bits.append(f"Defines {len(item.functions)} function(s)")
    if item.classes:
        summary_bits.append(f"{len(item.classes)} class(es)")
    if dependents:
        summary_bits.append(f"referenced by {dependents} other file(s)")
    if not summary_bits:
        summary_bits.append("Contains supporting project logic")
    return ", ".join(summary_bits) + "."


def detect_technologies(insights: list[FileInsight]) -> list[str]:
    counts = Counter(item.lang or "unknown" for item in insights)
    techs: list[str] = []
    for lang, _count in counts.most_common():
        label = TECH_LABELS.get(lang)
        if label and label not in techs:
            techs.append(label)

    content_blob = "\n".join(item.content.lower() for item in insights[:40])
    if "tkinter" in content_blob:
        techs.append("Tkinter desktop GUI")
    if "argparse" in content_blob or "sys.argv" in content_blob:
        techs.append("CLI workflow")
    if "unittest" in content_blob:
        techs.append("unittest test suite")
    if "git diff" in content_blob or "gitignore" in content_blob:
        techs.append("Git-aware file analysis")
    return techs[:6]


def detect_likely_purpose(insights: list[FileInsight]) -> str:
    names = {item.path.stem.lower() for item in insights}
    content_blob = "\n".join(item.content.lower() for item in insights[:20])

    if {"scanner", "renderer", "ui", "cli"} <= names:
        return "Scan project folders and generate curated Markdown context packs for AI workflows."
    if "tkinter" in content_blob and "argparse" in content_blob:
        return "Provide a desktop app with a companion CLI for local project analysis."
    if "fastapi" in content_blob or "flask" in content_blob:
        return "Serve an API-backed application with supporting project modules."
    if "react" in content_blob or "next" in content_blob:
        return "Deliver a frontend application with reusable UI and feature modules."
    return "Organize project structure and expose the most relevant code paths for developer workflows."


def build_architecture_overview(
    project_path: Path,
    insights: list[FileInsight],
    entrypoints: list[FileInsight],
    technologies: list[str],
    likely_purpose: str,
) -> list[str]:
    lines: list[str] = []

    if any(item.lang == "python" for item in insights):
        app_type = "Python application"
    elif any(item.lang in {"typescript", "tsx", "javascript", "jsx"} for item in insights):
        app_type = "JavaScript/TypeScript application"
    else:
        app_type = "multi-language project"

    if any("ui" in item.tags for item in insights) and any("cli" in item.tags for item in insights):
        lines.append(f"This project appears to be a {app_type} with both GUI and CLI workflows.")
    else:
        lines.append(f"This project appears to be a {app_type}.")

    if entrypoints:
        listed = ", ".join(f"`{item.relpath.as_posix()}`" for item in entrypoints[:3])
        lines.append(f"Likely entry points include {listed}.")

    core_modules = [item.path.stem for item in sorted(insights, key=lambda item: (-item.score, item.relpath.as_posix()))[:4]]
    if core_modules:
        lines.append(f"Core modules appear to center around {', '.join(core_modules)}.")

    if technologies:
        lines.append(f"Key technologies detected: {', '.join(technologies[:4])}.")

    lines.append(f"Likely purpose: {likely_purpose}")
    return lines[:5]


def build_summary_lines(
    project_path: Path,
    insights: list[FileInsight],
    selected_files: list[FileInsight],
    entrypoints: list[FileInsight],
    important_files: list[FileInsight],
    technologies: list[str],
    likely_purpose: str,
) -> list[str]:
    lines = [
        f"`{project_path.name}` looks like a {detect_project_shape(insights)}.",
        f"Likely purpose: {likely_purpose}",
    ]
    if entrypoints:
        lines.append(f"Main entry point: `{entrypoints[0].relpath.as_posix()}`")
    if technologies:
        lines.append(f"Main technologies detected: {', '.join(technologies[:4])}")
    if important_files:
        core = ", ".join(item.path.stem for item in important_files[:4])
        lines.append(f"Core modules: {core}")
    if any("test" in item.tags for item in selected_files):
        tested = [item.path.name for item in selected_files if "test" in item.tags and item.path.stem.startswith("test")]
        lines.append(f"Tests found in: {', '.join(tested)}")
    return lines


def detect_project_shape(insights: list[FileInsight]) -> str:
    langs = {item.lang for item in insights}
    has_ui = any("ui" in item.tags for item in insights)
    has_cli = any("cli" in item.tags for item in insights)

    if "python" in langs and has_ui and has_cli:
        return "Python desktop app with GUI + CLI"
    if "python" in langs:
        return "Python application"
    if {"typescript", "tsx", "javascript", "jsx"} & langs:
        return "frontend-oriented JavaScript/TypeScript project"
    return "developer-facing software project"


def build_risks(insights: list[FileInsight], reverse_index: dict[str, set[str]]) -> list[str]:
    risks: list[str] = []
    for item in sorted(insights, key=lambda entry: (-entry.line_count, entry.relpath.as_posix()))[:3]:
        if item.line_count >= 220:
            dependents = len(reverse_index[item.relpath.as_posix()])
            if dependents >= 2:
                risks.append(f"`{item.relpath.as_posix()}` is both large ({item.line_count} lines) and central to the graph, so regressions here can spread quickly.")
            else:
                risks.append(f"`{item.relpath.as_posix()}` is relatively large ({item.line_count} lines) and may be a change hotspot.")

    for item in sorted(insights, key=lambda entry: (-len(reverse_index[entry.relpath.as_posix()]), entry.relpath.as_posix()))[:3]:
        dependents = len(reverse_index[item.relpath.as_posix()])
        if dependents >= 2:
            risks.append(f"`{item.relpath.as_posix()}` sits on a central path and is depended on by {dependents} file(s).")

    for item in insights:
        if "async" in item.tags or ("ui" in item.tags and "threading" in item.content):
            risks.append(f"`{item.relpath.as_posix()}` mixes UI and background work, so race conditions or state sync bugs are worth watching.")
        if "integration" in item.tags and "test" not in item.tags:
            risks.append(f"`{item.relpath.as_posix()}` touches process or git integration, which is often sensitive to environment differences.")
        if {"analysis", "scanner"} & item.tags and ("re." in item.content or "re.findall" in item.content or "re.search" in item.content):
            risks.append(f"`{item.relpath.as_posix()}` relies on regex-heavy heuristics, so false positives or false negatives are a realistic maintenance risk.")
        if len(risks) >= 5:
            break

    return list(dict.fromkeys(risks))[:5]


def build_relationship_map(selected_files: list[FileInsight], reverse_index: dict[str, set[str]]) -> list[str]:
    rels: list[str] = []
    selected_lookup = {item.relpath.as_posix(): item for item in selected_files}
    selected_tests = [item for item in selected_files if "test" in item.tags]
    for item in selected_files:
        for target in item.local_imports[:3]:
            if target in selected_lookup:
                rels.append(f"`{item.relpath.as_posix()}` depends on `{target}`")
        if "test" in item.tags:
            continue
        related_tests = [
            candidate.relpath.as_posix()
            for candidate in selected_tests
            if test_relation_score(item, candidate) >= 4
        ]
        for test_path in sorted(related_tests)[:2]:
            rels.append(f"`{test_path}` likely covers `{item.relpath.as_posix()}`")
    return list(dict.fromkeys(rels))[:10]


def infer_selection_reasons(
    item: FileInsight,
    selected_files: list[FileInsight],
    config: ExportConfig,
    changed_paths: set[Path],
    reverse_index: dict[str, set[str]],
) -> list[str]:
    reasons: list[str] = []
    changed_relpaths = {
        selected.relpath.as_posix()
        for selected in selected_files
        if selected.path.resolve() in changed_paths
    }
    selected_tests = [candidate for candidate in selected_files if "test" in candidate.tags]

    if "entrypoint" in item.tags:
        reasons.append("entrypoint")
    if item.path.resolve() in changed_paths:
        reasons.append("changed file")
    if item.matched_focus:
        reasons.append("matched focus")
    if "test" in item.tags:
        if any(test_relation_score(other, item) >= 4 for other in selected_files if "test" not in other.tags):
            reasons.append("related test")
    if "docs" in item.tags:
        reasons.append("documentation")
    if item.dependents >= 2 and "test" not in item.tags and "docs" not in item.tags:
        reasons.append("central dependency")

    if changed_relpaths and item.relpath.as_posix() not in changed_relpaths:
        touches_changed = any(target in changed_relpaths for target in item.local_imports)
        touched_by_changed = any(dep in changed_relpaths for dep in reverse_index.get(item.relpath.as_posix(), set()))
        if touches_changed or touched_by_changed:
            reasons.append("related to changed files")

    if config.context_mode == "onboarding" and not reasons and "docs" not in item.tags:
        reasons.append("onboarding mode picked central file")
    elif config.context_mode == "feature" and not reasons:
        reasons.append("supports the focused area")
    elif config.context_mode == "refactor" and not reasons:
        reasons.append("high-leverage refactor candidate")
    elif config.context_mode == "debug" and not reasons:
        reasons.append("debug context support")
    elif config.context_mode == "full" and not reasons:
        reasons.append("full context keeps the complete project payload")

    if not reasons and "test" in item.tags and selected_tests:
        reasons.append("selected test coverage")
    if not reasons:
        reasons.append("high score")

    return list(dict.fromkeys(reasons))[:3]


def build_folder_summaries(selected_files: list[FileInsight]) -> list[str]:
    groups: dict[str, list[FileInsight]] = defaultdict(list)
    for item in selected_files:
        top = item.relpath.parts[0] if len(item.relpath.parts) > 1 else "."
        groups[top].append(item)

    summaries: list[str] = []
    for folder, items in sorted(groups.items()):
        if folder == ".":
            focus = ", ".join(entry.path.name for entry in items[:3])
            summaries.append(f"root: contains key top-level files such as {focus}.")
            continue
        tags = Counter(tag for item in items for tag in item.tags)
        if "test" in tags:
            summaries.append(f"{folder}/: groups {len(items)} selected file(s) and mainly handles automated coverage.")
        elif "ui" in tags:
            summaries.append(f"{folder}/: groups {len(items)} selected file(s) focused on interface and presentation.")
        elif "config" in tags:
            summaries.append(f"{folder}/: groups {len(items)} selected file(s) with config and environment setup.")
        else:
            names = ", ".join(entry.path.name for entry in items[:3])
            summaries.append(f"{folder}/: contains {len(items)} selected file(s), including {names}.")
    return summaries[:6]


def select_files(
    insights: list[FileInsight],
    config: ExportConfig,
    changed_paths: set[Path],
    reverse_index: dict[str, set[str]],
) -> list[FileInsight]:
    lookup = {item.relpath.as_posix(): item for item in insights}
    docs = [item for item in insights if "docs" in item.tags]
    tests = [item for item in insights if "test" in item.tags]
    important = sorted(insights, key=lambda item: (-item.score, item.relpath.as_posix()))
    focus_matches = [item for item in important if item.matched_focus]
    changed = [item for item in important if item.path.resolve() in changed_paths]

    if config.task_profile == "write_tests":
        return select_write_tests_files(config, lookup, important, focus_matches, tests)
    if config.task_profile == "find_dead_code":
        return select_dead_code_files(config, lookup, important, docs, tests)
    if config.context_mode == "diff":
        return select_diff_files(insights, config, changed_paths, reverse_index, lookup, changed, tests)
    if config.context_mode == "onboarding":
        return select_onboarding_files(insights, config, lookup, important, docs, tests, reverse_index)
    if config.context_mode == "debug":
        return select_debug_files(config, lookup, important, focus_matches, changed, tests, reverse_index)
    if config.context_mode == "feature":
        return select_feature_files(config, lookup, important, focus_matches, docs, tests, reverse_index)
    if config.context_mode == "refactor":
        return select_refactor_files(config, lookup, important, tests, reverse_index)
    if config.context_mode == "full":
        return important

    selected: set[str] = {item.relpath.as_posix() for item in important[:12]}
    selected = add_related_tests(selected, lookup, tests)
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(key=lambda item: (-item.score, item.relpath.as_posix()))
    return ordered[:20]


def add_related_tests(
    selected: set[str],
    lookup: dict[str, FileInsight],
    tests: list[FileInsight],
    limit: int = 4,
    min_score: int = 4,
    allow_token_fallback: bool = True,
) -> set[str]:
    related_targets = [lookup[rel] for rel in selected if rel in lookup and "test" not in lookup[rel].tags]
    ranked_tests = sorted(
        tests,
        key=lambda candidate: max((test_relation_score(target, candidate) for target in related_targets), default=0),
        reverse=True,
    )
    for item in ranked_tests[:limit]:
        best_score = max((test_relation_score(target, item) for target in related_targets), default=0)
        if best_score >= min_score or (
            allow_token_fallback and any(token in item.relpath.as_posix().lower() for token in derive_selected_tokens(selected))
        ):
            selected.add(item.relpath.as_posix())
    return selected


def select_onboarding_files(
    insights: list[FileInsight],
    config: ExportConfig,
    lookup: dict[str, FileInsight],
    important: list[FileInsight],
    docs: list[FileInsight],
    tests: list[FileInsight],
    reverse_index: dict[str, set[str]],
) -> list[FileInsight]:
    selected: set[str] = set()
    non_test_core = [item for item in important if "test" not in item.tags and "docs" not in item.tags]
    for item in docs[:2] + detect_entrypoints(insights)[:2] + non_test_core[:5]:
        selected.add(item.relpath.as_posix())
    selected = expand_with_related(selected, lookup, reverse_index, include_dependents=False)
    selected = add_related_tests(selected, lookup, tests, limit=2, min_score=5, allow_token_fallback=False)
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(
        key=lambda item: (
            "docs" in item.tags,
            "test" in item.tags,
            -item.score,
            item.relpath.as_posix(),
        )
    )
    return ordered[:11]


def select_debug_files(
    config: ExportConfig,
    lookup: dict[str, FileInsight],
    important: list[FileInsight],
    focus_matches: list[FileInsight],
    changed: list[FileInsight],
    tests: list[FileInsight],
    reverse_index: dict[str, set[str]],
) -> list[FileInsight]:
    selected: set[str] = {
        item.relpath.as_posix()
        for item in (changed[:6] + focus_matches[:6] + [entry for entry in important if {"async", "integration", "analysis", "scanner"} & entry.tags][:4])
    }
    selected = expand_with_related(selected, lookup, reverse_index, include_dependents=True)
    selected = add_related_tests(selected, lookup, tests, limit=4)
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(
        key=lambda item: (
            item.path.resolve() not in {candidate.path.resolve() for candidate in changed},
            not item.matched_focus,
            -item.score,
            item.relpath.as_posix(),
        )
    )
    return ordered[:16]


def select_feature_files(
    config: ExportConfig,
    lookup: dict[str, FileInsight],
    important: list[FileInsight],
    focus_matches: list[FileInsight],
    docs: list[FileInsight],
    tests: list[FileInsight],
    reverse_index: dict[str, set[str]],
) -> list[FileInsight]:
    selected: set[str] = {item.relpath.as_posix() for item in (focus_matches[:8] or important[:6])}
    if not focus_matches and docs:
        selected.add(docs[0].relpath.as_posix())
    selected = expand_with_related(selected, lookup, reverse_index, include_dependents=True)
    selected = add_related_tests(selected, lookup, tests, limit=4)
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(key=lambda item: (not item.matched_focus, -item.score, item.relpath.as_posix()))
    return ordered[:14]


def select_refactor_files(
    config: ExportConfig,
    lookup: dict[str, FileInsight],
    important: list[FileInsight],
    tests: list[FileInsight],
    reverse_index: dict[str, set[str]],
) -> list[FileInsight]:
    central = [item for item in important if "test" not in item.tags and "docs" not in item.tags][:10]
    selected: set[str] = {item.relpath.as_posix() for item in central}
    selected = expand_with_related(selected, lookup, reverse_index, include_dependents=True)
    selected = add_related_tests(selected, lookup, tests, limit=4)
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(key=lambda item: (-item.dependents, -item.score, item.relpath.as_posix()))
    return ordered[:16]


def select_write_tests_files(
    config: ExportConfig,
    lookup: dict[str, FileInsight],
    important: list[FileInsight],
    focus_matches: list[FileInsight],
    tests: list[FileInsight],
) -> list[FileInsight]:
    behavior_heavy = [
        item for item in important
        if "test" not in item.tags and ("integration" in item.tags or "analysis" in item.tags or item.line_count >= 80)
    ]
    selected: set[str] = {
        item.relpath.as_posix()
        for item in (focus_matches[:4] + behavior_heavy[:8] + [item for item in important if "entrypoint" in item.tags][:2])
    }
    selected = add_related_tests(selected, lookup, tests, limit=6)
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(key=lambda item: ("test" in item.tags, -item.score, item.relpath.as_posix()))
    return ordered[:16]


def select_dead_code_files(
    config: ExportConfig,
    lookup: dict[str, FileInsight],
    important: list[FileInsight],
    docs: list[FileInsight],
    tests: list[FileInsight],
) -> list[FileInsight]:
    low_signal = sorted(
        [item for item in important if "docs" not in item.tags and "test" not in item.tags],
        key=lambda item: (
            "entrypoint" in item.tags,
            item.dependents,
            item.score,
            item.relpath.as_posix(),
        ),
    )
    selected: set[str] = {item.relpath.as_posix() for item in low_signal[:10]}
    for item in docs[:1] + tests[:1]:
        selected.add(item.relpath.as_posix())
    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(key=lambda item: (item.dependents, item.score, item.relpath.as_posix()))
    return ordered[:14]


def select_diff_files(
    insights: list[FileInsight],
    config: ExportConfig,
    changed_paths: set[Path],
    reverse_index: dict[str, set[str]],
    lookup: dict[str, FileInsight],
    changed: list[FileInsight],
    tests: list[FileInsight],
) -> list[FileInsight]:
    if not changed:
        return []

    selected: set[str] = {item.relpath.as_posix() for item in changed[:10]}
    changed_relpaths = set(selected)

    for item in changed[:8]:
        for target in item.local_imports[:2]:
            target_item = lookup.get(target)
            if not target_item or "docs" in target_item.tags:
                continue
            selected.add(target)
        for dependent in sorted(reverse_index.get(item.relpath.as_posix(), set())):
            dependent_item = lookup.get(dependent)
            if not dependent_item or "docs" in dependent_item.tags:
                continue
            if dependent_item.score >= 5 or dependent_item.matched_focus:
                selected.add(dependent)
            if len([rel for rel in selected if rel not in changed_relpaths]) >= 6:
                break

    related_targets = [lookup[rel] for rel in selected if rel in lookup and "test" not in lookup[rel].tags]
    ranked_tests = sorted(
        tests,
        key=lambda candidate: max((test_relation_score(target, candidate) for target in related_targets), default=0),
        reverse=True,
    )
    for item in ranked_tests[:4]:
        best_score = max((test_relation_score(target, item) for target in related_targets), default=0)
        if best_score >= 4:
            selected.add(item.relpath.as_posix())

    if config.task_profile in {"code_review", "pr_summary"}:
        cap = 12
    else:
        cap = 14

    ordered = [lookup[rel] for rel in selected if rel in lookup]
    ordered.sort(key=lambda item: (-item.score, item.relpath.as_posix()))
    return ordered[:cap]


def derive_selected_tokens(selected: set[str]) -> set[str]:
    tokens: set[str] = set()
    for rel in selected:
        path = Path(rel)
        tokens.add(path.stem.lower().replace("test_", ""))
    return tokens


def expand_with_related(
    selected: set[str],
    lookup: dict[str, FileInsight],
    reverse_index: dict[str, set[str]],
    include_dependents: bool = False,
) -> set[str]:
    expanded = set(selected)
    for rel in list(selected):
        item = lookup.get(rel)
        if not item:
            continue
        for target in item.local_imports[:4]:
            expanded.add(target)
        if include_dependents:
            for dependent in list(reverse_index.get(rel, set()))[:3]:
                expanded.add(dependent)
    return expanded


def build_task_prompt(project_path: Path, config: ExportConfig) -> str:
    task_guidance = TASK_GUIDANCE.get(config.task_profile, TASK_GUIDANCE["general"])
    user_goal = config.system_prompt.strip()
    focus = config.focus_query.strip()

    prompt = f"You are reviewing the {project_path.name} project. {task_guidance}"
    if config.task_profile == "explain_project":
        prompt += " Start from the architecture summary and main execution flow before diving into file details."
    elif config.task_profile == "bug_report":
        prompt += " Prioritize changed files, hotspots, subprocess or threading risks, and the most likely failure path."
    elif config.task_profile == "code_review":
        prompt += " Lead with bugs, regressions, missing tests, and risky assumptions before proposing improvements."
    elif config.task_profile == "pr_summary":
        prompt += " Start with what changed, then explain the local impact, review surface, and any important follow-up concerns."
    elif config.task_profile == "write_tests":
        prompt += " Look for uncovered behaviors, boundary cases, and central modules without obvious direct test coverage."
    elif config.task_profile == "refactor_request":
        prompt += " Focus on coupling, central modules, safer refactor seams, and the smallest sequence of changes that would reduce risk."
    elif config.task_profile == "find_dead_code":
        prompt += " Treat dead-code signals as hypotheses, show the evidence, and call out likely false positives before suggesting removal."
    elif config.task_profile == "ai_handoff":
        prompt += " Use the handoff summary, read-this-first list, and file selection reasons before reading the raw payload."
    if focus:
        prompt += f" Focus especially on: {focus}."
    if user_goal:
        prompt += f" User goal: {user_goal}."
    return prompt.strip()


def extract_signatures(item: FileInsight) -> list[str]:
    signatures: list[str] = []
    lines = item.content.splitlines()

    if item.lang == "python":
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("async def ") or stripped.startswith("class "):
                signatures.append(stripped)
    elif item.lang in {"javascript", "jsx", "typescript", "tsx"}:
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("export ") or stripped.startswith("function ") or stripped.startswith("class "):
                signatures.append(stripped)

    return signatures[:18]


def extract_relevant_excerpt(item: FileInsight, query: str, max_lines: int = 90) -> tuple[str, str]:
    lines = item.content.splitlines()
    keywords = extract_keywords(query)
    if not lines:
        return "", "No textual content available."

    if "embedded_asset" in item.tags:
        excerpt = build_embedded_asset_excerpt(item)
        reason = "Embedded asset payload omitted because the file mostly stores inline binary/base64 data."
        return excerpt, reason

    if not keywords:
        excerpt, omitted_blob = sanitize_excerpt_lines(item, lines[:max_lines])
        if not excerpt:
            return "<excerpt omitted>", "Opening excerpt omitted because the file content is not useful as readable source."
        reason = "Opening excerpt shown because no focus keywords were provided."
        if omitted_blob:
            reason += " Embedded blob lines were omitted."
        return "\n".join(excerpt), reason

    matches: list[int] = []
    for idx, line in enumerate(lines):
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            matches.append(idx)

    if not matches:
        symbol_matches = [
            symbol
            for symbol in item.functions[:8] + item.classes[:6]
            if any(keyword in symbol.lower() for keyword in keywords)
        ]
        if symbol_matches:
            excerpt_lines = [
                stripped
                for stripped in extract_signatures(item)
                if any(symbol in stripped for symbol in symbol_matches)
            ]
            if excerpt_lines:
                return "\n".join(excerpt_lines[:max_lines]), f"Focused excerpt based on matching symbols: {', '.join(symbol_matches[:4])}."
        excerpt, omitted_blob = sanitize_excerpt_lines(item, lines[:max_lines])
        if not excerpt:
            return "<excerpt omitted>", "Opening excerpt omitted because the file content is not useful as readable source."
        reason = "Opening excerpt shown because no focus match was found in the file."
        if omitted_blob:
            reason += " Embedded blob lines were omitted."
        return "\n".join(excerpt), reason

    gathered: list[str] = []
    used: set[int] = set()
    for idx in matches[:8]:
        start = max(0, idx - 2)
        end = min(len(lines), idx + 3)
        for line_no in range(start, end):
            if line_no not in used:
                gathered.append(lines[line_no])
                used.add(line_no)
            if len(gathered) >= max_lines:
                break
        if len(gathered) >= max_lines:
            break
    gathered, omitted_blob = sanitize_excerpt_lines(item, gathered[:max_lines])
    if not gathered:
        return "<excerpt omitted>", "Focused excerpt omitted because the matching content was not useful as readable source."
    reason = f"Focused excerpt based on keywords: {', '.join(keywords[:4])}."
    if omitted_blob:
        reason += " Embedded blob lines were omitted."
    return "\n".join(gathered[:max_lines]), reason
