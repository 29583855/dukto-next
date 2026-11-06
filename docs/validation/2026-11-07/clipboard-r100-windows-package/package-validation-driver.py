"""日期：2026-11-07；从固定Git源码副本打包当前Windows程序，独立保留部署及迁移结果。"""
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import zipfile


# 日期：2026-11-07；二进制及338份冻结源码前后不变，部署测试使用实际ZIP和仅系统PATH。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/clipboard-r100-windows-package'
    assert not output.exists()
    full = root / 'docs/validation/2026-11-07/clipboard-r100-qualified/verified-receipt.json'
    verified = json.loads(full.read_text('utf-8'))
    assert verified['passed'] and len(verified['windows']) == 2
    assert verified['incrementalBuild'] and not verified['freshFull23TargetsRun']
    assert len(verified['buildInputs']) == 210
    for row in verified['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    prior = json.loads((root / 'docs/validation/2026-11-07/clipboard-r100-windows/driver-result.json').read_text('utf-8'))
    ucrt, = [row for row in prior['cases'] if row['toolchain'] == 'ucrt']
    assert ucrt['passed'] and len(ucrt['guiTargets']) == 4 and len(ucrt['unchangedCoreTestBinaries']) == 19
    for name, expected in ucrt['unchangedCoreTestBinaries'].items():
        assert hashlib.sha256((root / 'build/windows-ucrt' / (name + '.exe')).read_bytes()).hexdigest() == expected
    frozen = json.loads((root / '.cache/windows-r100-package-source.json').read_text('utf-8'))
    assert frozen['sourceCommit'] == 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3' and frozen['buildInputsVerified'] == 210
    source = Path(frozen['sourceRoot'])
    assert len(frozen['sourceFiles']) == 338
    for row in frozen['sourceFiles']:
        assert hashlib.sha256((source / row['path']).read_bytes()).hexdigest() == row['sha256']
    binary_hashes = {name: hashlib.sha256((root / 'build/windows-ucrt' / name).read_bytes()).hexdigest()
                     for name in ('dukto-cli.exe', 'dukto-gui.exe')}
    output.mkdir(parents=True)
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']('ucrt')
    with (output / 'build-binding.log').open('xb') as log:
        subprocess.run([str(root / '.tools/msys64/ucrt64/bin/cmake.exe'), '--build',
                        str(root / 'build/windows-ucrt'), '--config', 'Release', '--parallel', '2'],
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    assert 'ninja: no work to do.' in (output / 'build-binding.log').read_text('utf-8')
    assert all(hashlib.sha256((root / 'build/windows-ucrt' / name).read_bytes()).hexdigest() == sha
               for name, sha in binary_hashes.items())
    distribution = root / 'dist/windows-preview-20261107-r100-clipboard'
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
    value = {'sourceCommit': frozen['sourceCommit'], 'sourceFiles': 338, 'buildInputsVerified': 210,
             'binaries': binary_hashes, 'allFrozenInputsUnchanged': unchanged,
             'guiAndUnchangedCoreEvidence': str(full.relative_to(root)),
             'guiTargetsRechecked': 4, 'existingCoreBinariesUnchanged': 19, 'freshFull23TargetsRun': False, 'cases': cases, 'completed': True, 'passed': passed,
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
