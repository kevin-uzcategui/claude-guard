# claude-guard

Watches your **real Claude Code plan limits** (the same ones shown by `/usage`:
5-hour session, weekly global, and weekly per-model) and, when **any** of them
reaches a threshold, runs an action to stop further spend: close Claude Desktop
and the Claude Code plugin, close the editor, suspend, or power off the machine.

It checks every couple of minutes in the background (interval configurable,
2 min in the example configuration). If the API is unavailable, it can use a
recent, verified usage sample from Claude Desktop. If neither source provides
valid data, it records an unhealthy status and does not run the configured action.

> ⚠️ **Unofficial tool.** It reads your own local Claude Code OAuth token to
> call an internal, undocumented usage endpoint, and it can **close apps or
> power off your machine**. Use at your own risk. See [Disclaimer](#disclaimer).

## Requirements

- `jq` and `curl`
  - Linux: `sudo apt install jq curl util-linux` (`util-linux` provides `flock`)
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
claude-guard probe          # check usage without closing apps or powering off
claude-guard now            # run a check and the configured action if needed
claude-guard log            # follow the log live
```

Config changes take effect on the next scheduled check; no restart needed.
You can also edit `~/.config/claude-guard.conf` directly.

## Health and authentication

`claude-guard status` reports the timer state and the last check result
separately. An active timer alone does not mean usage monitoring is working.
Failures return a nonzero exit code so systemd also records them. Health and
the next allowed attempt are stored in `~/.local/state/claude-guard/health.json`,
without credentials. A stale successful reading is flagged in the status.

On Linux, an expired OAuth session is renewed using the existing refresh token.
The credentials file is replaced atomically with mode 0600, preserving unrelated
fields. If Claude Code changes credentials during renewal, its file is kept.
A 401 permits one renewal and one retry. If the refresh grant is rejected,
sign in again in Claude Code with `/login`. On macOS, renew the session in
Claude Code; the guard does not overwrite Keychain credentials.

Both usage and refresh requests respect numeric `Retry-After` headers and use
an exponential retry delay after HTTP 429 (2 minutes initially, up to 32 minutes
unless the server requests longer). Manual checks also respect this delay.
Failed or delayed API checks use the validated Desktop fallback when available.
A rejected fallback never triggers actions based on an old reading. Checks
are serialized; Linux uses `flock` from util-linux.

The parser accepts both the current `limits` array (`kind`, `percent`) and the
older `five_hour` / `seven_day*` objects (`utilization`). Empty or malformed
responses do not trigger actions.

Run the isolated regression tests with:

```bash
python3 -m unittest discover -s tests -v
```

The tests mock HTTP requests and process termination. For a real query without
running the configured action, use `claude-guard probe`.

## Missing usage notifications

The command output and notifications are in English. Other languages are not
currently supported.

After ten minutes without valid usage data from either source, the guard sends
one desktop notification with recovery steps: renew Claude Code with `/login`,
open Desktop Settings > Usage to request a fresh reading, respect any HTTP 429
cooldown, and check `claude-guard probe` and `claude-guard status`. These steps
may not restore access immediately; the guard verifies the next reading.

The notification is persisted once per outage, including manual checks and
restarts. A successful reading clears the episode so a later outage can send
one new notification. Without a successful reading on a new installation, the
ten minutes start at the first failed check. Missing data does not close apps.
`probe` does not send notifications. Change `STALE_NOTIFY_SECONDS` in the config
to adjust the ten-minute default (600 seconds).

## Desktop usage fallback

The primary usage source is the local Claude Code OAuth session. If the API
fails or is in cooldown, the guard reads Desktop's `plan-usage-history.json`:

| Platform | Desktop history path |
|---|---|
| Linux | `~/.config/Claude/plan-usage-history.json` |
| macOS | `~/Library/Application Support/Claude/plan-usage-history.json` |

The account identity comes from Desktop's adjacent `config.json` and the
retained Claude Code identity in `~/.claude.json`. A working API token is not
required for the fallback.

It requires version 2, both global limits, a sample no older than five minutes,
and matching account and organization identifiers. It reads Desktop's data
without changing that session or copying authentication tokens.

The fallback covers the cached five-hour and weekly limits, plus any known
model or surface limits present in the same sample. Desktop history does not
retain arbitrary scoped limits or reset times. Monthly extra-usage spending
is excluded. It is a recent snapshot, not a live server query; a reset after
the sample can make its percentages temporarily outdated.

Desktop may poll every 15 minutes while idle, or pause background polling.
If no new sample arrives within five minutes, the fallback is unavailable.
The guard reports this instead of acting on old data. It does not launch
Desktop or change its polling settings. `claude-guard probe` tests either
source without closing anything. `status` identifies `desktop_cache`, the
sample timestamp, and the primary API result separately.

Fallback success preserves the primary API cooldown and failure count.
The guard resumes the API when that cooldown expires, and gives a successful
API response precedence over the Desktop cache.

For example, a working fallback while OAuth is rate limited appears as:

```text
Health:  ok_desktop
Source:  desktop_cache
Primary API: refresh_rate_limited
```

If the sample expires, `status` warns that it is stale. The next unsuccessful
check reports `desktop_cache_unavailable`. Opening Desktop does not guarantee
continuous coverage: the application must keep updating its history.

## Actions

| Action | What it does | How to recover |
|---|---|---|
| `kill-claude` | Closes Claude Desktop and the Claude Code plugin | Reopen the app or panel |
| `vscode` | Closes the whole editor | Reopen VS Code |
| `poweroff` | Powers off the machine | Turn it back on, then `claude-guard on` |
| `suspend` | Suspends (sleeps) the machine | Wake it, then `claude-guard on` |

`kill-claude` covers the VS Code plugin and Claude Desktop. On Linux,
Desktop is matched by the exact process name `claude-desktop`, restricted to
the current user. On macOS, the main `Claude.app` executable is matched.
Each target receives SIGTERM. After five seconds, a process that remains alive
receives SIGKILL. The guard checks again before reporting success; a target
that stays alive is recorded as `action_failed`. Forced termination can lose
unsaved local work. Standalone Claude Code CLI sessions and Claude in a
browser are outside this action's scope.

Every threshold action disarms the guard before acting and sends one warning.
The timer is disabled; a persistent latch also prevents manual `now` or `check`
commands from repeating the action, even if disabling the timer fails. This
also applies when closing an application fails: inspect `status`, then re-arm
explicitly with `claude-guard on`. `probe` remains available without acting.

> `poweroff` and `suspend` **turn the guard off on their way out**. The limit is
> still exceeded when the machine stops, so a guard left on would power off (or
> re-suspend) the machine again as soon as you brought it back, and you could
> not use it until the limit window rolled over. Once you are back up, switch it
> on again with `claude-guard on`.

## Use cases

**Leave a long task running overnight, then power off.**
You kick off a long autonomous task before bed. Once the plan limit is hit,
Claude can't do more, so there's no point keeping the machine on until morning
Have claude-guard shut it down:

```bash
claude-guard action poweroff
claude-guard 95            # use almost the whole session before acting
claude-guard grace 60      # a minute of warning, just in case
```

It powers off once: the guard turns itself off before shutting down, so you can
boot in the morning and work. Re-arm it with `claude-guard on`.

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
