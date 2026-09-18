#!/bin/bash
# Double-click in Finder to start the replay tool; close the Terminal window to stop it.
cd "$(dirname "$0")/.." || exit 1
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3
exec "$PY" replay/serve.py
