#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${REDROID_CONTAINER_NAME:-media-automata-redroid}"
REDROID_IMAGE="${REDROID_IMAGE:-redroid/redroid:11.0.0-latest}"
REDROID_DATA_DIR="${REDROID_DATA_DIR:-/home/unichronic/media_automata/runtime/redroid-data}"
REDROID_WIDTH="${REDROID_WIDTH:-720}"
REDROID_HEIGHT="${REDROID_HEIGHT:-1280}"
REDROID_DPI="${REDROID_DPI:-320}"
REDROID_FPS="${REDROID_FPS:-30}"
ADB_HOST_PORT="${ADB_HOST_PORT:-127.0.0.1:5555}"

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Container '$CONTAINER_NAME' already exists."
  docker update --restart unless-stopped "$CONTAINER_NAME" >/dev/null
  exit 0
fi

mkdir -p "$REDROID_DATA_DIR"

docker run -d \
  --name "$CONTAINER_NAME" \
  --privileged \
  --restart unless-stopped \
  -p "${ADB_HOST_PORT}:5555" \
  -v "${REDROID_DATA_DIR}:/data" \
  "$REDROID_IMAGE" \
  "androidboot.redroid_width=${REDROID_WIDTH}" \
  "androidboot.redroid_height=${REDROID_HEIGHT}" \
  "androidboot.redroid_dpi=${REDROID_DPI}" \
  "androidboot.redroid_fps=${REDROID_FPS}"

echo "Created '$CONTAINER_NAME' with restart policy unless-stopped."
