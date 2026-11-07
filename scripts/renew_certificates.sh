#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
production_env="${ENV_FILE:-.env.production}"
export ENV_FILE="${production_env}"
compose=(docker compose --env-file "${production_env}" -f docker-compose.prod.yml)
"${compose[@]}" config --quiet
"${compose[@]}" --profile tools run --rm --no-deps certbot
# Certbot returns success even when no renewal was needed; a graceful reload is safe in both cases.
"${compose[@]}" exec -T nginx nginx -t
"${compose[@]}" exec -T nginx nginx -s reload
