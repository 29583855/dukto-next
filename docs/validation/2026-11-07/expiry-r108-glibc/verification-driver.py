"""日期：2026-11-07；独立核对Ubuntu新源码、真实失败、同二进制迁移重验及清理原件。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；原失败不被重验覆盖，只授予真实执行过的两个核心目标和进程专项资格。
def main():
    root = Path.cwd()
    base = root / 'docs/validation/2026-11-07'
    original = base / 'expiry-r108-glibc'
    recheck = base / 'expiry-r108-glibc-migration-v3'
    driver = json.loads((original / 'results/driver-result.json').read_text('utf-8'))
    collection = json.loads((original / 'collection-result.json').read_text('utf-8'))
    revised = json.loads((recheck / 'recheck-result.json').read_text('utf-8'))
    processes = json.loads((recheck / 'migration.json').read_text('utf-8'))
    assert collection['remoteExitCode'] == 1 and collection['collectionExitCode'] == 0 and not collection['passed']
    assert not driver['passed'] and driver['binaryUnchanged']
    rows = {row['name']: row for row in driver['cases']}
    assert set(rows) == {'configure', 'build', 'cleanup-core', 'task-store-processes'}
    assert all(rows[name]['exitCode'] == 0 for name in ('configure', 'build', 'cleanup-core'))
    assert rows['task-store-processes']['exitCode'] == 1
    failure = (original / 'results/task-store-processes.log').read_text('utf-8')
    assert 'PRAGMA user_version' in failure and '== (2,)' in failure and 'AssertionError' in failure
    assert revised['exitCode'] == 0 and revised['passed'] and revised['binaryUnchanged']
    assert processes['passed'] and processes['migratedSchemaVersion'] == 3
    assert processes['schemaMigrationProcesses'] == processes['schemaTwoMigrationProcesses'] == 8
    assert processes['oldFifteenColumnsUnchanged'] and processes['oldSixteenColumnsUnchanged']
    assert revised['fixtureSha256'] == processes['scriptSha256'] == hashlib.sha256((root / 'tests/task_store_integration.py').read_bytes()).hexdigest()
    for name, digest in driver['binarySha256'].items():
        assert revised['binarySha256'][name] == digest
    snapshot = runpy.run_path('scripts/source_snapshot.py')
    archive = root / '.cache/source-expiry-r108.tar.gz'
    manifest, values = snapshot['read_archive'](archive)
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == collection['sourceSnapshotSha256']
    inputs = json.loads((base / 'expiry-r108-qualified/receipt.json').read_text('utf-8'))['buildInputs']
    names = [row['path'] for row in inputs]
    drift = [name for name in names if values[name] != (root / name).read_bytes()]
    assert drift == ['tests/task_store_integration.py']
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    program = '''from pathlib import Path
import hashlib,json,subprocess
root=Path('/home/dukto/expiry-r108')
names=json.loads(INPUT_NAMES)
data={'inputs':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in names},'binarySha256':{name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in ['dukto-cli','task-store-tests','expired-task-cleanup-tests','task-store-probe']},'cxx14': '-std=c++14' in (root/'build/build.ninja').read_text(encoding='utf-8'),'qtVersion':subprocess.check_output(['qmake','-query','QT_VERSION']).decode().strip()}
print(json.dumps(data))
'''.replace('INPUT_NAMES', repr(json.dumps(names)))
    checked = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=90)
    assert checked.returncode == 0 and not checked.stderr
    observed = json.loads(checked.stdout)
    assert observed['cxx14'] and observed['qtVersion'] == '5.15.13'
    assert observed['binarySha256'] == revised['binarySha256']
    assert observed['inputs'] == {name: manifest['files'][name]['sha256'] for name in names}
    testing = original / 'results/Testing/QtTest'
    for name in ('task-store-tests', 'expired-task-cleanup-tests'):
        suite = ET.parse(testing / (name + '.xml')).getroot()
        assert suite.get('errors') == suite.get('failures') == '0'
        assert all(case.get('result') == 'pass' for case in suite.findall('testcase'))
    assert '18 passed, 0 failed, 0 skipped' in (testing / 'expired-task-cleanup-tests.log').read_text('utf-8')
    assert '100% tests passed, 0 tests failed out of 2' in (original / 'results/cleanup-core.log').read_text('utf-8')
    (original / 'independent-vm-inputs.json').write_text(json.dumps(observed, indent=2) + '\n', 'utf-8')
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
               'sourceBuildSucceeded': True, 'coreTargetsVerified': 2, 'qtXmlReports': 2,
               'cleanupQtRowsIncludingInitAndCleanup': 18, 'cxxStandard': 14, 'qtVersion': observed['qtVersion'],
               'originalDriverExitCode': 1, 'originalFixtureVersionMismatchRetained': True,
               'correctedFixtureRecheckExitCode': 0, 'schemaOneMigrationProcesses': 8,
               'schemaTwoMigrationProcesses': 8, 'productionInputsUnchanged': True,
               'buildInputsVerifiedOnVm': 216, 'testFixtureDrift': drift,
               'sameBinariesBeforeAndAfterRecheckVerified': revised['binarySha256'],
               'freshFullCoreSuiteRun': False, 'fullTaskItemsRerun': False,
               'originalSmallFileTimeoutResolved': False, 'globalDiskBudgetImplemented': False,
               'releaseQualified': False, 'deliveryComplete': False}
    evidence = []
    for folder in (original, recheck):
        for path in sorted(folder.rglob('*')):
            if path.is_file() and path.suffix in ('.json', '.xml', '.log', '.py', '.stderr') and path.name != 'receipt.json':
                evidence.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    receipt['evidence'] = evidence
    assert not (original / 'receipt.json').exists()
    (original / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, original / 'verification-driver.py')
    print(json.dumps({key: value for key, value in receipt.items() if key not in ('evidence', 'sameBinariesBeforeAndAfterRecheckVerified')}))


if __name__ == '__main__':
    main()
