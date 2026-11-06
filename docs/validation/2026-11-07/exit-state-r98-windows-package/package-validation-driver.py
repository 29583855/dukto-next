"""日期：2026-11-07；从固定Git源码副本打包当前Windows程序，独立保留部署及迁移结果。"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import zipfile


# 日期：2026-11-07；二进制及333份冻结源码前后不变，部署测试使用实际ZIP和仅系统PATH。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/exit-state-r98-windows-package'
    assert not output.exists()
    full = root / 'docs/validation/2026-11-07/exit-state-r98-full-windows/verified-receipt.json'
    verified = json.loads(full.read_text('utf-8'))
    assert verified['sourceCommit'] == 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7' and verified['passed']
    frozen = json.loads((root / '.cache/windows-r98-package-source.json').read_text('utf-8'))
    assert frozen['sourceCommit'] == verified['sourceCommit'] and frozen['buildInputsVerified'] == 210
    source = Path(frozen['sourceRoot'])
    assert len(frozen['sourceFiles']) == 333
    for row in frozen['sourceFiles']:
        assert hashlib.sha256((source / row['path']).read_bytes()).hexdigest() == row['sha256']
    binary_hashes = {name: hashlib.sha256((root / 'build/windows-ucrt' / name).read_bytes()).hexdigest()
                     for name in ('dukto-cli.exe', 'dukto-gui.exe')}
    output.mkdir(parents=True)
    distribution = root / 'dist/windows-preview-20261107-r98-exit-state'
    assert not distribution.exists()
    package_command = [sys.executable, '-X', 'utf8', str(source / 'scripts/package_windows.py'),
                       '--build-directory', str(root / 'build/windows-ucrt'),
                       '--qt-prefix', str(root / '.tools/msys64/ucrt64'), '--output', str(distribution)]
    with (output / 'package.log').open('xb') as log:
        packaged = subprocess.run(package_command, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
    cases = [{'name': 'deploy', 'exitCode': packaged.returncode}]
    archive = distribution / 'DuktoNext-windows-x64-preview.zip'
    if packaged.returncode == 0:
        with zipfile.ZipFile(archive) as bundle:
            prefix = 'DuktoNext-windows-x64-preview/'
            manifest = json.loads(bundle.read(prefix + 'package-manifest.json'))
            assert len(manifest['sourceFiles']) == len(frozen['sourceFiles'])
            assert {row['path']: row['sha256'] for row in manifest['sourceFiles']} == {
                row['path']: row['sha256'] for row in frozen['sourceFiles']}
            for name, expected in binary_hashes.items():
                assert hashlib.sha256(bundle.read(prefix + name)).hexdigest() == expected
        report = output / 'runtime.json'
        with (output / 'runtime.log').open('xb') as log:
            runtime = subprocess.run([sys.executable, '-X', 'utf8',
                                      str(source / 'tests/windows_package_integration.py'),
                                      str(archive), '--report', str(report)],
                                     stdout=log, stderr=subprocess.STDOUT, timeout=3600)
        cases.append({'name': 'relocated-system-path-runtime', 'exitCode': runtime.returncode})
    unchanged = all(hashlib.sha256((source / row['path']).read_bytes()).hexdigest() == row['sha256']
                    for row in frozen['sourceFiles'])
    unchanged = unchanged and all(hashlib.sha256((root / 'build/windows-ucrt' / name).read_bytes()).hexdigest() == digest
                                  for name, digest in binary_hashes.items())
    passed = unchanged and len(cases) == 2 and all(row['exitCode'] == 0 for row in cases)
    value = {'sourceCommit': frozen['sourceCommit'], 'sourceFiles': 333, 'buildInputsVerified': 210,
             'binaries': binary_hashes, 'allFrozenInputsUnchanged': unchanged,
             'coreEvidence': str(full.relative_to(root)), 'cases': cases, 'completed': True, 'passed': passed,
             'cleanSystemQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    if archive.exists():
        value['archive'] = archive.relative_to(root).as_posix()
        with archive.open('rb') as stream:
            value['archiveSha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (output / 'driver-result.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
