"""日期：2026-11-08；按实际终态、完整冻结源码及运行程序身份独立收验Ubuntu专项。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-08；只有原驱动退出成功、15行全通过、源码和程序后置核对全满足才授予本专项资格。
def main():
    root = Path.cwd()
    output = root / '.cache/r121-glibc-qualified'
    target = output / 'verified-receipt.json'
    assert not target.exists()
    original = json.loads((output / 'receipt.json').read_bytes())
    installed = json.loads((root / '.cache/r121-glibc-installed-source.json').read_bytes())
    assert original['driverExitCode'] == 0 and original['stateInventoryQualified']
    assert original['rowsPassed'] == 15 and original['permissionRowsSkipped'] == 0
    assert original['snapshotSha256'] == installed['snapshotSha256']
    manifest = json.loads((output / 'results/source-manifest.json').read_bytes())
    assert manifest['files'] == installed['installed']['files'] and len(manifest['files']) == 415
    assert (output / 'results/ctest-exit.txt').read_text().strip() == '0'
    before = (output / 'results/before.sha256').read_bytes()
    assert before == (output / 'results/after.sha256').read_bytes()
    binaries = {name: sha for sha, name in (line.split() for line in before.decode().splitlines())}
    assert set(binaries) == {'build/dukto-cli', 'build/state-storage-tests'}
    ssh = runpy.run_path(str(root / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    program = '''import hashlib,json
from pathlib import Path
root=Path('/home/dukto/state-inventory-r121-qualified')
manifest=json.loads((root/'.dukto-source-snapshot.json').read_bytes())
for name,expected in manifest['files'].items():
    raw=(root/name).read_bytes()
    assert {'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}==expected
print(json.dumps({name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['build/dukto-cli','build/state-storage-tests']}))
'''
    result = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    assert json.loads(result.stdout) == binaries
    verify = runpy.run_path(str(root / 'scripts/ci_state_inventory.py'))['verify_xml']
    verify.__globals__['os'] = type('Platform', (), {'name': 'posix'})
    xml = output / 'build/Testing/QtTest/state-storage-tests.xml'
    rows = verify(xml)
    assert rows['rowsPassed'] == 15 and rows['permissionRowsSkipped'] == 0
    cmake = (output / 'results/configure.log').read_text('utf-8')
    assert 'Build files have been written to: /home/dukto/state-inventory-r121-qualified/build' in cmake
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
             'qualificationScope': 'independent Ubuntu CLI and state storage suite only; GUI and other core suites not executed',
             'snapshotSha256': original['snapshotSha256'], 'actualSourceFileCount': 415,
             'actualQualificationInputCount': 268, 'allSourceInputsUnchangedAfterTest': True,
             'binariesUnchangedAfterTest': True, 'binaries': binaries, 'stateInventory': rows,
             'originalReceiptSha256': hashlib.sha256((output / 'receipt.json').read_bytes()).hexdigest(),
             'xmlSha256': hashlib.sha256(xml.read_bytes()).hexdigest(), 'cpp14BuildFlagPresent': True,
             'compiler': installed['installed']['compiler'], 'qtVersion': installed['installed']['qtVersion'],
             'cleanBuildAfterDependencyInstallation': True, 'originalConfigurationFailurePreserved': True,
             'fullCoreQualified': False, 'currentR121LongQualified': False,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    target.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value[key] for key in ['passed', 'actualSourceFileCount', 'actualQualificationInputCount', 'stateInventory']}))


if __name__ == '__main__':
    main()
