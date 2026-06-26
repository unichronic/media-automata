#!/usr/bin/env bash
set -Eeuo pipefail

MEDIA_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENWA_DIR="${OPENWA_DIR:-/home/unichronic/OpenWA}"
OPENWA_COMPOSE_FILE="${OPENWA_COMPOSE_FILE:-docker-compose.dev.yml}"
RUN_DIR="${MEDIA_DIR}/runtime/run"
LOG_DIR="${MEDIA_DIR}/runtime/logs"
API_HOST="${MEDIA_AUTOMATA_HOST:-0.0.0.0}"
API_PORT="${MEDIA_AUTOMATA_PORT:-8010}"
API_URL="http://127.0.0.1:${API_PORT}"
MEDIA_WEBHOOK_URL="${MEDIA_AUTOMATA_WEBHOOK_URL:-http://host.docker.internal:${API_PORT}/webhooks/whatsapp}"
OPENWA_URL="${OPENWA_HEALTH_URL:-http://127.0.0.1:2785/api}"
OPENWA_DASHBOARD_URL="${OPENWA_DASHBOARD_URL:-http://127.0.0.1:2886}"
AVD_NAME="${ANDROID_AVD_NAME:-media_automata_native_x86}"
ADB="${ANDROID_ADB_PATH:-/home/unichronic/.android-sdk/platform-tools/adb}"
EMULATOR="${ANDROID_EMULATOR_PATH:-/home/unichronic/.android-sdk/emulator/emulator}"

mkdir -p "$RUN_DIR" "$LOG_DIR"

log() {
  printf '[media-stack] %s\n' "$*"
}

die() {
  printf '[media-stack] ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "Required command is missing: $1"
}

ensure_docker() {
  docker info >/dev/null 2>&1 && return
  if command -v systemctl >/dev/null 2>&1; then
    log "Docker daemon is not running; attempting to start it..."
    sudo -n systemctl start docker >/dev/null 2>&1 || die \
      "Docker daemon is stopped. Run 'sudo systemctl start docker' once, then retry."
  fi
  docker info >/dev/null 2>&1 || die "Docker daemon is unavailable."
}

load_media_env() {
  [[ -f "$MEDIA_DIR/.env" ]] || die "Missing $MEDIA_DIR/.env"
  set -a
  # shellcheck disable=SC1091
  source "$MEDIA_DIR/.env"
  set +a
}

validate_media_env() {
  local missing=()
  local key
  for key in OPENWA_API_KEY OPENWA_SESSION_ID LINKEDIN_EMAIL LINKEDIN_PASSWORD \
    X_LOGIN_IDENTIFIER X_PASSWORD INSTAGRAM_USERNAME INSTAGRAM_PASSWORD; do
    [[ -n "${!key:-}" ]] || missing+=("$key")
  done
  if [[ -z "${MISTRAL_API_KEY:-}${MISTRAL_API_KEYS:-}${MISTRAL_API_KEY1:-}" ]]; then
    missing+=("MISTRAL_API_KEY or MISTRAL_API_KEYS")
  fi
  ((${#missing[@]} == 0)) || die "Missing required .env values: ${missing[*]}"
}

pid_alive() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local pid
  pid="$(cat "$file")"
  kill -0 "$pid" 2>/dev/null
}

start_process() {
  local name="$1"
  shift
  local pid_file="$RUN_DIR/$name.pid"
  local log_file="$LOG_DIR/$name.log"

  if pid_alive "$pid_file"; then
    log "$name already running (PID $(cat "$pid_file"))."
    return
  fi
  rm -f "$pid_file"
  (
    cd "$MEDIA_DIR"
    exec setsid "$@" >>"$log_file" 2>&1
  ) </dev/null &
  local pid=$!
  printf '%s\n' "$pid" >"$pid_file"
  sleep 1
  pid_alive "$pid_file" || {
    tail -n 30 "$log_file" >&2 || true
    die "$name exited during startup."
  }
  log "Started $name (PID $pid)."
}

stop_process() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if ! pid_alive "$pid_file"; then
    rm -f "$pid_file"
    log "$name is not running."
    return
  fi

  local pid
  pid="$(cat "$pid_file")"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.5
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
  fi
  rm -f "$pid_file"
  log "Stopped $name."
}

wait_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  for _ in $(seq 1 "$attempts"); do
    if curl --silent --fail --max-time 3 "$url" >/dev/null; then
      log "$name is ready: $url"
      return 0
    fi
    sleep 2
  done
  die "$name did not become ready: $url"
}

