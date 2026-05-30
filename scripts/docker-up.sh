#!/usr/bin/env sh
set -eu

docker compose --env-file .env up -d --build
