"""Exercise the actual shell command against isolated credentials and HTTP mocks."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'claude-guard'


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.creds = self.root / 'credentials.json'
        self.set_creds()
        self.conf = self.root / 'guard.conf'
        self.conf.write_text(f'DESKTOP_DATA_DIR={self.root / "desktop"}\nCLAUDE_IDENTITY={self.root / "identity.json"}\nCREDS={self.creds}\nTHRESHOLD=94\nACTION=kill-claude\nGRACE_SECONDS=0\n')
        self.env = dict(os.environ, CLAUDE_GUARD_CONF=str(self.conf),
                        CLAUDE_GUARD_LOG=str(self.root / 'guard.log'),
                        CLAUDE_GUARD_STATE_DIR=str(self.root / 'state'),
                        FIXTURES=str(self.root), PATH=f'{self.bin}:{os.environ["PATH"]}')
        self.mock('curl', '''#!/usr/bin/env python3
import json, os, pathlib, sys
p=pathlib.Path(os.environ['FIXTURES'])
args=sys.argv[1:]
body=sys.stdin.read()
refresh=args[-1].endswith('/oauth/token')
if '-D' in args: pathlib.Path(args[args.index('-D')+1]).write_text((p/'headers').read_text() if (p/'headers').exists() else '')
with (p/'calls').open('a') as f: f.write(('refresh' if refresh else 'usage')+'\\n')
if refresh:
 assert json.loads(body)['refresh_token']=='old-refresh'
 print((p/'refresh.json').read_text())
else:
 print((p/'usage.json').read_text())
''')
        self.mock('pkill', '''#!/bin/sh
printf '%s\\n' "$*" >> "$FIXTURES/actions"
''')
        self.mock('pgrep', '#!/bin/sh\nexit 1\n')
        self.mock('sleep', '#!/bin/sh\nexit 0\n')
        self.mock('notify-send', '#!/bin/sh\nexit 0\n')
        self.mock('wall', '#!/bin/sh\ncat >/dev/null\n')
        self.usage({'limits': [{'kind': 'session', 'percent': 31}]})
        (self.root / 'refresh.json').write_text(json.dumps({'access_token': 'new-access', 'refresh_token': 'new-refresh', 'expires_in': 3600}) + '\n200')

    def mock(self, name, code):
        p = self.bin / name
        p.write_text(code)
        p.chmod(0o755)

    def set_creds(self, expired=False):
        self.creds.write_text(json.dumps({'unrelated': {'keep': True}, 'claudeAiOauth': {
            'accessToken': 'old-access', 'refreshToken': 'old-refresh',
            'scopes': ['user:profile'], 'expiresAt': int((time.time() + (-60 if expired else 3600)) * 1000),
            'subscriptionType': 'max'}}))

    def usage(self, body, code=200):
        (self.root / 'usage.json').write_text(json.dumps(body) + f'\n{code}')

    def run_guard(self, command='check'):
        return subprocess.run([str(SCRIPT), command], env=self.env, text=True, capture_output=True)

    def health(self):
        return json.loads((self.root / 'state/health.json').read_text())

    def test_current_schema_and_threshold_kills(self):
        self.usage({'limits': [{'kind': 'session', 'percent': 94}]})
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertTrue((self.root / 'actions').exists())
        self.assertEqual(self.health()['status'], 'ok')

    def test_threshold_targets_desktop_and_plugin_only_for_current_user(self):
        self.usage({'limits': [{'kind': 'session', 'percent': 95}]})
        self.assertEqual(self.run_guard().returncode, 0)
        targets = (self.root / 'actions').read_text().splitlines()
        self.assertEqual(len(targets), 2)
        self.assertIn(f'-u {os.getuid()} -x claude-desktop', targets)
        self.assertTrue(any('native-binary/claude' in x for x in targets))

    def test_desktop_still_running_fails_action(self):
        self.usage({'limits': [{'kind': 'session', 'percent': 95}]})
        self.mock('pgrep', '#!/bin/sh\nexit 0\n')
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'action_failed')
        self.assertIn('Claude Desktop still running', (self.root / 'guard.log').read_text())

    def test_desktop_ignoring_sigterm_is_force_closed(self):
        self.usage({'limits': [{'kind': 'session', 'percent': 95}]})
        self.mock('pgrep', """#!/bin/sh
