#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .env ]]; then set -a; source .env; set +a; fi
case "${1:-api}" in
 api|mcp|worker) service=${1:-api}; if [[ $# -gt 0 ]]; then shift; fi; exec go run "./apps/$service" "$@" ;;
 voice) exec python -m uvicorn apps.voice.main:app --host 127.0.0.1 --port 8102 ;;
 web) cd apps/web; exec npm run dev -- --host 127.0.0.1 ;;
 *) echo "Usage: scripts/dev.sh api|mcp|worker|voice|web [arguments]"; exit 2 ;;
esac
