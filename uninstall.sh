#!/usr/bin/env bash
# Uninstall claude-guard: stop the scheduler and remove the files.
# Keeps the log (~/.local/state/claude-guard.log) in case you want to review it.
set -euo pipefail

case "$(uname -s)" in Linux) OS=linux ;; Darwin) OS=mac ;; *) OS=other ;; esac

if [[ $OS == linux ]]; then
  systemctl --user disable --now claude-guard.timer 2>/dev/null || true
  rm -f "$HOME/.config/systemd/user/claude-guard.timer" \
        "$HOME/.config/systemd/user/claude-guard.service"
  systemctl --user daemon-reload 2>/dev/null || true
elif [[ $OS == mac ]]; then
  PLIST="$HOME/Library/LaunchAgents/com.claude-guard.check.plist"
  launchctl unload -w "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
fi

rm -f "$HOME/.local/bin/claude-guard"
echo "✔ claude-guard uninstalled."
echo "• Config kept: $HOME/.config/claude-guard.conf (delete it by hand if you want)"
echo "• Log kept:    $HOME/.local/state/claude-guard.log"
