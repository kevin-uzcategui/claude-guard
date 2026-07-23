#!/usr/bin/env bash
# claude-guard installer. Detects the OS (Linux/macOS), copies the script,
# creates the config if missing, and sets up the scheduler (systemd or launchd).
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
CONF="$HOME/.config/claude-guard.conf"

case "$(uname -s)" in
  Linux)  OS=linux ;;
  Darwin) OS=mac ;;
  *) echo "Unsupported OS: $(uname -s). This installer only covers Linux and macOS."; exit 1 ;;
esac
echo "▶ Detected system: $OS"

# ── Dependencies ─────────────────────────────────────────────────
missing=""
for dep in jq curl; do command -v "$dep" >/dev/null 2>&1 || missing="$missing $dep"; done
if [[ -n "$missing" ]]; then
  echo "✗ Missing dependencies:$missing"
  [[ $OS == mac ]]   && echo "  Install with:  brew install$missing"
  [[ $OS == linux ]] && echo "  Install with:  sudo apt install$missing   (or your package manager)"
  exit 1
fi

# ── Script + config ──────────────────────────────────────────────
mkdir -p "$BIN" "$(dirname "$CONF")"
install -m 0755 "$SRC/claude-guard" "$BIN/claude-guard"
echo "✔ Script installed at $BIN/claude-guard"
if [[ -f "$CONF" ]]; then
  echo "• Config already exists, keeping it: $CONF"
else
  cp "$SRC/claude-guard.conf.example" "$CONF"
  echo "✔ Config created: $CONF"
fi

# ── Migrate away from any legacy (claude-usage-guard) install ─────
if [[ $OS == linux ]]; then
  if systemctl --user list-unit-files 2>/dev/null | grep -q '^claude-usage-guard'; then
    systemctl --user disable --now claude-usage-guard.timer 2>/dev/null || true
    rm -f "$HOME/.config/systemd/user/claude-usage-guard.timer" \
          "$HOME/.config/systemd/user/claude-usage-guard.service"
    echo "• Removed legacy claude-usage-guard units"
  fi
  rm -f "$HOME/.local/bin/claude-usage-guard.sh"
fi

# ── Scheduler ────────────────────────────────────────────────────
if [[ $OS == linux ]]; then
  UNIT_DIR="$HOME/.config/systemd/user"; mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/claude-guard.service" <<EOF
[Unit]
Description=Watch Claude Code usage and act on limit

[Service]
Type=oneshot
ExecStart=%h/.local/bin/claude-guard check
EOF
  cat > "$UNIT_DIR/claude-guard.timer" <<EOF
[Unit]
Description=Periodic Claude Code usage check

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now claude-guard.timer
  loginctl enable-linger "$USER" >/dev/null 2>&1 || \
    echo "  (note: could not enable 'linger'; the guard will only run while you are logged in)"
  echo "✔ systemd timer active (every 1 min)."
else
  LA="$HOME/Library/LaunchAgents"; mkdir -p "$LA"
  PLIST="$LA/com.claude-guard.check.plist"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.claude-guard.check</string>
  <key>ProgramArguments</key>
  <array>
    <string>$BIN/claude-guard</string>
    <string>check</string>
  </array>
  <key>StartInterval</key><integer>60</integer>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load -w "$PLIST"
  echo "✔ launchd LaunchAgent active (every 60s)."
fi

# ── PATH ─────────────────────────────────────────────────────────
case ":$PATH:" in
  *":$BIN:"*) : ;;
  *) echo "⚠ Add $BIN to your PATH. Append to your ~/.bashrc or ~/.zshrc:"
     echo '    export PATH="$HOME/.local/bin:$PATH"' ;;
esac

echo
echo "Done. Check the status with:  claude-guard status"
