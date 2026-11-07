"""日期：2026-11-07；核验R105双Mac真实编译产物，独立于尚在运行的完整测试结论。"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import shutil
import stat
import subprocess
import tarfile
import zipfile


# 日期：2026-11-07；只保存既有编译步骤和真实Mach-O证据，编译归档不授予运行依赖部署或正式发布资格。
def main():
    root = Path.cwd()
    commit = '4652f4dce23b014e18f2db56c6a75e81e76deafa'
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    run_id = json.loads((root / '.cache/r105-native-run.json').read_text('utf-8'))['run']['id']
    run = request(base + '/actions/runs/' + str(run_id))
    assert run['head_sha'] == commit
    jobs = request(base + '/actions/runs/' + str(run_id) + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/' + str(run_id) + '/artifacts?per_page=100')['artifacts']
    folder = root / 'docs/validation/2026-11-07/task-items-r105-macos-compiled'
    distribution = root / 'dist/macos-compiled-20261107-r105-task-items'
    folder.mkdir(exist_ok=False)
    distribution.mkdir(exist_ok=False)
    records = []
    for runner, label, architecture, cpu in (('macos-15', 'ARM64', 'arm64', 0x100000c),
                                              ('macos-15-intel', 'X64', 'x86_64', 0x1000007)):
        job, = [row for row in jobs if row['name'] == 'native (' + runner + ', brew)']
        required = ('Compile', 'Archive macOS compilation outputs', 'Preserve macOS compiled GUI and CLI')
        for name in required:
            step, = [row for row in job['steps'] if row['name'] == name]
            assert step['status'] == 'completed' and step['conclusion'] == 'success'
        item, = [row for row in artifacts if row['name'] == 'macos-compiled-' + label]
        assert not item['expired']
        raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        checksum = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + checksum
        (distribution / (item['name'] + '.zip')).write_bytes(raw)
        tar_name = 'DuktoNext-macos-' + label + '-compiled.tar.gz'
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            assert set(archive.namelist()) == {tar_name, tar_name + '.sha256'}
            for member in archive.infolist():
                assert not stat.S_ISLNK(member.external_attr >> 16) and member.file_size < 16 * 1024**2
            payload = archive.read(tar_name)
            declaration = archive.read(tar_name + '.sha256')
        tar_sha = hashlib.sha256(payload).hexdigest()
        assert declaration.decode('ascii').split()[0] == tar_sha
        contents, names = {}, set()
        with tarfile.open(fileobj=io.BytesIO(payload), mode='r:gz') as archive:
            for member in archive:
                path = PurePosixPath(member.name)
                assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name
                assert member.name not in names
                names.add(member.name)
                if member.isdir():
                    continue
                assert member.isfile() and member.size < 16 * 1024**2
                contents[member.name] = (member, archive.extractfile(member).read())
        assert contents['SOURCE-COMMIT.txt'][1].decode('ascii').strip() == commit
        license_bytes = subprocess.check_output(['git', 'show', commit + ':LICENSE'],
                                                cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert contents['LICENSE'][1] == license_bytes
        binaries = []
        for name in ('dukto-cli', 'dukto-gui.app/Contents/MacOS/dukto-gui'):
            member, binary = contents[name]
            assert member.mode & 0o111 and int.from_bytes(binary[:4], 'little') == 0xfeedfacf
            assert int.from_bytes(binary[4:8], 'little') == cpu
            binaries.append({'path': name, 'sha256': hashlib.sha256(binary).hexdigest(),
                             'architecture': architecture, 'executable': True})
        (distribution / tar_name).write_bytes(payload)
        (distribution / (tar_name + '.sha256')).write_bytes(declaration)
        records.append({'sourceCommit': commit, 'architecture': architecture, 'artifactId': item['id'],
                        'artifactUrl': run['html_url'] + '/artifacts/' + str(item['id']),
                        'artifactSha256': checksum, 'archive': tar_name, 'sha256': tar_sha,
                        'binaries': binaries, 'compileStepsPassed': True, 'dependenciesDeployed': False})
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'packages': records, 'bothArchitecturesCompiledAndVerified': True,
             'fullNativeRegressionQualifiedByThisReceipt': False, 'releaseQualified': False, 'deliveryComplete': False}
    (folder / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (distribution / 'BUILD-RECEIPT.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), folder / 'verification-driver.py')
    print(json.dumps({'sourceCommit': commit, 'bothArchitecturesCompiledAndVerified': True,
                      'artifactIds': [row['artifactId'] for row in records]}), flush=True)


if __name__ == '__main__':
    main()
