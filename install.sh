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

# ── Scheduler (built from the config interval, delegated to the binary) ──
"$BIN/claude-guard" sync-scheduler
"$BIN/claude-guard" on >/dev/null
if [[ $OS == linux ]]; then
  loginctl enable-linger "$USER" >/dev/null 2>&1 || \
    echo "  (note: could not enable 'linger'; the guard will only run while you are logged in)"
fi
interval=$(grep -E '^INTERVAL_SECONDS=' "$CONF" | tail -1 | cut -d= -f2)
echo "✔ Guard active (checks every ${interval:-60}s)."

# ── PATH ─────────────────────────────────────────────────────────
case ":$PATH:" in
  *":$BIN:"*) : ;;
  *) echo "⚠ Add $BIN to your PATH. Append to your ~/.bashrc or ~/.zshrc:"
     echo '    export PATH="$HOME/.local/bin:$PATH"' ;;
esac

echo
echo "Done. Check the status with:  claude-guard status"
