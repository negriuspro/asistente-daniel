#!/usr/bin/env sh
set -eu

docker compose --env-file .env logs -f "${1:-}"
