"""Compatibility alias: the General Radio CLI became zones/tools/workstation.py.

Scripts and notes that still run `zones/tools/general_radio.py` (or import it) get the Workstation
client and command line; a legacy General Radio board is driven by it just the same.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # loaded by path (tests, other scripts): find the real module
from workstation import *  # noqa: E402,F401,F403
from workstation import main  # noqa: E402,F401

if __name__ == '__main__':
    raise SystemExit(main())
