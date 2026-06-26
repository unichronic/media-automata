#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${REDROID_CONTAINER_NAME:-media-automata-redroid}"
ADB_PATH="${ANDROID_ADB_PATH:-/home/unichronic/.android-sdk/platform-tools/adb}"
ADB_ENDPOINT="${ANDROID_ADB_ENDPOINT:-127.0.0.1:5555}"
BOOT_TIMEOUT_SECONDS="${REDROID_BOOT_TIMEOUT_SECONDS:-120}"

load_binder_module() {
  if lsmod | grep -q '^binder_linux'; then
    return 0
  fi
  modprobe binder_linux devices=binder,hwbinder,vndbinder
}

ensure_docker() {
  if systemctl is-active --quiet docker; then
    return 0
  fi
  systemctl start docker
}

ensure_container_running() {
  if ! docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    echo "ReDroid container '$CONTAINER_NAME' not found. Run ops/redroid/create-container.sh first." >&2
    exit 1
  fi
  if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    return 0
  fi
  docker start "$CONTAINER_NAME" >/dev/null
}

wait_for_adb() {
  local deadline=$((SECONDS + BOOT_TIMEOUT_SECONDS))
  while ((SECONDS < deadline)); do
    "$ADB_PATH" connect "$ADB_ENDPOINT" >/dev/null 2>&1 || true
    local state
    state=$("$ADB_PATH" -s "$ADB_ENDPOINT" get-state 2>/dev/null || true)
    if [[ "$state" == "device" ]]; then
      local boot
      boot=$("$ADB_PATH" -s "$ADB_ENDPOINT" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')
      if [[ "$boot" == "1" ]]; then
        return 0
      fi
    fi
    sleep 2
  done
  echo "ReDroid did not become ADB-ready within ${BOOT_TIMEOUT_SECONDS}s" >&2
  return 1
}

load_binder_module
ensure_docker
ensure_container_running
wait_for_adb
