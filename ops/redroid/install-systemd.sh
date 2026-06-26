#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root: sudo $0" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

install -m 0644 "$SCRIPT_DIR/binder-linux.modules" /etc/modules-load.d/binder-linux.conf
install -m 0644 "$SCRIPT_DIR/binder-linux.conf" /etc/modprobe.d/binder-linux.conf
chmod +x "$SCRIPT_DIR/start-redroid.sh" "$SCRIPT_DIR/create-container.sh"
install -m 0644 "$SCRIPT_DIR/media-automata-redroid.service" /etc/systemd/system/media-automata-redroid.service

modprobe binder_linux devices=binder,hwbinder,vndbinder || true

if docker ps -a --format '{{.Names}}' | grep -qx media-automata-redroid; then
  docker update --restart unless-stopped media-automata-redroid >/dev/null
fi

systemctl daemon-reload
systemctl enable media-automata-redroid.service
systemctl restart media-automata-redroid.service

echo "Installed and started media-automata-redroid.service"
systemctl --no-pager status media-automata-redroid.service