grep -q -- '-KILL' "$FIXTURES/actions" && exit 1
exit 0
""")
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertIn('-KILL', (self.root / 'actions').read_text())
        self.assertIn('SIGKILL required', (self.root / 'guard.log').read_text())

    def test_missing_plugin_does_not_skip_desktop(self):
        self.usage({'limits': [{'kind': 'session', 'percent': 95}]})
        self.mock('pkill', """#!/bin/sh
printf '%s\\n' "$*" >> "$FIXTURES/actions"
case "$*" in *native-binary*) exit 1 ;; esac
""")
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertIn('-x claude-desktop', (self.root / 'actions').read_text())
        self.assertIn('Claude Code plugin not running', (self.root / 'guard.log').read_text())
        self.assertIn('Claude Desktop closed', (self.root / 'guard.log').read_text())

    def test_usage_over_100_still_triggers(self):
        self.usage({'limits': [{'kind': 'session', 'percent': 101}]})
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertTrue((self.root / 'actions').exists())

    def test_probe_never_kills(self):
        self.usage({'limits': [{'kind': 'weekly_all', 'percent': 100}]})
        self.assertEqual(self.run_guard('probe').returncode, 0)
        self.assertFalse((self.root / 'actions').exists())

    def test_legacy_schema_and_null_model(self):
        self.usage({'five_hour': {'utilization': 30}, 'seven_day': {'utilization': 95}, 'seven_day_opus': None})
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertTrue((self.root / 'actions').exists())

    def test_below_threshold_does_not_kill(self):
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertFalse((self.root / 'actions').exists())

    def test_expired_token_refresh_and_preserve_credentials(self):
        self.set_creds(expired=True)
        self.assertEqual(self.run_guard().returncode, 0)
        updated = json.loads(self.creds.read_text())
        self.assertEqual(updated['claudeAiOauth']['accessToken'], 'new-access')
        self.assertEqual(updated['claudeAiOauth']['refreshToken'], 'new-refresh')
        self.assertEqual(updated['unrelated'], {'keep': True})
        self.assertEqual(self.creds.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['refresh', 'usage'])

    def test_refresh_preserves_concurrent_claude_update(self):
        self.set_creds(expired=True)
        curl = self.bin / 'curl'
        code = curl.read_text().replace("assert json.loads(body)['refresh_token']=='old-refresh'", """assert json.loads(body)['refresh_token']=='old-refresh'
 credentials=json.loads((p/'credentials.json').read_text())
 credentials['claudeAiOauth']['accessToken']='claude-updated-access'
 (p/'credentials.json').write_text(json.dumps(credentials))""")
        curl.write_text(code)
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertEqual(json.loads(self.creds.read_text())['claudeAiOauth']['accessToken'], 'claude-updated-access')

    def test_refresh_failure_no_usage_no_action(self):
        self.set_creds(expired=True)
        before = self.creds.read_text()
        (self.root / 'refresh.json').write_text('{}\n400')
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'authentication_error')
        self.assertEqual(before, self.creds.read_text())
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['refresh'])

    def test_rate_limit_respects_retry_after_and_blocks_manual_check(self):
        self.usage({'error': {'type': 'rate_limit_error'}}, 429)
        (self.root / 'headers').write_text('HTTP/2 429\r\nretry-after: 900\r\n')
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertGreaterEqual(self.health()['next_attempt'], int(time.time()) + 899)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['usage'])
        self.assertFalse((self.root / 'actions').exists())

    def test_rate_limit_exponential_backoff(self):
        self.usage({}, 429)
        self.run_guard()
        state = self.health()
        state['next_attempt'] = 0
        (self.root / 'state/health.json').write_text(json.dumps(state))
        self.run_guard()
        state = self.health()
        self.assertEqual(state['next_attempt'] - state['checked_at'], 240)

    def test_malformed_payloads_never_kill(self):
        for body in [{}, {'limits': []}, {'limits': [{'kind': 'session', 'percent': '100'}]}, {'five_hour': {'utilization': -1}}]:
            with self.subTest(body=body):
                (self.root / 'state/health.json').unlink(missing_ok=True)
                self.usage(body)
                self.assertNotEqual(self.run_guard().returncode, 0)
                self.assertEqual(self.health()['status'], 'invalid_response')
                self.assertFalse((self.root / 'actions').exists())

    def test_http_failure_is_not_success(self):
        self.usage({}, 503)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'http_503')

    def test_rejected_token_only_retries_once(self):
        self.usage({}, 401)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'http_401')
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['usage', 'refresh', 'usage'])

    def test_refresh_rate_limit_uses_same_backoff(self):
        self.set_creds(expired=True)
        before = self.creds.read_text()
        (self.root / 'refresh.json').write_text('{}\n429')
        (self.root / 'headers').write_text('HTTP/2 429\r\nRetry-After: 900\r\n')
        self.assertNotEqual(self.run_guard('probe').returncode, 0)
        self.assertEqual(self.health()['status'], 'refresh_rate_limited')
        self.assertGreaterEqual(self.health()['next_attempt'], int(time.time()) + 899)
        self.assertEqual(before, self.creds.read_text())
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['refresh'])

    def test_network_failure_is_visible(self):
        self.mock('curl', '#!/bin/sh\nexit 28\n')
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'network_error')
        self.assertFalse((self.root / 'actions').exists())

    def test_overlapping_check_does_not_query_or_act(self):
        import fcntl
        state_dir = self.root / 'state'
        state_dir.mkdir()
        with (state_dir / 'check.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(self.run_guard().returncode, 0)
        self.assertFalse((self.root / 'calls').exists())
        self.assertFalse((self.root / 'actions').exists())

    def desktop_sample(self, usage=None, age=0, account='account-a', org='org-a'):
        desktop = self.root / 'desktop'
        desktop.mkdir(exist_ok=True)
        (self.root / 'identity.json').write_text(json.dumps({'oauthAccount': {
            'accountUuid': 'account-a', 'organizationUuid': 'org-a'}}))
        (desktop / 'config.json').write_text(json.dumps({'lastKnownAccountUuid': account}))
        sample = {'t': int((time.time() - age) * 1000), 'org': org,
                  'u': usage if usage is not None else {'fh': 12, 'sd': 49}}
        (desktop / 'plan-usage-history.json').write_text(json.dumps({'version': 2, 'samples': [sample]}))

    def test_desktop_fallback_during_rate_limit_keeps_primary_backoff(self):
        self.desktop_sample()
        self.usage({}, 429)
        self.assertEqual(self.run_guard().returncode, 0)
        before = self.health()
        self.assertEqual(before['status'], 'ok_desktop')
        self.assertEqual(before['source'], 'desktop_cache')
        self.assertEqual(before['primary_status'], 'rate_limited')
        self.assertEqual(self.run_guard().returncode, 0)
        after = self.health()
        self.assertEqual(after['next_attempt'], before['next_attempt'])
        self.assertEqual(after['failures'], before['failures'])
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['usage'])
        self.assertFalse((self.root / 'actions').exists())

    def test_desktop_threshold_really_calls_close_action(self):
        self.desktop_sample({'fh': 95, 'sd': 49})
        self.usage({}, 503)
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertIn('-x claude-desktop', (self.root / 'actions').read_text())
        self.assertEqual(self.health()['status'], 'ok_desktop')

    def test_desktop_probe_never_closes(self):
        self.desktop_sample({'fh': 100, 'sd': 49})
        self.usage({}, 503)
        self.assertEqual(self.run_guard('probe').returncode, 0)
        self.assertFalse((self.root / 'actions').exists())

    def test_desktop_ignores_monthly_extra_spending(self):
        self.desktop_sample({'fh': 0, 'sd': 49, 'xu': 100})
        self.usage({}, 503)
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertFalse((self.root / 'actions').exists())

    def test_desktop_available_model_limit_triggers(self):
        self.desktop_sample({'fh': 0, 'sd': 49, 'so': 95})
        self.usage({}, 503)
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertTrue((self.root / 'actions').exists())

    def test_desktop_rejects_untrusted_samples(self):
        cases = [dict(age=301), dict(age=-60), dict(account='other'), dict(org='other'),
                 dict(usage={'fh': 100}), dict(usage={'fh': '100', 'sd': 49}),
                 dict(usage={'fh': -1, 'sd': 49}), dict(usage={'fh': 0, 'sd': 49, 'so': '100'})]
        for sample in cases:
            with self.subTest(sample=sample):
                (self.root / 'state/health.json').unlink(missing_ok=True)
                self.desktop_sample(**sample)
                self.usage({}, 503)
                self.assertNotEqual(self.run_guard().returncode, 0)
                self.assertEqual(self.health()['status'], 'http_503')
                self.assertFalse((self.root / 'actions').exists())

    def test_desktop_stale_fallback_stops_reporting_healthy(self):
        self.desktop_sample()
        self.usage({}, 429)
        self.assertEqual(self.run_guard().returncode, 0)
        before = self.health()['next_attempt']
        self.desktop_sample(age=301)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'desktop_cache_unavailable')
        self.assertEqual(self.health()['next_attempt'], before)

    def test_primary_recovery_takes_precedence_over_desktop(self):
        self.desktop_sample({'fh': 100, 'sd': 49})
        self.usage({'limits': [{'kind': 'session', 'percent': 12}]})
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['source'], 'oauth')
        self.assertFalse((self.root / 'actions').exists())

    def test_desktop_fallback_when_refresh_is_rate_limited(self):
        self.set_creds(expired=True)
        self.desktop_sample()
        (self.root / 'refresh.json').write_text('{}\n429')
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'ok_desktop')
        self.assertEqual(self.health()['primary_status'], 'refresh_rate_limited')
        self.assertEqual((self.root / 'calls').read_text().splitlines(), ['refresh'])

    def test_desktop_action_failure_preserves_primary_cooldown(self):
        self.desktop_sample({'fh': 95, 'sd': 49})
        self.usage({}, 429)
        self.mock('pgrep', '#!/bin/sh\nexit 0\n')
        self.assertNotEqual(self.run_guard().returncode, 0)
        state = self.health()
        self.assertEqual(state['status'], 'action_failed')
        self.assertEqual(state['primary_status'], 'rate_limited')
        self.assertEqual(state['source'], 'desktop_cache')
        self.assertEqual(state['failures'], 1)

    def test_desktop_newest_organization_wins_over_old_matching_sample(self):
        self.desktop_sample()
        p = self.root / 'desktop/plan-usage-history.json'
        data = json.loads(p.read_text())
        data['samples'].append(dict(data['samples'][0], org='other'))
        p.write_text(json.dumps(data))
        self.usage({}, 503)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertFalse((self.root / 'actions').exists())

    def test_desktop_unknown_history_version_is_rejected(self):
        self.desktop_sample({'fh': 100, 'sd': 49})
        p = self.root / 'desktop/plan-usage-history.json'
        data = json.loads(p.read_text())
        data['version'] = 3
        p.write_text(json.dumps(data))
        self.usage({}, 503)
        self.assertNotEqual(self.run_guard().returncode, 0)
        self.assertFalse((self.root / 'actions').exists())

    def test_desktop_fallback_when_no_oauth_token(self):
        self.creds.unlink()
        self.desktop_sample()
        self.assertEqual(self.run_guard().returncode, 0)
        self.assertEqual(self.health()['status'], 'ok_desktop')
        self.assertFalse((self.root / 'calls').exists())

    def test_secrets_never_logged(self):
        self.set_creds(expired=True)
        self.run_guard()
        output = (self.root / 'guard.log').read_text() + (self.root / 'state/health.json').read_text()
        self.assertNotIn('old-refresh', output)
        self.assertNotIn('new-access', output)


if __name__ == '__main__':
    unittest.main()
