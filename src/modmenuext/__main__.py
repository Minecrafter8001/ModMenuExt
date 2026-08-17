from __future__ import annotations

import argparse

try:
    from .app import main as run_app
    from .logging_utils import configure_logging, get_logger
except ImportError:
    # PyInstaller can execute this as a top-level script where relative imports are unavailable.
    from modmenuext.app import main as run_app
    from modmenuext.logging_utils import configure_logging, get_logger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="modmenuext")
    parser.add_argument("--log", action="store_true", help="also write logs to modmenu.log")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(write_to_file=args.log)
    get_logger("main").info("Launching application (file_logging=%s)", args.log)
    return run_app()


if __name__ == "__main__":
    raise SystemExit(main())
