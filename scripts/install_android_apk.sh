#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/app.apk" >&2
  exit 2
fi

apk_path="$1"
if [[ ! -f "$apk_path" ]]; then
  echo "APK not found: $apk_path" >&2
  exit 2
fi

adb="${ANDROID_ADB_PATH:-/home/unichronic/.android-sdk/platform-tools/adb}"
endpoint="${ANDROID_ADB_ENDPOINT:-127.0.0.1:5555}"
serial="${ANDROID_DEVICE_SERIAL:-$endpoint}"

if [[ -z "${ANDROID_DEVICE_SERIAL:-}" ]]; then
  "$adb" connect "$endpoint" >/dev/null
fi

"$adb" -s "$serial" install -r "$apk_path"
