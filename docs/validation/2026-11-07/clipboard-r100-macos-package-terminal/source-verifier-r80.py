"""日期：2026-11-06；核验精确r80双Mac包、源码、原生运行及主窗口证据。"""

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import runpy
import shutil
import stat
import subprocess
import tarfile
import zipfile

COMMIT = '9ac5ca7a18874a52207bedd7cb440c4867a5bcdf'
RUN = 42162374097
CHECKOUT = Path('.cache/github-29583855-dukto-next-r28')
ROOT = Path('docs/validation/2026-11-06/client-history-r80-macos-package-terminal')
DIST = Path('dist/macos-preview-20261106-r80-client-history')


# 日期：2026-11-06；原始字节摘要用于绑定GitHub附件和全部本机证据。
def digest(raw):
    return hashlib.sha256(raw).hexdigest()


# 日期：2026-11-06；所有归档成员必须是有界相对路径，重复名和特殊对象拒绝读取。
def checked_zip(raw, max_bytes=40 * 1024**2):
    result = {}
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.filename
            assert not stat.S_ISLNK(member.external_attr >> 16)
            assert member.file_size <= max_bytes and member.filename not in result
            assert not member.is_dir()
            result[member.filename] = archive.read(member)
    return result


# 日期：2026-11-06；逐个源码blob与精确提交核对，禁止拿当前工作区或包内声明代替Git树。
def source_proof(raw, manifest):
    files = checked_zip(raw, max_bytes=4 * 1024**2)
    git_raw = subprocess.check_output(['git', 'archive', COMMIT], cwd=CHECKOUT)
    expected_bytes = {}
    with tarfile.open(fileobj=io.BytesIO(git_raw)) as git_archive:
        for member in git_archive.getmembers():
            if not member.isfile():
                continue
            name = member.name
            if name in ('CMakeLists.txt', '.clang-format', 'LICENSE', 'README.md', '开发计划与进度.md') or (
                    name.split('/')[0] in ('src', 'ui', 'resources', 'scripts', 'tests', '.github', 'docs')
                    and '__pycache__' not in name.split('/') and 'validation' not in name.split('/')):
                expected_bytes[name] = git_archive.extractfile(member).read()
    expected = {item['path']: item['sha256'] for item in manifest['applicationSources']}
    assert set(files) == set(expected) == set(expected_bytes)
    for name, value in files.items():
        assert digest(value) == expected[name] and value == expected_bytes[name], name
    return {'applicationSourceFiles': len(files), 'allSourceBlobsMatchExactGitCommit': True}


# 日期：2026-11-06；在内存读取tar，验证全部载荷、链接目标、Mach-O架构和应用源码。
def payload_proof(raw, architecture):
    content, links, names = {}, {}, set()
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
            assert member.name not in names
            names.add(member.name)
            if member.isfile():
                assert member.size <= 50 * 1024**2
                content[member.name] = (member, archive.extractfile(member).read())
            elif member.issym():
                assert not PurePosixPath(member.linkname).is_absolute()
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member.name), member.linkname))
                assert resolved.startswith(member.name.split('/')[0] + '/')
                links[member.name] = member.linkname
            else:
                assert member.isdir()
    manifest_name, = [name for name in content if name.endswith('/package-manifest.json')]
    manifest = json.loads(content[manifest_name][1])
    assert manifest['sourceCommit'] == COMMIT and manifest['architecture'] == architecture
    assert manifest['signature'] == 'adhoc' and not manifest['notarized']
    prefix = manifest_name.rsplit('/', 1)[0] + '/'
    expected = {prefix + item['path']: item for item in manifest['files']}
    assert set(content) - set(expected) == {manifest_name}
    assert set(expected) <= set(content)
    for name, item in expected.items():
        value = content[name][1]
        assert len(value) == item['bytes'] and digest(value) == item['sha256'], name
    assert {name[len(prefix):]: target for name, target in links.items()} == {
        item['path']: item['target'] for item in manifest['links']}
    executables = []
    for name in ('Dukto Next.app/Contents/MacOS/dukto-cli', 'Dukto Next.app/Contents/MacOS/dukto-gui'):
        member, value = content[prefix + name]
        assert member.mode & 0o111 and int.from_bytes(value[:4], 'little') == 0xfeedfacf
        assert int.from_bytes(value[4:8], 'little') == (0x100000c if architecture == 'arm64' else 0x1000007)
        executables.append({'path': name, 'sha256': digest(value), 'executable': True})
    member, launcher = content[prefix + 'dukto-cli']
    assert member.mode & 0o111 and launcher.startswith(b'#!/bin/sh\n')
    source = source_proof(content[prefix + 'DuktoNext-application-source.zip'][1], manifest)
    return dict(source, verifiedPayloadFiles=len(expected), verifiedLinks=len(links),
                guiCli=executables, signature='adhoc', developerIdSigned=False, notarized=False)


