#!/usr/bin/env python3
"""PhenomeOne UI Discovery - application entry point (also the PyInstaller entry)."""
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(_here, "src")
if os.path.isdir(_src) and _src not in sys.path:
    sys.path.insert(0, _src)          # running from a source checkout

from p1uid.app import main            # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
