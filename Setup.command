#!/bin/zsh
cd -- "${0:A:h}"
if command -v python3.14 >/dev/null 2>&1; then
  python3.14 scripts/setup.py
else
  python3 scripts/setup.py
fi
