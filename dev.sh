#!/usr/bin/env bash
# Local dev wrapper: ./dev.sh <command> [args]   (see src/m4l/cli.py)
#
#   ./dev.sh setup                      create .venv with runtime + dev deps
#   ./dev.sh test                       Python + JS unit tests
#   ./dev.sh browser-test               headless-Chrome smoke test of ./public
#   ./dev.sh fetch 2026-08-06           fetch + parse one drawing (prints, saves nothing)
#   ./dev.sh scrape [--date D] [--full] incremental scrape into ./data, rebuild ./public
#   ./dev.sh build | stats | serve
#   ./dev.sh check 2026-08-06 7 20 42 48 51 3
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python

case "${1:-}" in
  setup)
    uv venv -q --python 3.14 .venv
    uv pip install -q --python "$PY" -e ".[dev]"
    ;;
  test)
    "$PY" -m pytest -q
    node --test tests/js/checker.test.mjs
    ;;
  browser-test)
    node tests/js/browser-smoke.mjs public screenshots
    ;;
  *)
    PYTHONPATH=src exec "$PY" -m m4l.cli "$@"
    ;;
esac
