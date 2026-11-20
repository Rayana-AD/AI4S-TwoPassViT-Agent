#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
docker build --platform "$PLATFORM" -f "$ROOT/docker/Dockerfile" -t space-science-agent:latest "$ROOT"
ARCH="$(docker image inspect space-science-agent:latest --format '{{.Os}}/{{.Architecture}}')"
echo "Built space-science-agent:latest ($ARCH)"
if [[ "$ARCH" != "$PLATFORM" ]]; then
  echo "ERROR: expected $PLATFORM, got $ARCH" >&2
  exit 1
fi
