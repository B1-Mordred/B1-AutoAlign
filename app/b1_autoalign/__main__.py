"""Launch the B1-AutoAlign desktop application."""

from __future__ import annotations

import argparse
import sys

from PyQt6.QtCore import QTimer

from .ui import create_application


def main() -> int:
    parser = argparse.ArgumentParser(description="B1-AutoAlign desktop control center")
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="open and close the UI automatically without connecting to hardware",
    )
    args, qt_args = parser.parse_known_args()
    application, window = create_application([sys.argv[0], *qt_args])
    window.show()
    if args.smoke_test:
        QTimer.singleShot(250, window.close)
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
