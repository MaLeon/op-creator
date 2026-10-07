#!/usr/bin/env python3
"""Run as a non-root Linux user; real flock/stat/ss parsing and fake native CLIs."""
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'bin/openclaw-instance'


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='oci-test-')
        self.home = Path(self.temp.name)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        for command in ('openclaw', 'systemctl', 'loginctl', 'ss'):
            (self.bin / command).symlink_to(ROOT / 'tests/fake_cli.py')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('OPENCLAW_', 'XDG_'))}
        self.env.update(HOME=str(self.home), PATH=f'{self.bin}:{os.environ["PATH"]}')
        self.manager = self.home / '.local/state/openclaw-instance-manager'
        self.registry = self.manager / 'instances.json'

    def tearDown(self):
        self.temp.cleanup()

    def run_cli(self, *args, ok=True, extra=None):
        result = subprocess.run([str(SCRIPT), *args], env=self.env | (extra or {}),
                                capture_output=True, text=True, timeout=110)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('secret-from-upstream-must-not-leak', result.stdout + result.stderr)
        return result

    def entries(self):
        return json.loads(self.registry.read_text())['instances']

    def config(self, name='alpha'):
        return self.home / f'.openclaw-{name}/openclaw.json'

    def edit_config(self, fn, name='alpha'):
        path = self.config(name)
        value = json.loads(path.read_text())
        fn(value)
        path.write_text(json.dumps(value))

    def test_preflight_is_read_only(self):
        result = self.run_cli('preflight')
        self.assertTrue(json.loads(result.stdout)['ok'])
        self.assertFalse(self.manager.exists())
        self.assertEqual(json.loads(self.run_cli('list', '--json').stdout), [])

    def test_create_and_idempotence(self):
        result = self.run_cli('create', 'alpha')
        config = self.config().read_text()
        token = json.loads(config)['gateway']['auth']['token']
        self.assertEqual(len(token), 64)
        self.assertNotIn(token, result.stdout + result.stderr + self.registry.read_text())
        self.run_cli('create', 'alpha')
        self.assertEqual(config, self.config().read_text())
        self.assertEqual(self.entries()['alpha']['port'], 19000)
        self.assertEqual(self.registry.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.manager.stat().st_mode & 0o777, 0o700)

    def test_lifecycle_and_remove_restore(self):
        self.run_cli('create', 'alpha')
        self.run_cli('stop', 'alpha')
        status = json.loads(self.run_cli('status', 'alpha', '--json').stdout)
        self.assertEqual(status['serviceStatus'], 'inactive')
        self.run_cli('start', 'alpha')
        self.run_cli('restart', 'alpha')
        self.run_cli('doctor', 'alpha')
        self.assertIn('gateway started', self.run_cli('logs', 'alpha').stdout)
        original = self.config().read_text()
        self.run_cli('remove', 'alpha')
        self.assertEqual(self.entries()['alpha']['state'], 'removed')
        self.run_cli('create', 'bravo')
        self.assertEqual(self.entries()['bravo']['port'], 19200)
        self.run_cli('start', 'alpha')
        self.assertEqual(original, self.config().read_text())

    def test_ports_and_stopped_reservations(self):
        self.run_cli('create', 'alpha', extra={'FAKE_PORTS': '19110'})
        self.assertEqual(self.entries()['alpha']['port'], 19200)
        self.run_cli('stop', 'alpha')
        self.run_cli('create', 'bravo', extra={'FAKE_PORTS': '19000'})
        self.assertEqual(self.entries()['bravo']['port'], 19400)
        self.run_cli('start', 'alpha', ok=False, extra={'FAKE_PORTS': '19201'})

    def test_existing_unmanaged_config_untouched(self):
        path = self.home / '.openclaw-legacy'
        path.mkdir()
        data = '{"gateway":{"port":19000},"browser":{"profiles":{"x":{"cdpPort":19255}}}}'
        (path / 'openclaw.json').write_text(data)
        self.run_cli('create', 'alpha')
        self.assertEqual(self.entries()['alpha']['port'], 19400)
        self.assertEqual((path / 'openclaw.json').read_text(), data)
        self.run_cli('purge', 'legacy', '--confirm', 'legacy', ok=False)

    def test_unknown_browser_and_malformed_port_block_allocation(self):
        path = self.home / '.openclaw-legacy'
        path.mkdir()
        config = path / 'openclaw.json'
        config.write_text(json.dumps({'gateway': {'port': 19000},
                                      'browser': {'cdpUrl': 'http://unknown-host:9222'}}))
        self.run_cli('create', 'alpha', ok=False)
        self.assertEqual(self.entries(), {})
        sentinel = self.home / 'must-not-exist'
        config.write_text(json.dumps({'gateway': {'port': f'x[$(touch {sentinel})]'}}))
        self.run_cli('create', 'alpha', ok=False)
        self.assertEqual(self.entries(), {})
        self.assertFalse(sentinel.exists())

    def test_custom_browser_range_reserved(self):
        path = self.home / '.openclaw-legacy'
        path.mkdir()
        (path / 'openclaw.json').write_text(json.dumps({'gateway': {'port': 18000},
           'browser': {'cdpPortRangeStart': 19001, 'cdpPortRangeEnd': 19401}}))
        self.run_cli('create', 'alpha')
        self.assertEqual(self.entries()['alpha']['port'], 19600)

    def test_concurrent_first_creates(self):
        jobs = [subprocess.Popen([str(SCRIPT), 'create', name], env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                for name in ('alpha', 'bravo')]
        for job in jobs:
            out, err = job.communicate(timeout=90)
            self.assertEqual(job.returncode, 0, out + err)
        self.assertEqual({v['port'] for v in self.entries().values()}, {19000, 19200})
        tokens = [json.loads(self.config(n).read_text())['gateway']['auth']['token']
                  for n in ('alpha', 'bravo')]
        self.assertNotEqual(*tokens)

    def test_concurrent_same_name(self):
        jobs = [subprocess.Popen([str(SCRIPT), 'create', 'alpha'], env=self.env,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        for job in jobs:
            out, err = job.communicate(timeout=90)
            self.assertEqual(job.returncode, 0, out + err)
        self.assertEqual(len(self.entries()), 1)

    def test_invalid_names_and_environment(self):
        for name in ('default', 'dev', '../oops', 'A', '-a', 'a'*33):
            self.run_cli('create', name, ok=False)
        self.run_cli('create', 'alpha', ok=False, extra={'OPENCLAW_STATE_DIR': '/tmp/secret-value'})
        self.run_cli('create', 'alpha', ok=False, extra={'FAKE_NO_LINGER': '1'})
        self.assertFalse(self.manager.exists())

    def test_corrupt_or_missing_registry_blocks_mutation(self):
        self.run_cli('create', 'alpha')
        self.registry.write_text('{broken')
        self.run_cli('create', 'bravo', ok=False)
        self.registry.unlink()
        self.run_cli('create', 'bravo', ok=False)
        self.assertTrue(self.config().exists())

    def test_registry_write_failure(self):
        self.run_cli('create', 'alpha')
        before = self.registry.read_text()
        self.manager.chmod(0o500)
        try:
            self.run_cli('create', 'bravo', ok=False)
            self.assertEqual(before, self.registry.read_text())
            self.assertFalse(self.config('bravo').exists())
        finally:
            self.manager.chmod(0o700)

    def test_creation_failure_preserves_and_cleanup(self):
        for index, phase in enumerate(('setup', 'patch', 'validate', 'install')):
            name = f'failed-{phase}'
            self.run_cli('create', name, ok=False, extra={'FAKE_FAIL': phase})
            self.assertEqual(self.entries()[name]['state'], 'failed')
            self.assertEqual(self.entries()[name]['port'], 19000 + 200 * index)
            self.assertTrue(self.config(name).exists())
            self.run_cli('create', name, ok=False)
        self.assertEqual(json.loads((self.home / '.fake/services.json').read_text()), {})

    def test_failed_baseline_can_purge(self):
        self.run_cli('create', 'alpha', ok=False, extra={'FAKE_FAIL': 'setup'})
        self.run_cli('purge', 'alpha', '--confirm', 'alpha')
        self.assertEqual(self.entries(), {})

    def test_stop_and_uninstall_failure_preserve_data(self):
        self.run_cli('create', 'alpha')
        for phase in ('stop', 'uninstall'):
            self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False, extra={'FAKE_FAIL': phase})
            self.assertTrue(self.config().exists())
            self.assertIn('alpha', self.entries())
        self.run_cli('purge', 'alpha', '--confirm', 'alpha')
        self.assertEqual(self.entries(), {})

    def test_config_and_service_drift(self):
        self.run_cli('create', 'alpha')
        original = self.config().read_text()
        self.edit_config(lambda x: x['gateway'].update(port=22000))
        self.run_cli('restart', 'alpha', ok=False)
        self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False)
        self.config().write_text(original)
        unit = self.home / '.config/systemd/user/openclaw-gateway-alpha.service'
        unit.write_text(unit.read_text()+'# edited\n')
        self.run_cli('stop', 'alpha', ok=False)
        self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False)

    def test_symlink_and_external_workspace_refused(self):
        self.run_cli('create', 'alpha')
        self.edit_config(lambda x: x['agents']['defaults'].update(workspace='/tmp/elsewhere'))
        self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False)
        root = self.home / '.openclaw-alpha'
        renamed = self.home / 'renamed'
        root.rename(renamed)
        root.symlink_to(renamed)
        self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False)
        self.assertTrue((renamed / 'openclaw.json').exists())

    def test_purge_does_not_follow_internal_symlinks(self):
        self.run_cli('create', 'alpha')
        external = self.home / 'keep'
        external.mkdir()
        (external / 'sentinel').write_text('keep')
        (self.home / '.openclaw-alpha/workspace/link').symlink_to(external)
        self.run_cli('purge', 'alpha', '--confirm', 'wrong', ok=False)
        self.run_cli('purge', 'alpha', '--confirm', 'alpha')
        self.assertEqual((external / 'sentinel').read_text(), 'keep')

    def test_noninteractive_configure(self):
        self.run_cli('create', 'alpha')
        self.run_cli('configure', 'alpha', ok=False)

    def test_partial_deletion_is_retryable(self):
        self.run_cli('create', 'alpha')
        stuck = self.home / '.openclaw-alpha/workspace/stuck'
        stuck.mkdir()
        (stuck / 'file').write_text('data')
        stuck.chmod(0o500)
        try:
            self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False)
            self.assertEqual(self.entries()['alpha']['state'], 'deleting')
            self.assertTrue((self.home / '.openclaw-alpha/.instance-manager-owner').exists())
        finally:
            stuck.chmod(0o700)
        self.run_cli('purge', 'alpha', '--confirm', 'alpha')
        self.assertNotIn('alpha', self.entries())

    def test_failed_purge_of_partial_creation_retries(self):
        self.run_cli('create', 'alpha', ok=False, extra={'FAKE_FAIL': 'setup'})
        self.run_cli('purge', 'alpha', '--confirm', 'alpha', ok=False,
                     extra={'FAKE_PORTS': '19001'})
        self.run_cli('purge', 'alpha', '--confirm', 'alpha')

    def test_health_failure_preserves_data_and_uninstalls_service(self):
        start = time.monotonic()
        self.run_cli('create', 'alpha', ok=False, extra={'FAKE_FAIL': 'health'})
        elapsed = time.monotonic()-start
        self.assertGreater(elapsed, 59)
        self.assertLess(elapsed, 85)
        self.assertEqual(self.entries()['alpha']['lastError']['stage'], 'checking-health')
        self.assertTrue(self.config().exists())
        self.assertEqual(json.loads((self.home / '.fake/services.json').read_text()), {})

    def test_failed_reinstall_can_recover(self):
        self.run_cli('create', 'alpha')
        self.run_cli('remove', 'alpha')
        self.run_cli('start', 'alpha', ok=False, extra={'FAKE_FAIL': 'install'})
        self.run_cli('start', 'alpha')
        self.assertEqual(self.entries()['alpha']['state'], 'ready')

    def test_killed_creation_is_not_resumed(self):
        job = subprocess.Popen([str(SCRIPT), 'create', 'alpha'], env=self.env | {'FAKE_PAUSE_SETUP': '1'},
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        try:
            for _ in range(200):
                if (self.home / '.fake/setup-entered').exists():
                    break
                time.sleep(0.05)
            self.assertTrue((self.home / '.fake/setup-entered').exists())
            os.killpg(job.pid, signal.SIGKILL)
            job.communicate(timeout=5)
            self.assertEqual(self.entries()['alpha']['state'], 'creating')
            self.run_cli('create', 'alpha', ok=False)
            self.run_cli('purge', 'alpha', '--confirm', 'alpha')
        finally:
            if job.poll() is None:
                os.killpg(job.pid, signal.SIGKILL)
                job.communicate()


if __name__ == '__main__':
    if os.geteuid() == 0:
        raise SystemExit('Run tests as a non-root Linux user.')
    unittest.main(verbosity=2)
