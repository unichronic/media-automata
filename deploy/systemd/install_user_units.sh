#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

mkdir -p "$unit_dir"

for unit in "$repo_dir"/deploy/systemd/media-automata-*.service "$repo_dir"/deploy/systemd/media-automata-*.timer; do
  unit_name="$(basename "$unit")"
  sed "s#/home/unichronic/media_automata#${repo_dir}#g" "$unit" > "$unit_dir/$unit_name"
  echo "Installed $unit_dir/$unit_name"
done

systemctl --user daemon-reload
echo "User units installed. Enable with:"
echo "  systemctl --user enable --now media-automata-redroid.service media-automata-api.service media-automata-worker.service media-automata-monitor.timer"
echo "Optional hourly native check:"
echo "  systemctl --user enable --now media-automata-deep-check.timer"