start_openwa() {
  [[ -d "$OPENWA_DIR" ]] || die "OpenWA directory does not exist: $OPENWA_DIR"
  [[ -f "$OPENWA_DIR/$OPENWA_COMPOSE_FILE" ]] || die "Missing OpenWA compose file: $OPENWA_COMPOSE_FILE"
  require_command docker
  ensure_docker
  load_media_env
  validate_media_env

  if curl --silent --fail --max-time 3 "$OPENWA_URL/health" >/dev/null &&
    curl --silent --fail --max-time 3 "$OPENWA_DASHBOARD_URL" >/dev/null; then
    log "OpenWA API and dashboard are already running."
    return
  fi

  log "Starting OpenWA API and dashboard..."
  (
    cd "$OPENWA_DIR"
    API_MASTER_KEY="$OPENWA_API_KEY" docker compose -f "$OPENWA_COMPOSE_FILE" up -d --build openwa dashboard
  )
  wait_http "OpenWA API" "$OPENWA_URL/health" 90
  wait_http "OpenWA dashboard" "$OPENWA_DASHBOARD_URL" 60
}

configure_openwa_webhook() {
  local auth_header=(-H "X-API-Key: $OPENWA_API_KEY")
  local sessions_json session_id webhooks_json

  sessions_json="$(curl --silent --fail "${auth_header[@]}" "$OPENWA_URL/sessions")" ||
    die "Could not list OpenWA sessions."
  session_id="$(
    SESSION_NAME="$OPENWA_SESSION_ID" python -c '
import json, os, sys
payload = json.load(sys.stdin)
items = payload if isinstance(payload, list) else payload.get("data", payload.get("sessions", []))
target = os.environ["SESSION_NAME"]
for item in items:
    if str(item.get("id")) == target or item.get("name") == target:
        print(item["id"])
        break
' <<<"$sessions_json"
  )"
  if [[ -z "$session_id" ]]; then
    log "OpenWA session '$OPENWA_SESSION_ID' does not exist yet."
    log "Create and pair it from $OPENWA_DASHBOARD_URL; rerun '$0 restart' afterward."
    return
  fi

  webhooks_json="$(curl --silent --fail "${auth_header[@]}" "$OPENWA_URL/sessions/$session_id/webhooks")" ||
    die "Could not list webhooks for OpenWA session $session_id."
  if WEBHOOK_URL="$MEDIA_WEBHOOK_URL" python -c '
import json, os, sys
payload = json.load(sys.stdin)
items = payload if isinstance(payload, list) else payload.get("data", payload.get("webhooks", []))
raise SystemExit(0 if any(item.get("url") == os.environ["WEBHOOK_URL"] for item in items) else 1)
' <<<"$webhooks_json"; then
    log "OpenWA webhook is already configured."
    return
  fi

  curl --silent --fail --show-error \
    -X POST "${auth_header[@]}" \
    -H "Content-Type: application/json" \
    "$OPENWA_URL/sessions/$session_id/webhooks" \
    -d "{\"url\":\"$MEDIA_WEBHOOK_URL\",\"events\":[\"message.received\",\"message.sent\"]}" \
    >/dev/null
  log "Configured OpenWA webhook: $MEDIA_WEBHOOK_URL"
}

stop_openwa() {
  (
    cd "$OPENWA_DIR"
    docker compose -f "$OPENWA_COMPOSE_FILE" stop dashboard openwa
  ) >/dev/null 2>&1 || true
  log "Stopped OpenWA containers without deleting session data."
}

