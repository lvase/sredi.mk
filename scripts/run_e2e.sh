#!/bin/sh
set -eu

PROJECT_NAME=opstinski-inbox-e2e
COMPOSE_FILE=docker-compose.e2e.yml

cleanup() {
  docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" down --volumes --remove-orphans
}

trap cleanup EXIT INT TERM
docker compose -p "$PROJECT_NAME" -f "$COMPOSE_FILE" up --build --abort-on-container-exit --exit-code-from e2e-tests
