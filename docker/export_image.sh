#!/usr/bin/env bash
# Build and docker save → submission image tar (DEL-2).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-space-science-agent:latest}"
OUT_DIR="${2:-$ROOT/星海舰队/image}"
IMAGE_NAME="${3:-星海舰队_image.tar}"

bash "$ROOT/sync_from_repo.sh"
bash "$ROOT/docker/build.sh"

ARCH="$(docker image inspect "$TAG" --format '{{.Os}}/{{.Architecture}}')"
if [[ "$ARCH" != "linux/amd64" ]]; then
  echo "ERROR: $TAG is $ARCH; export requires linux/amd64 (x86_64)" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
cp -f "$ROOT/docker/Dockerfile" "$ROOT/docker/docker-compose.yml" "$OUT_DIR/"
docker save -o "$OUT_DIR/$IMAGE_NAME" "$TAG"
echo "Wrote $OUT_DIR/$IMAGE_NAME ($ARCH, $(du -h "$OUT_DIR/$IMAGE_NAME" | awk '{print $1}'))"
