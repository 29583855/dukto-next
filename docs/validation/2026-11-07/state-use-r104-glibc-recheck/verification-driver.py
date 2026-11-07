"""日期：2026-11-07；独立核验Ubuntu真实构建、23核心和维护多进程原件，不授予失败协议资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

SOURCE = '9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6'


# 日期：2026-11-07；原退出、22份XML、213冻结输入与POSIX拒绝逐项核对，保留首次编译失败。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/state-use-r104-glibc-recheck'
    collection = json.loads((output / 'collection-result.json').read_text('utf-8'))
    assert collection['remoteExitCode'] == 0 and collection['passed']
    target = output / 'recheck-results'
    driver = json.loads((target / 'driver-result.json').read_text('utf-8'))
    assert driver['passed'] and driver['binaryUnchanged']
    assert driver['cases'] == [{'name': name, 'exitCode': 0} for name in ('build', 'ctest', 'task-store', 'doctor', 'service')]
    original = json.loads((output / 'results/exit-codes.json').read_text('utf-8'))
    assert original == [{'name': 'configure', 'exitCode': 0}, {'name': 'build', 'exitCode': 1}]
    assert 'identity_tests.cpp' in (output / 'results/build.log').read_text('utf-8')
    archive = root / '.cache/source-state-use-r104-final.tar.gz'
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == collection['sourceSnapshotSha256']
    manifest, files = runpy.run_path('scripts/source_snapshot.py')['read_archive'](archive)
    inputs = json.loads((output / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 213
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    for row in inputs:
        raw = files[row['path']]
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert subprocess.check_output(['git', 'show', SOURCE + ':' + row['path']], cwd=checkout) == raw
    assert re.search(r'^100% tests passed, 0 tests failed out of 23$', (target / 'ctest.log').read_text('utf-8'), re.M)
    verify_xml = runpy.run_path('.cache/verify-diagnostics-r103.py')['verify_xml']
    xmls = sorted((output / 'build/Testing/QtTest').glob('*.xml'))
    assert len(xmls) == 22
    for path in xmls:
        verify_xml(path)
    identity = (output / 'build/Testing/QtTest/identity-tests.log').read_text('utf-8').splitlines()
    assert identity.count('PASS   : IdentityTests::stateDirectoryUseGuard()') == 1
    task = json.loads((target / 'task-store.json').read_text('utf-8'))
    assert task['passed'] and task['competingProcesses'] == task['schemaMigrationProcesses'] == task['contendedInitializationProcesses'] == 8
    for key in ('activeLeaseRefused', 'leaseRecoveredAfterKill', 'oldFifteenColumnsUnchanged', 'activeInitializationOwnerPreserved'):
        assert task[key]
    guard = task['stateDirectoryUse']
    assert guard['sharedProcesses'] == 8 and guard['firstRefusalSeconds'] < 2
    for key in ('exclusiveRefusedUntilLastReaderExited', 'sharedAndExclusiveRefusedDuringMaintenance',
                'recoveredAfterKill', 'ordinaryDataUnchanged', 'nonemptyGuardRefusedWithoutTruncation'):
        assert guard[key]
    assert guard['posixChecks'] == ['broad-permissions-refused-without-chmod', 'hard-link-refused',
                                   'symbolic-link-refused-without-touching-target']
    doctor = json.loads((target / 'doctor.json').read_text('utf-8'))
    assert doctor['passed'] and doctor['binaryUnchanged'] and len(doctor['checks']) == 12 and len(doctor['posixLinkChecks']) == 2
    assert doctor['binarySha256'] == driver['binarySha256']['dukto-cli']
    assert json.loads((target / 'service.json').read_text('utf-8'))['passed']
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    proof = helper['proof']
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': SOURCE,
             'passed': True, 'verifiedCoreTargets': 23, 'verifiedOriginalQtXml': 22,
             'verifiedFrozenBuildInputs': 213, 'binarySha256': driver['binarySha256'],
             'binaryUnchanged': True, 'newStateDirectoryUseMethodPassed': True,
             'stateUseEightProcessPosixChecksPassed': True, 'doctorChecks': 12, 'doctorPosixLinkChecks': 2,
             'coreReport': proof(target / 'ctest.log'), 'processReport': proof(target / 'task-store.json'),
             'doctorReport': proof(target / 'doctor.json'), 'serviceReport': proof(target / 'service.json'),
             'initialCompilationFailureRetained': True, 'fullProtocolSuiteQualified': False,
             'r105TaskItemsTimeoutStillRetained': True, 'entireR04Qualified': False,
             'releaseQualified': False, 'deliveryComplete': False}
    path = output / 'receipt.json'
    assert not path.exists()
    path.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': SOURCE, 'coreTargets': 23, 'xmlReports': 22, 'inputs': 213, 'passed': True}))


if __name__ == '__main__':
    main()
