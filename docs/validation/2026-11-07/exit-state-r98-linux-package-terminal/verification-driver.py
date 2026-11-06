"""日期：2026-11-07；收验固定R98源码的Linux包、23核心、双显示迁移及原业务报告。"""
import hashlib
import io
import json
from pathlib import Path
import runpy
import shutil
import stat
import subprocess
import tarfile
import zipfile

COMMIT = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'


# 日期：2026-11-07；包内源码的全集和每份字节都与固定Git对象比较，不读取整个历史证据Git归档。
def full_sources(raw, expected, commit, checkout):
    assert commit == COMMIT
    files = runpy.run_path('.cache/verify-completed-r66-packages.py')['checked_zip'](raw, max_bytes=4 * 1024**2)
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', commit], cwd=checkout)
    top = {'CMakeLists.txt', '.clang-format', 'LICENSE', 'README.md', '开发计划与进度.md'}
    folders = {'src', 'ui', 'resources', 'scripts', 'tests', '.github', 'docs'}
    selected = set()
    for encoded in names.split(b'\0'):
        if encoded:
            name = encoded.decode('utf-8')
            parts = Path(name).parts
            if name in top or parts[0] in folders and 'validation' not in parts and '__pycache__' not in parts:
                selected.add(name)
    declared = {row['path']: row['sha256'] for row in expected}
    assert len(expected) == len(declared) and selected == set(files) == set(declared)
    for name, raw in files.items():
        assert hashlib.sha256(raw).hexdigest() == declared[name]
        assert subprocess.check_output(['git', 'show', commit + ':' + name], cwd=checkout) == raw
    return len(files)


# 日期：2026-11-07；已有原件只允许相同字节复用，任何不一致立即停止，不覆盖失败记录。
def preserve(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


# 日期：2026-11-07；先保全附件和终态，成功资格还必须逐份核对核心、源码和双显示业务结果。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/exit-state-r98-linux-package-terminal'
    distribution = root / 'dist/linux-preview-20261107-r98-exit-state'
    assert not (output / 'verified-summary.json').exists()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    ledger = json.loads((root / '.cache/r98-linux-package-dispatch.json').read_text('utf-8'))
    run = request(base + '/actions/runs/' + str(ledger['runId']))
    assert run['id'] == 42266702018 and run['head_sha'] == COMMIT and run['status'] == 'completed'
    jobs = request(base + '/actions/runs/' + str(run['id']) + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/' + str(run['id']) + '/artifacts?per_page=100')['artifacts']
    assert len(jobs) == 1 and jobs[0]['status'] == 'completed'
    output.mkdir(parents=True, exist_ok=True)
    distribution.mkdir(parents=True, exist_ok=True)
    helper = runpy.run_path('.cache/fetch-linux-preview-r42.py')
    helper['verify_tar'].__globals__['verify_sources'] = full_sources
    records = []
    for item in artifacts:
        assert item['name'] == 'linux-glibc-preview-X64' and not item['expired']
        saved = distribution / (item['name'] + '.zip')
        raw = saved.read_bytes() if saved.exists() else request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        checksum = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + checksum
        preserve(saved, raw)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            assert len(archive.namelist()) == len(set(archive.namelist()))
            for member in archive.infolist():
                helper['safe_name'](member.filename)
                assert not stat.S_ISLNK(member.external_attr >> 16)
                if member.is_dir():
                    continue
                if member.filename.endswith('.tar.gz') or Path(member.filename).name == 'SHA256SUMS':
                    target = distribution / Path(member.filename).name
                else:
                    assert Path(member.filename).suffix in ('.json', '.log', '.png', '.xml', '.txt', '.sha256')
                    assert member.file_size <= 16 * 1024**2
                    target = output / member.filename
                preserve(target, archive.read(member))
        records.append({'id': item['id'], 'name': item['name'], 'sha256': checksum})
    for job in jobs:
        preserve(output / ('job-' + str(job['id']) + '.log'),
                 request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
    observation = {'sourceCommit': COMMIT, 'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                   'artifacts': records, 'jobs': jobs, 'allArtifactDigestsVerified': True,
                   'releaseQualified': False, 'deliveryComplete': False}
    preserve(output / 'terminal-observation.json', (json.dumps(observation, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    assert run['conclusion'] == jobs[0]['conclusion'] == 'success', 'Original failure preserved; no success qualification'
    assert len(records) == 1
    archive = distribution / 'DuktoNext-linux-glibc-x64-preview.tar.gz'
    with archive.open('rb') as stream:
        archive_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert (distribution / 'SHA256SUMS').read_text('ascii').split()[0] == archive_sha
    package = helper['verify_tar'](archive, COMMIT, root / '.cache/github-29583855-dukto-next-r28')
    assert package['applicationSourceFiles'] == 333
    core = runpy.run_path('.cache/verify-r95-local-terminals.py')['core'](output / 'build', output / 'build/ctest.log', output / 'build/Testing/QtTest')
    text = (output / 'build/Testing/QtTest/file-exchange-tests.log').read_text('utf-8')
    for row in ('already-finished', 'already-finished-error', 'running-finishes', 'real-deadline'):
        assert 'PASS   : FileExchangeTests::childExitWait(' + row + ')' in text
    assert text.count('PASS   : FileExchangeTests::parallelDispositions(') == 16
    with tarfile.open(archive, 'r:gz') as payload:
        launcher_sha = hashlib.sha256(payload.extractfile('DuktoNext-linux-glibc-x64-preview/dukto-cli').read()).hexdigest()
    flags = runpy.run_path('.cache/verify-overwrite-r62-terminal.py')['passed_flags']
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    reports = []
    for platform, name in (('xcb', 'package-x11.json'), ('wayland', 'package-wayland.json')):
        path = output / 'build' / name
        value = json.loads(path.read_text('utf-8'))
        assert value['passed'] and value['runtimeChecksPassed'] and value['transferChecksPassed']
        assert value['platform'] == platform and value['archiveSha256'] == archive_sha
        for key in ('transfer', 'conflictOverwrite', 'conflictOverwriteRecovery'):
            child = value[key]
            flags(child)
            if key != 'transfer':
                assert child.get('executableSha256', child.get('binarySha256')) == launcher_sha
        reports.append(dict(proof(path), platform=platform, businessReports=3, cliLauncherSha256=launcher_sha))
    package.update(artifactId=records[0]['id'], artifactSha256=records[0]['sha256'],
                   artifactUrl=run['html_url'] + '/artifacts/' + str(records[0]['id']),
                   runtimeMigrationBothDisplaysQualified=True)
    result = dict(observation, package=package, core=core, runtimeReports=reports,
                  newExitStateRows=4, originalParallelRows=16, screenshotsViewed=False,
                  cleanSystemQualified=False, entireProtocolSuiteRun=False, passed=True)
    preserve(output / 'verified-summary.json', (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    preserve(distribution / 'BUILD-RECEIPT.json', (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': COMMIT, 'sourceFiles': 333, 'coreTargets': 23,
                      'bothDisplayRuntimesVerified': True, 'screenshotsViewed': False}), flush=True)


if __name__ == '__main__':
    main()
