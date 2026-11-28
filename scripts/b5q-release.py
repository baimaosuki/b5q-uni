#!/usr/bin/env python3
"""Run an authorized b5q release without manual gaps between its stages.

start commits the audit's exact scope and pushes once. resume follows that
commit without pushing. replay validates/packages an existing returned build
locally, without Git writes, network access or delivery-record updates.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inside(path):
    path = (ROOT / path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Release paths must stay inside the workspace')
    return path


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def git(*args, data=None):
    return subprocess.check_output(['git', '-C', str(ROOT), *args], input=data)


def validate_audit(audit, gate_work):
    """Reuse passed tests only while every recorded input is still identical."""
    for name, expected in audit['source_sha256'].items():
        # porting.toml is staged separately to exclude unrelated local records.
        if name != 'UniXNU-b5q/porting.toml' and sha(inside(name)) != expected:
            raise ValueError('Audit source changed: ' + name)
    aggregate = inside(audit['local_gate']['receipt'])
    if sha(aggregate) != audit['local_gate']['receipt_sha256']:
        raise ValueError('Local gate receipt hash changed')
    receipts = [aggregate, *[gate_work / n for n in
                ['local-gates.json', 'static-gates.json', 'failure-gates.json']]]
    bound = {}
    for path in receipts:
        receipt = json.loads(path.read_text())
        if not receipt.get('passed') or any(not c.get('passed') for c in receipt.get('checks', [])):
            raise ValueError('Local gate not passed: ' + str(path))
        for name, expected in receipt.get('source_sha256', {}).items():
            if name in bound and bound[name] != expected:
                raise ValueError('Inconsistent gate inputs: ' + name)
            bound[name] = expected
    for name, expected in bound.items():
        if sha(inside(name)) != expected:
            raise ValueError('Local gate source changed: ' + name)
    return bound


def porting_snapshot(base, working, reference, review):
    """Select only new review areas or strictly additive review evidence."""
    def blocks(text):
        pieces = re.split(r'(?m)(?=^\[\[area\]\]$)', text)
        return pieces[0], {tomllib.loads(p)['area'][0]['id']: p for p in pieces[1:]}
    prefix, old = blocks(base)
    _, new = blocks(working)
    selected = []
    for area_id, text in new.items():
        current = tomllib.loads(text)['area'][0]
        if not any(e.get('reference') == reference for e in current.get('evidence', [])):
            continue
        if area_id in old:
            before = tomllib.loads(old[area_id])['area'][0]
            if current == before:
                continue
            for key in before.keys() | current.keys():
                if before.get(key) == current.get(key):
                    continue
                if key not in ('paths', 'findings', 'evidence'):
                    raise ValueError('Unrelated porting field in review area: ' + key)
                if any(v not in current[key] for v in before.get(key, [])):
                    raise ValueError('Non-additive porting change: ' + key)
                added = [v for v in current[key] if v not in before.get(key, [])]
                if key == 'findings' and any(not v.startswith(review + ' ') for v in added):
                    raise ValueError('Unrelated porting finding')
                if key == 'evidence' and any(v.get('reference') != reference for v in added):
                    raise ValueError('Unrelated porting evidence')
        elif not area_id.startswith(review + '-'):
            raise ValueError('New area is outside requested review: ' + area_id)
        old[area_id] = text
        selected.append(area_id)
    if not selected:
        raise ValueError('No uncommitted porting area for ' + review)
    result = prefix + ''.join(old.values())
    tomllib.loads(result)
    return result, selected


class Release:
    def __init__(self, args):
        self.args = args
        self.config = json.loads(inside(args.config).read_text())
        self.audit_path = inside(args.audit or f'UniXNU-b5q/reports/{args.review}-source-audit.json')
        self.audit = json.loads(self.audit_path.read_text())
        if self.audit['review'] != args.review:
            raise ValueError('Requested review differs from audit')
        self.gate_work = inside(args.gate_work or Path(self.audit['local_gate']['receipt']).parent)
        self.work = inside(args.work_dir or f'artifacts/b5q-{args.review}-release')
        self.work.mkdir(parents=True, exist_ok=True)
        self.output = inside(args.output or f'artifacts/b5q-esp-{args.review}/esp.img')
        self.start = time.monotonic()
        self.state = dict(review=args.review, mode=args.mode, started_at=self.utc(),
                          passed=False, stages=[], phone_accessed=False)
        self.temp = None
        self.env = dict(os.environ, B5Q_GATE_WORK=str(self.gate_work), PYTHONUNBUFFERED='1')

    @staticmethod
    def utc():
        return datetime.now(timezone.utc).isoformat()

    def save(self):
        self.state['elapsed_seconds'] = round(time.monotonic() - self.start, 3)
        write_json(self.work / 'timings.json', self.state)

    def step(self, name, function):
        row = dict(name=name, started_at=self.utc(), passed=False)
        self.state['stages'].append(row)
        self.save()
        print('START', name, flush=True)
        started = time.monotonic()
        try:
            result = function()
            row['passed'] = True
            return result
        finally:
            row['seconds'] = round(time.monotonic() - started, 3)
            row['finished_at'] = self.utc()
            self.save()
            print('PASS' if row['passed'] else 'FAIL', name, row['seconds'], 'seconds', flush=True)

    def command(self, name, *command):
        log = self.work / (name + '.log')
        with log.open('w') as stream:
            result = subprocess.run(list(map(str, command)), cwd=ROOT, env=self.env,
                                    stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{name} failed (exit {result.returncode}); first failure log: {log}')

    def api(self, path):
        token = os.environ.get('GH_TOKEN') or (Path.home() / '.config/gh/token').read_text().strip()
        url = 'https://api.github.com/repos/' + self.config['repo'] + path
        for attempt in range(3):
            request = urllib.request.Request(url, headers={
                'Authorization': 'Bearer ' + token, 'User-Agent': 'b5q-release',
                'Accept': 'application/vnd.github+json'})
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                    raise RuntimeError('GitHub API failed: HTTP ' + str(error.code)) from None
                time.sleep(min(30, int(error.headers.get('Retry-After', '2'))))

    def commit(self, bound):
        self.require_main()
        if git('diff', '--cached', '--name-only').strip():
            raise ValueError('Index contains existing changes; no staging was performed')
        paths = list(self.audit['source_paths'])
        if set(paths) != set(self.audit['source_sha256']):
            raise ValueError('Audit file list differs from its source hashes')
        for name in paths:
            inside(name)
            if not name.startswith(('UniXNU-b5q/', 'tests/b5q-ufs/', 'scripts/b5q-install/')):
                raise ValueError('Outside review source scope: ' + name)
        # Check changed tested inputs against the projected commit, not just the working tree.
        dirty = git('diff', '--name-only', 'HEAD', '--', *bound).decode().splitlines()
        dirty += git('ls-files', '--others', '--exclude-standard', '--', *bound).decode().splitlines()
        if set(dirty) - set(paths):
            raise ValueError('Tested inputs have unstaged changes outside the audit: ' +
                             ', '.join(sorted(set(dirty) - set(paths))))
        porting = 'UniXNU-b5q/porting.toml'
        snapshot, areas = porting_snapshot(git('show', 'HEAD:' + porting).decode(),
                                          inside(porting).read_text(),
                                          self.audit_path.relative_to(ROOT / 'UniXNU-b5q').as_posix(),
                                          self.args.review)
        self.audit['source_sha256'][porting] = hashlib.sha256(snapshot.encode()).hexdigest()
        note = 'porting.toml source hash identifies the staged review-only snapshot.'
        if note not in self.audit.setdefault('notes', []):
            self.audit['notes'].append(note)
        write_json(self.audit_path, self.audit)
        blob = git('hash-object', '-w', '--stdin', data=snapshot.encode()).decode().strip()
        git('update-index', '--cacheinfo', '100644,' + blob + ',' + porting)
        git('add', '--', *[n for n in paths if n != porting], str(self.audit_path.relative_to(ROOT)))
        actual = set(git('diff', '--cached', '--name-only').decode().splitlines())
        expected = set(paths) | {str(self.audit_path.relative_to(ROOT))}
        if actual != expected:
            raise ValueError('Staged scope differs from audit')
        for name, expected_hash in self.audit['source_sha256'].items():
            if hashlib.sha256(git('show', ':' + name)).hexdigest() != expected_hash:
                raise ValueError('Staged source hash differs: ' + name)
        git('diff', '--cached', '--check')
        self.command('commit', 'git', 'commit', '-m',
                     f'b5q: {self.args.review} reviewed fixes [reuse-firmware]')
        commit = git('rev-parse', 'HEAD').decode().strip()
        self.state.update(commit=commit, committed_files=len(actual), porting_areas=areas)
        return commit

    def require_main(self):
        if self.config.get('branch') != 'main':
            raise ValueError('Release destination must be main')
        if git('branch', '--show-current').decode().strip() != 'main':
            raise ValueError('Release commits must be made on main')

    def push_main(self, commit):
        self.require_main()
        if git('rev-parse', 'HEAD').decode().strip() != commit:
            raise ValueError('HEAD changed after the release commit')
        self.command('push', 'git', 'push', self.config['remote'], 'HEAD:refs/heads/main')

    def prepare_firmware(self):
        receipt = json.loads(inside(self.config['firmware_receipt']).read_text())
        fd = inside(self.config['fd'])
        if not receipt.get('passed') or not receipt.get('github_digest_verified'):
            raise ValueError('Firmware receipt is not verified')
        if sha(fd) != receipt['FD']['sha256']:
            raise ValueError('Firmware FD changed')
        sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
        from unixnu.boot_template import loader_pe
        inputs = self.temp / 'efi-inputs'
        inputs.mkdir()
        data = fd.read_bytes()
        for name, guid in [('BOOTAA64.EFI', '9b665204-a133-47a2-9396-9e2b370a4e25'),
                           ('DarwinBoot.efi', '1b64af87-8415-4b57-9b16-680d70913b9f')]:
            (inputs / name).write_bytes(loader_pe(data, guid))
        self.state['firmware_FD_sha256'] = receipt['FD']['sha256']

    def wait_run(self, commit):
        deadline = time.monotonic() + self.args.timeout
        run = self.args.run
        if run is not None:
            self.state.update(ci_run=run, ci_url=f"https://github.com/{self.config['repo']}/actions/runs/{run}")
            self.save()
        last_step = None
        next_jobs = 0
        while time.monotonic() < deadline:
            if run is None:
                query = urllib.parse.urlencode({'branch': self.config['branch'], 'event': 'push', 'per_page': 10})
                runs = self.api('/actions/workflows/' + self.config['workflow'] + '/runs?' + query)
                matches = [r for r in runs['workflow_runs'] if r['head_sha'] == commit]
                if matches:
                    run = max(matches, key=lambda r: r['id'])['id']
                    self.state.update(ci_run=run, ci_url=f"https://github.com/{self.config['repo']}/actions/runs/{run}")
                    self.save()
                    print('CI', self.state['ci_url'], flush=True)
            if run is not None:
                info = self.api('/actions/runs/' + str(run))
                if info['head_sha'] != commit or info['path'] != '.github/workflows/' + self.config['workflow']:
                    raise ValueError('CI commit/workflow mismatch')
                if time.monotonic() >= next_jobs or info['status'] == 'completed':
                    jobs = self.api('/actions/runs/' + str(run) + '/jobs')['jobs']
                    next_jobs = time.monotonic() + 20
                    matches = [j for j in jobs if j['name'] == 'macOS XNU full-component build']
                    kernel = matches[0] if len(matches) == 1 else None
                    if kernel and kernel.get('labels') and 'macos-26' not in kernel['labels']:
                        raise ValueError('Expected the existing macOS ARM runner')
                    current = next((s['name'] for s in kernel['steps'] if s['status'] == 'in_progress'),
                                   kernel['status']) if kernel else 'waiting for kernel job'
                    if current != last_step:
                        print('CI STEP', current, flush=True)
                        last_step = current
                if info['status'] == 'completed':
                    write_json(self.work / 'CI.json', dict(run=run, commit=commit, status=info['status'],
                               conclusion=info['conclusion'], jobs=[{k: j.get(k) for k in
                               ['name', 'conclusion', 'started_at', 'completed_at', 'labels']} for j in jobs]))
                    if info['conclusion'] != 'success':
                        gh = ROOT / 'tools/github-cli-2.106.0/bin/gh'
                        self.command('CI-first-failure', gh, 'run', 'view', str(run), '--repo',
                                     self.config['repo'], '--log-failed')
                        raise RuntimeError('CI failed; retained CI-first-failure.log; no new run was started')
                    if not kernel or kernel['conclusion'] != 'success':
                        raise ValueError('Workflow finished without a successful kernel job')
                    return run
            time.sleep(self.args.poll_seconds)
        raise TimeoutError('CI wait timed out; resume this same run, do not start another')

    def finish(self, run, commit):
        ci = inside(self.args.ci_dir or f'artifacts/b5q-{self.args.review}-ci-{run}')
        if not ci.exists():
            if self.args.mode == 'replay':
                raise ValueError('Replay requires existing returned artifacts')
            self.step('download', lambda: self.command('download', PYTHON,
                      ROOT / 'scripts/b5q-install/download-ci-artifact.py', '--run', run, '--out', ci))
        transfer = json.loads((ci / 'transfer-index.json').read_text())
        if (transfer['commit'] != commit or str(transfer['run']) != str(run)
                or not transfer['artifact']['github_digest_verified']):
            raise ValueError('Returned artifact identity differs from requested CI')
        accepted = self.work / 'returned'
        self.step('returned-gates', lambda: self.command('returned-gates', PYTHON,
                  ROOT / 'scripts/b5q-install/check-v33b-returned.py', '--ci', ci,
                  '--firmware-receipt', inside(self.config['firmware_receipt']),
                  '--fd', inside(self.config['fd']), '--firmware-dir', inside(self.config['firmware_dir']),
                  '--reuse-unchanged-firmware', '--out', accepted))
        package_ci = ci
        if self.args.mode == 'replay':
            # The production packager writes batch2-package.json under --ci.
            # Give replay an overlay so the original delivery metadata is untouched.
            package_ci = self.temp / 'package-ci'
            package_ci.mkdir()
            for name in ['payload', 'runtime', 'device-tree']:
                (package_ci / name).symlink_to(ci / name, target_is_directory=True)
        metadata = self.work / 'batch2-package.json'
        if self.output.exists():
            producer = metadata if metadata.is_file() else ci / 'batch2-package.json'
            expected = json.loads(producer.read_text())['esp']
            actual = dict(bytes=self.output.stat().st_size, sha256=sha(self.output))
            if self.args.mode != 'resume' or actual != expected:
                raise ValueError('Existing IMG does not match this package; refusing overwrite')
            if producer != metadata:
                metadata.write_bytes(producer.read_bytes())
            print('RESUME existing byte-identical package; continuing readback', flush=True)
        else:
            self.step('package', lambda: self.command('package', PYTHON,
                      ROOT / 'UniXNU-b5q/scripts/package-batch2-esp.py', '--unixnu', ROOT / 'UniXNU',
                      '--inputs', self.temp / 'efi-inputs', '--ci', package_ci, '--out', self.output,
                      '--fd', inside(self.config['fd']), '--gates', accepted / 'package-ready.json'))
            metadata.write_bytes((package_ci / 'batch2-package.json').read_bytes())
        self.step('readback', lambda: self.command('readback', PYTHON,
                  ROOT / 'scripts/b5q-verify-release.py', '--esp', self.output, '--ci', ci,
                  '--fd', inside(self.config['fd']), '--config', inside(self.args.config),
                  '--package-metadata', metadata, '--out', self.work / 'ESP-readback.json'))
        proof = json.loads((self.work / 'ESP-readback.json').read_text())
        self.state.update(passed=True, commit=commit, ci_run=run, esp=dict(path=str(self.output), **proof['esp']),
                          hardware_verified=False, returned_receipt_sha256=sha(accepted / 'package-ready.json'),
                          readback_receipt_sha256=sha(self.work / 'ESP-readback.json'))
        self.save()
        if self.args.mode != 'replay':
            self.record_delivery()
        print(json.dumps({k: self.state[k] for k in ['passed', 'commit', 'ci_run', 'esp', 'elapsed_seconds']}, indent=2), flush=True)

    def record_delivery(self):
        path = ROOT / 'UniXNU-b5q/reports' / (self.args.review + '-delivery.json')
        write_json(path, self.state)
        porting = ROOT / 'UniXNU-b5q/porting.toml'
        area_id = self.args.review + '-automated-delivery'
        if any(a['id'] == area_id for a in tomllib.loads(porting.read_text())['area']):
            return
        q = json.dumps
        esp = self.state['esp']
        record = ('\n[[area]]\nid = ' + q(area_id) + '\nstatus = "host-verified"\n'
                  'components = ["QcomDwc3"]\npaths = [' + q('reports/' + path.name) + ']\n'
                  'inputs = [' + q('CI commit ' + self.state['commit']) + ', ' +
                  q('Firmware FD SHA256 ' + self.state['firmware_FD_sha256']) + ']\n'
                  'configuration = ["Existing ARM workflow, exact qualified firmware and production800MiB4KnESP"]\n'
                  'procedure = ["Follow the same CI, verify artifact digest, run complete returned gates, package and read back actual ESP bytes"]\n'
                  'findings = [' + q('Automatic release completed; unchanged full returned gates and final FAT/ADT/signature/plist/PAC/POST/log readback PASS. ESP SHA256 ' + esp['sha256']) + ']\n'
                  'completion = [' + q('Delivered ' + esp['path'] + ' SHA256 ' + esp['sha256']) + ']\n'
                  'limits = ["HOST_VERIFIED_PENDING_HARDWARE; no phone action"]\n'
                  'next_action = ["Await physical feedback"]\n'
                  '[[area.evidence]]\nkind = "host"\nreference = ' + q('reports/' + path.name) + '\n'
                  'revision = ' + q(self.state['commit']) + '\ncommand = ' + q('python3 scripts/b5q-release.py ' + self.args.mode + ' --review ' + self.args.review) + '\n'
                  'result = ' + q('PASS CI ' + str(self.state['ci_run']) + '; ' + str(esp['bytes']) + ' byte ESP SHA256 ' + esp['sha256'] + '; timing stages recorded') + '\n')
        updated = porting.read_text() + record
        tomllib.loads(updated)
        porting.write_text(updated)

    def execute(self):
        if self.args.mode == 'start':
            self.require_main()
        if self.output.exists() and self.args.mode != 'resume':
            raise ValueError('Output already exists; choose a new output or use the existing verified IMG')
        bound = self.step('preflight', lambda: validate_audit(self.audit, self.gate_work))
        with tempfile.TemporaryDirectory(prefix='release-', dir=self.work) as td:
            self.temp = Path(td)
            self.env['TMPDIR'] = str(self.temp)
            if self.args.mode == 'start':
                commit = self.step('commit', lambda: self.commit(bound))
                self.step('firmware-input-identity', lambda: self.command('firmware-input-identity', PYTHON,
                          ROOT / 'scripts/b5q-install/check-firmware-reuse.py',
                          '--receipt', inside(self.config['firmware_receipt']), '--fd', inside(self.config['fd']),
                          '--current', commit, '--out', self.work / 'firmware-reuse.json'))
                self.step('push', lambda: self.push_main(commit))
            elif self.args.mode == 'replay':
                commit = json.loads((inside(self.args.ci_dir) / 'transfer-index.json').read_text())['commit']
            else:
                commit = git('rev-parse', 'HEAD').decode().strip()
            # Run while the remote runner queues/builds, before waiting for completion.
            self.step('prepare-firmware', self.prepare_firmware)
            run = self.args.run if self.args.mode == 'replay' else self.step('CI', lambda: self.wait_run(commit))
            self.finish(run, commit)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['start', 'resume', 'replay'])
    parser.add_argument('--review', required=True)
    parser.add_argument('--run', type=int)
    parser.add_argument('--audit')
    parser.add_argument('--gate-work')
    parser.add_argument('--ci-dir')
    parser.add_argument('--work-dir')
    parser.add_argument('--output')
    parser.add_argument('--config', default='scripts/b5q-release.json')
    parser.add_argument('--poll-seconds', type=float, default=5)
    parser.add_argument('--timeout', type=int, default=21600)
    args = parser.parse_args()
    if not re.fullmatch(r'review\d+', args.review) or not 1 <= args.poll_seconds <= 30:
        parser.error('Expected reviewN and a poll interval between 1 and 30 seconds')
    if args.mode == 'replay' and (not args.run or not args.ci_dir):
        parser.error('replay requires --run and --ci-dir')
    release = Release(args)
    try:
        release.execute()
    except Exception as error:
        release.state.update(passed=False, error=str(error))
        release.save()
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