# 日期：2026-11-06；运行报告按父摘要读取全部子报告，同时验证原生窗口及150/200%DPI子用例。
def runtime_proof(files, architecture, target):
    report = json.loads(files['build/package-runtime.json'])
    assert report['passed'] and report['runtimeMigrationQualified'] and report['systemPathOnly']
    assert report['sourceCommit'] == COMMIT and report['architecture'] == architecture
    assert len(report['cases']) == 5
    checks = runpy.run_path('.cache/verify-progress-r53.py')
    children = []
    for case in report['cases']:
        name = 'build/package-runtime-' + case['name'] + '.json'
        assert digest(files[name]) == case['reportSha256'] and case['passed']
        value = json.loads(files[name])
        assert value['passed']
        if case['name'] == 'overwrite':
            checks['overwrite'](value)
        elif 'recovery' in case['name']:
            checks['recovery'](value)
        elif case['name'] == 'transfer16':
            assert value['channelsRequested'] == 16
        children.append({'path': name, 'sha256': digest(files[name]), 'passed': True})
    navigation = json.loads(files['build/main-window-navigation.json'])
    assert navigation['passed']
    # 日期：2026-11-06；只提取经过路径和类型核对的证据，不执行下载程序。
    for name, raw in files.items():
        if name.startswith('build/') and Path(name).suffix in ('.json', '.log', '.xml', '.png'):
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
    return {'runtimeReports': children, 'runtimeMigrationQualified': True,
            'mainWindowNavigationPassed': True, 'systemPathOnly': True,
            'screenshot': (target / 'build/package-runtime.png').as_posix(),
            'navigationScreenshot': (target / 'build/main-window-navigation/native/Testing/QtTest/main-server-430x700.png').as_posix()}


# 日期：2026-11-06；只有工作流及两job均终态成功且全部原附件核验后才发布本机交付回执。
def main():
    api = runpy.run_path('.cache/github-actions-r28.py')
    request = api['request']
    base = '/repos/' + api['REPOSITORY']
    run = request(base + '/actions/runs/' + str(RUN))
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    assert run['head_sha'] == COMMIT and run['status'] == 'completed' and run['conclusion'] == 'success'
    assert len(jobs) == 2 and all(job['conclusion'] == 'success' for job in jobs)
    ROOT.mkdir(exist_ok=False)
    DIST.mkdir(exist_ok=False)
    records = []
    for architecture, label in [('arm64', 'ARM64'), ('x86_64', 'X64')]:
        artifact, = [item for item in artifacts if item['name'] == 'macos-preview-' + label]
        prior = Path('.cache/client-history-r80-package-downloads') / (artifact['name'] + '.zip')
        raw = prior.read_bytes() if prior.exists() else request(base + '/actions/artifacts/' + str(artifact['id']) + '/zip', binary=True)
        assert 'sha256:' + digest(raw) == artifact['digest']
        (ROOT / (artifact['name'] + '.zip')).write_bytes(raw)
        shutil.copyfile(ROOT / (artifact['name'] + '.zip'), DIST / (artifact['name'] + '.zip'))
        files = checked_zip(raw)
        tar_name = 'package-output/DuktoNext-macos-' + architecture + '-preview.tar.gz'
        payload = files[tar_name]
        assert files[tar_name + '.sha256'].decode('ascii').split()[0] == digest(payload)
        target = ROOT / artifact['name']
        runtime = runtime_proof(files, architecture, target)
        proof = payload_proof(payload, architecture)
        package_dir = DIST / artifact['name'] / 'package-output'
        package_dir.mkdir(parents=True)
        for name in (tar_name, tar_name + '.sha256'):
            (package_dir / Path(name).name).write_bytes(files[name])
        records.append(dict(proof, **runtime, architecture=architecture, archive=Path(tar_name).name,
                            sha256=digest(payload), sourceCommit=COMMIT, artifactId=artifact['id'],
                            artifactUrl=run['html_url'] + '/artifacts/' + str(artifact['id']),
                            zipSha256=digest(raw), localArchive=(package_dir / Path(tar_name).name).as_posix()))
        print(json.dumps({'architecture': architecture, 'payloadFiles': proof['verifiedPayloadFiles'],
                          'sourceFiles': proof['applicationSourceFiles'], 'runtimeReports': 5, 'passed': True}), flush=True)
    result = {'date': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
              'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
              'jobs': jobs, 'packages': records, 'bothArchitecturesVerified': True,
              'screenshotsViewed': False, 'releaseQualified': False, 'deliveryComplete': False}
    for path in (ROOT / 'receipt.json', DIST / 'BUILD-RECEIPT.json'):
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(ROOT / 'receipt.json'), 'bothArchitecturesVerified': True}))


if __name__ == '__main__':
    main()
