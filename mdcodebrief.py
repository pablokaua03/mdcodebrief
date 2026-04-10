"""
mdcodebrief — MD Code Brief
Scans an entire project and generates a structured .md file
with full code context, ideal for AI models.

Author: https://github.com/pablokaua03
Repository: https://github.com/pablokaua03/mdcodebrief
License: MIT

Usage:
    GUI:  python mdcodebrief.py
    CLI:  python mdcodebrief.py <project_path> [options]
"""

import sys


def main() -> None:
    if len(sys.argv) > 1:
        from cli import run_cli
        run_cli()
    else:
        from ui import App
        app = App()
        app.mainloop()


if __name__ == "__main__":
    main()
