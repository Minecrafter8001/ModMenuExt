from __future__ import annotations

import argparse

try:
    from .app import main
    from .logging_utils import configure_logging
except ImportError:
    # PyInstaller can execute this as a top-level script where relative imports are unavailable.
    from modmenuext.app import main
    from modmenuext.logging_utils import configure_logging


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="modmenuext")
    parser.add_argument("--log", action="store_true", help="also write logs to modmenu.log")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    configure_logging(write_to_file=args.log)
    raise SystemExit(main())
