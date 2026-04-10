# Changelog

All notable changes to this project will be documented in this file.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/)
Versioning: [Semantic Versioning](https://semver.org/)

---

## [1.3.0] — 2025-04-10

### Changed
- **Modular architecture** — split into `scanner.py`, `renderer.py`, `theme.py`, `ui.py`, `cli.py`; `mdcodebrief.py` is now a clean 20-line entry point
- **Improved `.gitignore` parser** — now supports negation (`!`), rooted patterns (`/build`), directory-only patterns (`dist/`), and `**` wildcards
- **Version consistency** — `__version__` unified across all modules

### Added
- **33 unit tests** — covering scanner, renderer, gitignore parser, token estimation, and tree building (`unittest`, zero extra dependencies)
- Screenshot added to README with download button

### Fixed
- Windows SmartScreen false positive — removed `--add-data` from build scripts (`--noupx` retained)

---

## [1.2.0] — 2025-04-10

### Added
- Dark / Light theme toggle (instant switch, no rebuild)
- Pill-style toggle switches replacing checkboxes
- Two-column layout (AI Instruction + Options side by side)
- Status pill indicator (shows Scanning… / Done ✓ / Error)

### Fixed
- White Entry field on Windows (readonly state color bug)
- Progress bar style name incompatible with Python 3.14

---

## [1.1.0] — 2025-04-10

### Added
- Native `.gitignore` support
- Copy to clipboard — GUI button + `--copy` / `-c` CLI flag
- Token estimation with model hints in log and footer
- Git diff mode — `--diff` and `--staged` flags
- AI instruction injection — GUI text field + `-p / --prompt` CLI flag
- Build scripts (`build.bat`, `build.sh`)

---

## [1.0.0] — 2025-04-10

### Added
- GUI with dark theme (tkinter, zero dependencies)
- CLI mode
- Recursive project scanner with smart filtering
- ASCII directory tree
- Syntax-highlighted code blocks for 50+ extensions
- Multi-encoding file reader (UTF-8, latin-1, cp1252, UTF-16)
- Safety limits: 1 000 lines/file, 2 000 files/scan
- Cross-platform Desktop path detection
- MIT License
