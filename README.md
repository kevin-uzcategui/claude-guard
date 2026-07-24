# claude-guard

Watches your **real Claude Code plan limits** (the same ones shown by `/usage`:
5-hour session, weekly global, and weekly per-model) and, when **any** of them
reaches a threshold, runs an action to stop further spend: close Claude Code,
close the editor, suspend, or power off the machine.

It checks every couple of minutes in the background (interval configurable,
2 min by default). If it can't read your usage with confidence (expired token,
no internet), it **does nothing** — it never acts blind.

> ⚠️ **Unofficial tool.** It reads your own local Claude Code OAuth token to
> call an internal, undocumented usage endpoint, and it can **close apps or
> power off your machine**. Use at your own risk. See [Disclaimer](#disclaimer).

## Requirements

- `jq` and `curl`
  - Linux: `sudo apt install jq curl` (or your package manager)
  - macOS: `brew install jq` (curl is already there)
- Claude Code installed and signed in (that's where the token comes from).

## Install

```bash
git clone https://github.com/<you>/claude-guard.git
cd claude-guard
./install.sh
```

The installer detects your OS and sets up the right scheduler
(**systemd** on Linux, **launchd** on macOS). Make sure `~/.local/bin` is on
your `PATH`.

## Usage

```bash
claude-guard status         # config + guard state + recent checks
claude-guard 50             # set the threshold to 50% (1–100)
claude-guard action vscode  # kill-claude | vscode | poweroff | suspend
claude-guard grace 15       # seconds of warning before acting
claude-guard interval 2m    # how often to check (90s | 2m | 1h, min 30s)
claude-guard off / on       # turn the guard off / on
claude-guard now            # run a check right now
claude-guard log            # follow the log live
```

Config changes take effect on the next check (≤ 1 min); no restart needed.
You can also edit `~/.config/claude-guard.conf` directly.

## Actions

| Action | What it does | How to recover |
|---|---|---|
| `kill-claude` | Closes only the Claude Code plugin | Reopen the panel |
| `vscode` | Closes the whole editor | Reopen VS Code |
| `poweroff` | Powers off the machine | Turn it back on |
| `suspend` | Suspends (sleeps) the machine | Wake it |

> With `kill-claude`, if you're still above the threshold the guard will close
> it again every minute. To keep working: lower the threshold or run
> `claude-guard off`.

## Use cases

**Leave a long task running overnight, then power off.**
You kick off a long autonomous task before bed. Once the plan limit is hit,
Claude can't do more, so there's no point keeping the machine on until morning
— have claude-guard shut it down:

```bash
claude-guard action poweroff
claude-guard 95            # use almost the whole session before acting
claude-guard grace 60      # a minute of warning, just in case
```

**Step away while Claude works (AFK).**
You leave Claude on a task and go do something else. When the limit is reached,
just stop Claude so it doesn't keep hammering the API (and eating your weekly
allowance) — the machine stays on and everything else keeps running:

```bash
claude-guard action kill-claude   # the default
claude-guard 90
```

**Laptop on battery.**
Same as AFK, but sleep the machine to save battery instead of only closing
Claude:

```bash
claude-guard action suspend
```

## Uninstall

```bash
./uninstall.sh
```

## Platform notes

- **Linux**: tested. Token read from `~/.claude/.credentials.json`.
- **macOS**: the token is read from the **Keychain**. The first time, the
  system may ask permission for `claude-guard` to access the Keychain — allow
  it. The Keychain item name can vary between Claude Code versions; if
  `claude-guard now` logs *"could not read the OAuth token"*, adjust the item
  name in the `get_token` function.

## Disclaimer

This project is **not affiliated with or endorsed by Anthropic**. It relies on
the `/api/oauth/usage` endpoint used internally by Claude Code, which is
undocumented and may change or stop working at any time — in which case the
guard logs the error and does nothing. The `poweroff`/`suspend` actions affect
your whole machine and the `kill-claude`/`vscode` actions close running apps,
which may cause you to lose unsaved work. Review the code, pick your action
consciously, and use at your own risk. Provided "as is", without warranty.

## License

MIT — see [LICENSE](LICENSE).
