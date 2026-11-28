#!/usr/bin/env python3
"""Regression tests for release isolation, gate failures and prompt CI handoff."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import tomllib
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('b5q_release', ROOT / 'scripts/b5q-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def area(name, finding, reference):
    return ('\n[[area]]\nid = ' + json.dumps(name) + '\nfindings = [' + json.dumps(finding) + ']\n'
            '[[area.evidence]]\nreference = ' + json.dumps(reference) + '\n')


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='release-test-', dir=ROOT / 'artifacts')
        self.root = Path(self.tmp.name)
        self.root_patch = patch.object(release, 'ROOT', self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.tmp.cleanup()

    def pipeline(self, **options):
        result = object.__new__(release.Release)
        result.args = SimpleNamespace(review='review99', run=123, timeout=30,
                                      poll_seconds=5, mode='resume', ci_dir='ci', **options)
        result.config = dict(repo='test/test', workflow='b5q-p0-p5.yml', branch='main', remote='origin')
        result.state = dict(stages=[])
        result.work = self.root / 'logs'
        result.work.mkdir()
        result.output = self.root / 'esp.img'
        result.start = time.monotonic()
        result.env = dict(os.environ)
        return result

    def test_porting_excludes_old_edits_and_delivery_areas(self):
        base = area('old', 'original', 'old.json')
        working = (area('old', 'unrelated dirty finding', 'old.json') +
                   area('review98-delivery', 'old delivery', 'delivery.json') +
                   area('review99-fix', 'review99 fix', 'reports/review99-source-audit.json'))
        selected, ids = release.porting_snapshot(base, working, 'reports/review99-source-audit.json', 'review99')
        self.assertEqual(ids, ['review99-fix'])
        self.assertIn('original', selected)
        self.assertNotIn('unrelated dirty', selected)
        self.assertNotIn('review98-delivery', selected)

    def test_porting_rejects_unrelated_edit_inside_existing_area(self):
        base = area('old', 'original', 'old.json')
        changed = area('old', 'unrelated replacement', 'reports/review99-source-audit.json')
        with self.assertRaises(ValueError):
            release.porting_snapshot(base, changed, 'reports/review99-source-audit.json', 'review99')

    def test_stale_gate_source_stops_before_staging(self):
        source = self.root / 'source.c'
        source.write_text('old')
        digest = release.sha(source)
        gate = self.root / 'gate'
        gate.mkdir()
        for name in ['aggregate.json', 'local-gates.json', 'static-gates.json', 'failure-gates.json']:
            release.write_json(gate / name, dict(passed=True, checks=[dict(passed=True)],
                                               source_sha256={'source.c': digest}))
        audit = dict(source_sha256={'source.c': digest}, local_gate=dict(
                     receipt='gate/aggregate.json', receipt_sha256=release.sha(gate / 'aggregate.json')))
        self.assertEqual(release.validate_audit(audit, gate), {'source.c': digest})
        source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Audit source changed'):
            release.validate_audit(audit, gate)

    def test_actual_commit_excludes_dirty_unrelated_files(self):
        def git(*args):
            return subprocess.check_output(['git', '-C', str(self.root), *args])
        git('init', '-q', '-b', 'main')
        git('config', 'user.name', 'release-test')
        git('config', 'user.email', 'release-test@example.invalid')
        (self.root / 'UniXNU-b5q/package').mkdir(parents=True)
        (self.root / 'UniXNU-b5q/reports').mkdir()
        source = self.root / 'UniXNU-b5q/package/example.c'
        source.write_text('old\n')
        porting = self.root / 'UniXNU-b5q/porting.toml'
        baseline = area('old', 'original', 'old.json')
        porting.write_text(baseline)
        other = self.root / 'unrelated.txt'
        other.write_text('keep\n')
        git('add', '.')
        git('commit', '-qm', 'base')
        other.write_text('unrelated dirty work\n')
        source.write_text('new\n')
        reference = 'reports/review99-source-audit.json'
        porting.write_text(area('old', 'unrelated dirty record', 'old.json') +
                           area('review99-fix', 'review99 fix', reference))
        pipeline = self.pipeline()
        pipeline.audit_path = self.root / 'UniXNU-b5q' / reference
        paths = ['UniXNU-b5q/package/example.c', 'UniXNU-b5q/porting.toml']
        pipeline.audit = dict(source_paths=paths,
                              source_sha256={n: release.sha(self.root / n) for n in paths})
        release.write_json(pipeline.audit_path, pipeline.audit)
        commit = pipeline.commit({paths[0]: release.sha(source)})
        names = set(git('diff-tree', '--no-commit-id', '--name-only', '-r', commit).decode().splitlines())
        self.assertEqual(names, {*paths, 'UniXNU-b5q/' + reference})
        committed_porting = git('show', 'HEAD:UniXNU-b5q/porting.toml').decode()
        self.assertIn('original', committed_porting)
        self.assertNotIn('unrelated dirty record', committed_porting)
        self.assertEqual(other.read_text(), 'unrelated dirty work\n')
        self.assertIn('unrelated.txt', git('diff', '--name-only').decode())
        committed_audit = json.loads(git('show', 'HEAD:UniXNU-b5q/' + reference))
        self.assertEqual(committed_audit['source_sha256'][paths[1]],
                         hashlib.sha256(committed_porting.encode()).hexdigest())

    def test_wrong_ci_commit_is_rejected(self):
        pipeline = self.pipeline()
        pipeline.api = Mock(return_value=dict(head_sha='wrong', path='.github/workflows/b5q-p0-p5.yml'))
        with self.assertRaisesRegex(ValueError, 'CI commit/workflow mismatch'):
            pipeline.wait_run('wanted')

    def test_success_hands_off_without_a_final_poll_delay(self):
        pipeline = self.pipeline()
        info = dict(head_sha='wanted', path='.github/workflows/b5q-p0-p5.yml',
                    status='completed', conclusion='success')
        job = dict(name='macOS XNU full-component build', labels=['macos-26'],
                   status='completed', conclusion='success', steps=[])
        pipeline.api = Mock(side_effect=[info, dict(jobs=[job])])
        with patch.object(release.time, 'sleep') as sleep:
            self.assertEqual(pipeline.wait_run('wanted'), 123)
            sleep.assert_not_called()

    def test_queued_run_can_initially_have_no_jobs(self):
        pipeline = self.pipeline()
        queued = dict(head_sha='wanted', path='.github/workflows/b5q-p0-p5.yml', status='queued')
        complete = dict(queued, status='completed', conclusion='success')
        job = dict(name='macOS XNU full-component build', labels=['macos-26'],
                   status='completed', conclusion='success', steps=[])
        pipeline.api = Mock(side_effect=[queued, dict(jobs=[]), complete, dict(jobs=[job])])
        with patch.object(release.time, 'sleep') as sleep:
            self.assertEqual(pipeline.wait_run('wanted'), 123)
            sleep.assert_called_once_with(5)

    def test_returned_gate_failure_prevents_packaging(self):
        pipeline = self.pipeline()
        ci = self.root / 'ci'
        ci.mkdir()
        release.write_json(ci / 'transfer-index.json', dict(commit='wanted', run='123',
                           artifact=dict(github_digest_verified=True)))
        pipeline.config.update(firmware_receipt='firmware.json', fd='firmware.fd', firmware_dir='firmware')
        pipeline.command = Mock(side_effect=RuntimeError('returned gate failed'))
        with self.assertRaisesRegex(RuntimeError, 'returned gate failed'):
            pipeline.finish(123, 'wanted')
        self.assertEqual(pipeline.command.call_count, 1)
        self.assertEqual(pipeline.command.call_args.args[0], 'returned-gates')
        self.assertFalse(pipeline.output.exists())
        timing = json.loads((pipeline.work / 'timings.json').read_text())
        self.assertFalse(timing['stages'][0]['passed'])

    def test_existing_output_is_never_overwritten(self):
        pipeline = self.pipeline()
        pipeline.args.mode = 'start'
        pipeline.output.write_bytes(b'existing delivered IMG')
        with patch.object(pipeline, 'require_main'), patch.object(release, 'validate_audit') as validation:
            with self.assertRaisesRegex(ValueError, 'Output already exists'):
                pipeline.execute()
            validation.assert_not_called()
        self.assertEqual(pipeline.output.read_bytes(), b'existing delivered IMG')

    def test_release_refuses_branch_configuration_and_checkout(self):
        pipeline = self.pipeline()
        pipeline.config['branch'] = 'old-ci-branch'
        with self.assertRaisesRegex(ValueError, 'destination must be main'):
            pipeline.require_main()
        pipeline.config['branch'] = 'main'
        with patch.object(release, 'git', return_value=b'old-ci-branch\n'):
            with self.assertRaisesRegex(ValueError, 'commits must be made on main'):
                pipeline.require_main()

    def test_push_uses_only_main_and_checks_commit(self):
        pipeline = self.pipeline()
        pipeline.command = Mock()
        with patch.object(release, 'git', side_effect=[b'main\n', b'wanted\n']):
            pipeline.push_main('wanted')
        pipeline.command.assert_called_once_with('push', 'git', 'push', 'origin', 'HEAD:refs/heads/main')
        pipeline.command.reset_mock()
        with patch.object(release, 'git', side_effect=[b'main\n', b'other\n']):
            with self.assertRaisesRegex(ValueError, 'HEAD changed'):
                pipeline.push_main('wanted')
        pipeline.command.assert_not_called()

    def test_paths_cannot_escape_workspace(self):
        with self.assertRaises(ValueError):
            release.inside(self.root.parent)

    def test_resume_reuses_the_image_and_runs_readback(self):
        pipeline = self.pipeline()
        pipeline.args.config = 'config.json'
        pipeline.temp = self.root / 'temp'
        pipeline.temp.mkdir()
        ci = self.root / 'ci'
        ci.mkdir()
        release.write_json(ci / 'transfer-index.json', dict(commit='wanted', run='123',
                           artifact=dict(github_digest_verified=True)))
        pipeline.config.update(firmware_receipt='firmware.json', fd='firmware.fd', firmware_dir='firmware')
        pipeline.output.write_bytes(b'existing package')
        image = dict(bytes=pipeline.output.stat().st_size, sha256=release.sha(pipeline.output))
        release.write_json(ci / 'batch2-package.json', dict(esp=image))
        def command(name, *args):
            if name == 'returned-gates':
                release.write_json(pipeline.work / 'returned/package-ready.json', dict(passed=True))
            elif name == 'readback':
                release.write_json(pipeline.work / 'ESP-readback.json', dict(passed=True, esp=image))
            else:
                self.fail('Unexpected rebuild: ' + name)
        pipeline.command = Mock(side_effect=command)
        pipeline.record_delivery = Mock()
        pipeline.finish(123, 'wanted')
        self.assertEqual([c.args[0] for c in pipeline.command.call_args_list], ['returned-gates', 'readback'])
        self.assertEqual(pipeline.output.read_bytes(), b'existing package')

    def test_resume_does_not_commit_or_push(self):
        pipeline = self.pipeline()
        pipeline.audit = {}
        pipeline.gate_work = self.root / 'gate'
        pipeline.prepare_firmware = Mock()
        pipeline.wait_run = Mock(return_value=123)
        pipeline.finish = Mock()
        pipeline.command = Mock()
        with patch.object(release, 'validate_audit', return_value={}), \
             patch.object(release, 'git', return_value=b'wanted\n') as git:
            pipeline.execute()
        pipeline.command.assert_not_called()
        git.assert_called_once_with('rev-parse', 'HEAD')
        pipeline.finish.assert_called_once_with(123, 'wanted')

    def test_automatic_delivery_record_passes_official_schema(self):
        pipeline = self.pipeline()
        device = self.root / 'UniXNU-b5q'
        device.mkdir()
        (device / 'porting.toml').write_bytes((ROOT / 'UniXNU-b5q/porting.toml').read_bytes())
        pipeline.state.update(commit='a' * 40, firmware_FD_sha256='b' * 64, ci_run=123,
                              esp=dict(path=str(pipeline.output), bytes=838860800, sha256='c' * 64))
        pipeline.record_delivery()
        spec = importlib.util.spec_from_file_location('porting_validator', ROOT / 'UniXNU/scripts/porting-record.py')
        validator = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(validator)
        record = tomllib.loads((device / 'porting.toml').read_text())
        board = tomllib.loads((ROOT / 'UniXNU-b5q/board.toml').read_text())
        validator.validate(record, board, 'release-record', allow_custom_components=True)
        self.assertEqual(record['area'][-1]['id'], 'review99-automated-delivery')
        self.assertTrue((device / 'reports/review99-delivery.json').is_file())


if __name__ == '__main__':
    unittest.main()