detect_android() {
  [[ -x "$ADB" ]] || return 0
  "$ADB" start-server >/dev/null 2>&1 || true

  local serial
  serial="$("$ADB" devices | awk 'NR > 1 && $2 == "device" && $1 ~ /^emulator-/ {print $1; exit}')"
  [[ -n "$serial" ]] || serial="$("$ADB" devices | awk 'NR > 1 && $2 == "device" {print $1; exit}')"
  if [[ -n "$serial" ]]; then
    export ANDROID_DEVICE_SERIAL="${ANDROID_DEVICE_SERIAL:-$serial}"
    log "Using Android device $ANDROID_DEVICE_SERIAL."
    return
  fi

  [[ -x "$EMULATOR" ]] || {
    log "Android emulator is not installed; native Instagram actions will remain unavailable."
    return
  }
  "$EMULATOR" -list-avds | grep -Fxq "$AVD_NAME" || {
    log "Android AVD '$AVD_NAME' is unavailable; native Instagram actions will remain unavailable."
    return
  }

  log "Starting Android AVD $AVD_NAME..."
  nohup setsid "$EMULATOR" -avd "$AVD_NAME" -no-window -no-audio -no-boot-anim \
    -gpu swiftshader_indirect -no-snapshot \
    >>"$LOG_DIR/android-emulator.log" 2>&1 </dev/null &
  printf '%s\n' "$!" >"$RUN_DIR/android-emulator.pid"

  for _ in $(seq 1 90); do
    serial="$("$ADB" devices | awk 'NR > 1 && $2 == "device" && $1 ~ /^emulator-/ {print $1; exit}')"
    [[ -n "$serial" ]] || serial="$("$ADB" devices | awk 'NR > 1 && $2 == "device" {print $1; exit}')"
    if [[ -n "$serial" ]] && [[ "$("$ADB" -s "$serial" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; then
      export ANDROID_DEVICE_SERIAL="$serial"
      log "Android AVD is ready as $serial."
      return
    fi
    sleep 2
  done
  die "Android AVD did not finish booting."
}

start_media() {
  require_command uv
  load_media_env
  validate_media_env
  detect_android

  cd "$MEDIA_DIR"
  uv run python -m media_automata.cli migrate
  uv run python -m media_automata.cli recover-interrupted
  start_process api uv run uvicorn media_automata.api:app --host "$API_HOST" --port "$API_PORT"
  wait_http "Media Automata API" "$API_URL/health" 45
  start_process worker uv run python -m media_automata.cli worker --loop
}

status_process() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if pid_alive "$pid_file"; then
    printf '%-24s running (PID %s)\n' "$name" "$(cat "$pid_file")"
  else
    printf '%-24s stopped\n' "$name"
  fi
}

status() {
  status_process "api"
  status_process "worker"
  if curl --silent --fail --max-time 2 "$OPENWA_URL/health" >/dev/null; then
    printf '%-24s running\n' "openwa-api"
  else
    printf '%-24s unavailable\n' "openwa-api"
  fi
  if curl --silent --fail --max-time 2 "$OPENWA_DASHBOARD_URL" >/dev/null; then
    printf '%-24s running\n' "openwa-dashboard"
  else
    printf '%-24s unavailable\n' "openwa-dashboard"
  fi
  if [[ -x "$ADB" ]]; then
    "$ADB" devices | awk 'NR > 1 && $2 == "device" {devices = devices (devices ? ", " : "") $1} END {if (devices) printf "%-24s running (%s)\n", "android-runtime", devices; else printf "%-24s unavailable\n", "android-runtime"}'
  fi
}

show_logs() {
  local target="${1:-all}"
  touch "$LOG_DIR/api.log" "$LOG_DIR/worker.log" "$LOG_DIR/android-emulator.log"
  case "$target" in
    api) tail -n 200 -f "$LOG_DIR/api.log" ;;
    worker) tail -n 200 -f "$LOG_DIR/worker.log" ;;
    android) tail -n 200 -f "$LOG_DIR/android-emulator.log" ;;
    openwa) (cd "$OPENWA_DIR" && docker compose -f "$OPENWA_COMPOSE_FILE" logs -f --tail=200 openwa dashboard) ;;
    all) tail -n 100 -f "$LOG_DIR/api.log" "$LOG_DIR/worker.log" ;;
    *) die "Unknown log target '$target'. Use: api, worker, android, openwa, all" ;;
  esac
}

start_all() {
  start_openwa
  start_media
  configure_openwa_webhook
  log "Stack is ready."
  log "OpenWA dashboard: $OPENWA_DASHBOARD_URL"
  log "OpenWA API docs:  http://127.0.0.1:2785/api/docs"
  log "Media API:        $API_URL"
  log "Run '$0 status' for component state."
}

stop_all() {
  stop_process worker
  stop_process api
  stop_openwa
}

case "${1:-start}" in
  start) start_all ;;
  stop) stop_all ;;
  restart)
    stop_all
    start_all
    ;;
  status) status ;;
  logs) show_logs "${2:-all}" ;;
  *)
    cat >&2 <<EOF
Usage: $0 {start|stop|restart|status|logs [api|worker|android|openwa|all]}
EOF
    exit 2
    ;;
esac
