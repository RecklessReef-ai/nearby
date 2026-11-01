#!/usr/bin/env bash
# Run the page without Docker, for development. AdGuard is not started this way.
set -euo pipefail
cd "$(dirname "$0")/app"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip -q install -r requirements.txt
exec .venv/bin/uvicorn nearby.web:app --host 0.0.0.0 --port 8765 --reload
