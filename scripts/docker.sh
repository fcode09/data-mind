#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-up}" in
  init) docker run --rm -v "$PWD:/workspace" -w /workspace python:3.12-slim python scripts/docker_setup.py ;;
  up) docker compose up --build -d --wait --wait-timeout 600 ;;
  down) docker compose down ;;
  logs) docker compose logs -f --tail 100 ;;
  *) echo 'Usage: bash scripts/docker.sh init|up|down|logs'; exit 2 ;;
esac
