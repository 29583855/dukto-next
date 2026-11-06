"""日期：2026-11-07；保全并核验固定R100双Mac部署包和原生迁移证据。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
RUN = 42286046864
ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-07/clipboard-r100-macos-package-terminal'
DIST = ROOT / 'dist/macos-preview-20261107-r100-clipboard'
CHECKOUT = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-07；原件仅允许相同字节复用，失败观察不会被后续资格记录覆盖。
def preserve(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


# 日期：2026-11-07；重试仅复用相同终态的首次观察，保留原观察时间，其他身份和结果必须一致。
def preserve_observation(path, value):
    if path.exists():
        previous = json.loads(path.read_text('utf-8'))
        assert {key: item for key, item in previous.items() if key != 'observedUtc'} == {
            key: item for key, item in value.items() if key != 'observedUtc'}
    else:
        preserve(path, (json.dumps(value, indent=2) + '\n').encode('utf-8'))


# 日期：2026-11-07；明确选择完整应用源码并逐blob比较，避免读取含历史证据的整个Git归档。
def source_proof(raw, manifest):
    checked_zip = runpy.run_path('.cache/verify-client-history-r80-packages.py')['checked_zip']
    files = checked_zip(raw, max_bytes=4 * 1024**2)
    names = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', '-z', COMMIT], cwd=CHECKOUT)
    top = {'CMakeLists.txt', '.clang-format', 'LICENSE', 'README.md', '开发计划与进度.md'}
    folders = {'src', 'ui', 'resources', 'scripts', 'tests', '.github', 'docs'}
    selected = set()
    for encoded in names.split(b'\0'):
        if encoded:
            name = encoded.decode('utf-8')
            parts = Path(name).parts
            if name in top or parts[0] in folders and 'validation' not in parts and '__pycache__' not in parts:
                selected.add(name)
    declared = {row['path']: row['sha256'] for row in manifest['applicationSources']}
    assert len(manifest['applicationSources']) == len(declared) == 338
    assert selected == set(files) == set(declared)
    for name, value in files.items():
        assert hashlib.sha256(value).hexdigest() == declared[name], name
        assert subprocess.check_output(['git', 'show', COMMIT + ':' + name], cwd=CHECKOUT) == value, name
    return {'applicationSourceFiles': len(files), 'allSourceBlobsMatchExactGitCommit': True}


# 日期：2026-11-07；核对Cocoa和两种缩放导航帧与实际PNG摘要，保留原完整迁移门槛。
def navigation_proof(files):
    value = json.loads(files['build/main-window-navigation.json'])
    assert value['passed'] and value['sourceCommit'] == COMMIT
    assert value['nativePlatform'] == 'cocoa' and value['binaryUnchanged']
    assert {case['name'] for case in value['cases']} == {'native', 'offscreen-150', 'offscreen-200'}
    for case in value['cases']:
        assert case['passed'] and case['exitCode'] == 0 and len(case['frames']) == 2
        for frame in case['frames']:
            assert frame['chineseGlyphCoverage']['passed'] and frame['chineseGlyphCoverage']['missingGlyphs'] == 0
            size = 'x'.join(str(number) for number in frame['requestedSize'])
            name = 'build/main-window-navigation/' + case['name'] + '/Testing/QtTest/main-server-' + size + '.png'
            assert hashlib.sha256(files[name]).hexdigest() == frame['pngSha256']


# 日期：2026-11-07；终态和附件先保全，再核全部载荷、链接、源码及业务；截图另行实际审阅。
def main():
    assert not (OUTPUT / 'receipt.json').exists()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    assert run['head_sha'] == COMMIT and run['status'] == 'completed'
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    assert len(jobs) == 2 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
                   'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                   'jobs': jobs, 'artifacts': [], 'releaseQualified': False, 'deliveryComplete': False}
    preserve_observation(OUTPUT / 'terminal-observation.json', observation)
    helper = runpy.run_path('.cache/verify-client-history-r80-packages.py')
    helper['payload_proof'].__globals__.update(COMMIT=COMMIT, source_proof=source_proof)
    downloaded = {}
    for item in artifacts:
        assert item['name'] in ('macos-preview-ARM64', 'macos-preview-X64') and not item['expired']
        saved = DIST / (item['name'] + '.zip')
        raw = saved.read_bytes() if saved.exists() else request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        checksum = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + checksum
        preserve(saved, raw)
        files = helper['checked_zip'](raw)
        for name, value in files.items():
            if name.startswith('build/'):
                assert Path(name).suffix in ('.json', '.log', '.xml', '.png', '.txt')
                preserve(OUTPUT / item['name'] / name, value)
        assert item['name'] not in downloaded
        downloaded[item['name']] = (item, files, checksum)
        observation['artifacts'].append({'id': item['id'], 'name': item['name'], 'sha256': checksum})
    for job in jobs:
        preserve(OUTPUT / ('job-' + str(job['id']) + '.log'),
                 request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
    preserve_observation(OUTPUT / 'artifact-observation.json', observation)
    assert run['conclusion'] == 'success' and all(job['conclusion'] == 'success' for job in jobs), \
        'Original terminal failure preserved; no success qualification'
    assert set(downloaded) == {'macos-preview-ARM64', 'macos-preview-X64'}
    records = []
    for architecture, label in (('arm64', 'ARM64'), ('x86_64', 'X64')):
        item, files, zip_sha = downloaded['macos-preview-' + label]
        name = 'package-output/DuktoNext-macos-' + architecture + '-preview.tar.gz'
        payload = files[name]
        checksum = hashlib.sha256(payload).hexdigest()
        assert files[name + '.sha256'].decode('ascii').split()[0] == checksum
        package_dir = DIST / item['name'] / 'package-output'
        for selected in (name, name + '.sha256'):
            preserve(package_dir / Path(selected).name, files[selected])
        proof = helper['payload_proof'](payload, architecture)
        runtime_parent = json.loads(files['build/package-runtime.json'])
        assert runtime_parent['archiveSha256'] == checksum
        assert runtime_parent['verifiedFiles'] == proof['verifiedPayloadFiles']
        assert runtime_parent['verifiedLinks'] == proof['verifiedLinks'] == 71
        navigation_proof(files)
        runtime = helper['runtime_proof'](files, architecture, OUTPUT / item['name'])
        for key in ('screenshot', 'navigationScreenshot'):
            runtime[key] = Path(runtime[key]).relative_to(ROOT).as_posix()
        records.append(dict(proof, **runtime, architecture=architecture, archive=Path(name).name,
                            sha256=checksum, sourceCommit=COMMIT, artifactId=item['id'],
                            artifactUrl=run['html_url'] + '/artifacts/' + str(item['id']),
                            zipSha256=zip_sha, localArchive=(package_dir / Path(name).name).relative_to(ROOT).as_posix()))
        print(json.dumps({'architecture': architecture, 'payloadFiles': proof['verifiedPayloadFiles'],
                          'sourceFiles': proof['applicationSourceFiles'], 'runtimeReports': 5, 'passed': True}), flush=True)
    result = dict(observation, packages=records, bothArchitecturesVerified=True, screenshotsViewed=False,
                  fullNativeProtocolRegressionQualified=False, passed=True)
    for path in (OUTPUT / 'receipt.json', DIST / 'BUILD-RECEIPT.json'):
        preserve(path, (json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    shutil.copyfile(Path(__file__), OUTPUT / 'verification-driver.py')
    shutil.copyfile(ROOT / '.cache/verify-client-history-r80-packages.py', OUTPUT / 'source-verifier-r80.py')
    print(json.dumps({'receipt': str(OUTPUT / 'receipt.json'), 'bothArchitecturesVerified': True}), flush=True)


if __name__ == '__main__':
    main()
