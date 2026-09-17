#!/bin/zsh
cd -- "${0:A:h}"
exec ../../pairing_station/.venv/bin/python app.py "$@"
