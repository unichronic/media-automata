#!/usr/bin/env bash
set -euo pipefail

name="${REDROID_CONTAINER:-media-automata-redroid}"
image="${REDROID_IMAGE:-redroid/redroid:11.0.0-latest}"
data_dir="${REDROID_DATA_DIR:-$PWD/runtime/redroid-data}"
adb_port="${REDROID_ADB_PORT:-5555}"
adb_path="${ANDROID_ADB_PATH:-${ADB_PATH:-/home/unichronic/.android-sdk/platform-tools/adb}}"
if [[ ! -x "$adb_path" ]]; then
  adb_path="${ADB_PATH:-adb}"
fi

mkdir -p "$data_dir"

if ! grep -Eq '^nodev[[:space:]]+binder$' /proc/filesystems 2>/dev/null; then
  echo "Loading binder_linux host module for ReDroid..."
  docker run --rm \
    --privileged \
    --pid=host \
    -v /:/host \
    python:3.11-slim \
    chroot /host /sbin/modprobe binder_linux devices=binder,hwbinder,vndbinder
fi

echo "Ensuring host binderfs device nodes exist..."
docker run --rm \
  --privileged \
  --pid=host \
  -v /:/host \
  python:3.11-slim \
  chroot /host /usr/bin/nsenter --mount=/proc/1/ns/mnt -- /bin/sh -lc '
    mkdir -p /dev/binderfs
    mountpoint -q /dev/binderfs || mount -t binder binder /dev/binderfs
    chmod 666 /dev/binderfs/binder /dev/binderfs/hwbinder /dev/binderfs/vndbinder
    ln -sf /dev/binderfs/binder /dev/binder
    ln -sf /dev/binderfs/hwbinder /dev/hwbinder
    ln -sf /dev/binderfs/vndbinder /dev/vndbinder
  '

wait_for_adb() {
  local endpoint="127.0.0.1:${adb_port}"
  local attempt state
  "$adb_path" disconnect "$endpoint" >/dev/null 2>&1 || true
  for attempt in $(seq 1 20); do
    "$adb_path" connect "$endpoint" >/dev/null 2>&1 || true
    state="$("$adb_path" -s "$endpoint" get-state 2>/dev/null || true)"
    if [[ "$state" == "device" ]]; then
      echo "ADB device is ready at $endpoint."
      return 0
    fi
    sleep 3
  done
  echo "ADB device did not become ready at $endpoint." >&2
  return 1
}

if docker ps --format '{{.Names}}' | grep -qx "$name"; then
  echo "$name is already running; checking ADB health."
  if wait_for_adb; then
    exit 0
  fi
  echo "$name is running but ADB is unhealthy; restarting container."
  docker restart "$name" >/dev/null
  wait_for_adb
  exit 0
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$name"; then
  docker rm "$name" >/dev/null
fi

docker run -d \
  --name "$name" \
  --privileged \
  -p "127.0.0.1:${adb_port}:5555" \
  -v "$data_dir:/data" \
  "$image" \
  androidboot.redroid_width=720 \
  androidboot.redroid_height=1280 \
  androidboot.redroid_dpi=320 \
  androidboot.redroid_fps=30

echo "Started $name from $image."
echo "ADB endpoint: 127.0.0.1:${adb_port}"
wait_for_adb
