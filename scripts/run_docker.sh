#!/usr/bin/env bash
# Start the complete AIOps Sentinel Docker stack.
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

docker compose up --build "$@"
