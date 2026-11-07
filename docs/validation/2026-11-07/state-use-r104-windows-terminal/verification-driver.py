"""日期：2026-11-07；核验失败Windows作业的真实通过子集，保留完整失败与跳过边界。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace

SOURCE = '9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6'


# 日期：2026-11-07；按提交重建执行清单并逐摘要核对50份通过报告，绝不把缺失失败报告计为通过。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/state-use-r104-windows-terminal'
    observation = json.loads((output / 'observation.json').read_text('utf-8'))
    assert observation['run']['head_sha'] == SOURCE and observation['run']['id'] == 42316601470
    job = observation['job']
    assert job['id'] == 128230608444 and job['status'] == 'completed' and job['conclusion'] == 'failure'
    artifact = observation['artifact']
    archive = output / 'validation-windows-2022.zip'
    assert artifact['id'] == 13555220671
    archive_digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    assert artifact['digest'] == 'sha256:' + archive_digest
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    folder = output / 'validation-windows-2022'
    path = folder / 'build/protocol-suite.json'
    suite = json.loads(path.read_text('utf-8'))
    assert suite['completed'] and not suite['passed'] and suite['sourceCommit'] == SOURCE
    source = subprocess.check_output(['git', 'show', SOURCE + ':scripts/ci_protocol.py'],
                                     cwd=root / '.cache/github-29583855-dukto-next-r28')
    source = source.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    assert suite['platform'] == 'win32' and suite['scriptSha256'] == hashlib.sha256(source).hexdigest()
    module = {'__name__': 'r104_exact_protocol'}
    exec(compile(source, SOURCE + ':scripts/ci_protocol.py', 'exec'), module)
    module['commands'].__globals__['sys'] = SimpleNamespace(platform='win32', executable='python')
    assert [row['name'] for row in suite['cases']] == [row[0] for row in module['commands'](Path('build'))]
    failures = [row for row in suite['cases'] if not row['passed']]
    assert len(failures) == 1 and failures[0]['name'] == 'task-items'
    assert failures[0]['exitCode'] == 1 and not failures[0]['reportCreated']
    assert not (folder / 'build/task-items.json').exists()
    passed = []
    for case in suite['cases']:
        if case['name'] == 'task-items':
            continue
        report = path.parent / case['report'].replace('\\', '/').split('/')[-1]
        assert case['reportCreated'] and case['passed'] and case['exitCode'] == 0
        assert hashlib.sha256(report.read_bytes()).hexdigest() == case['reportSha256']
        helper['verify_passed'](json.loads(report.read_text('utf-8')))
        passed.append(dict(helper['proof'](report.relative_to(root)), name=case['name']))
    assert len(passed) == 50
    steps = {step['name']: step for step in job['steps']}
    assert steps['Protocol integration all independent cases']['conclusion'] == 'failure'
    skipped = ['Real disk exhaustion on isolated Linux tmpfs', 'Real TLS transfer disk exhaustion and recovery']
    assert all(steps[name]['conclusion'] == 'skipped' for name in skipped)
    assert not (folder / 'build/disk.json').exists() and not (folder / 'build/parallel-disk.json').exists()
    log = (output / 'job.log').read_bytes()
    assert hashlib.sha256(log).hexdigest() == 'c0c81cd4e8e30595283abed8bc47872701bd477baf3eb6f456e8eeb025321fe2'
    assert b'original.rmdir()' in log and b'The directory is not empty' in log and b'client' in log
    # 日期：2026-11-07；维护占用报告自身需完整通过，不能仅据作业总体结果推断其失败或成功。
    guard = json.loads((folder / 'build/task-store.json').read_text('utf-8'))
    assert guard['passed'] and guard['competingProcesses'] == 8 and guard['leaseRecoveredAfterKill']
    state = guard['stateDirectoryUse']
    assert state['sharedProcesses'] == 8 and state['firstRefusalSeconds'] < 2
    for name in ('exclusiveRefusedUntilLastReaderExited', 'sharedAndExclusiveRefusedDuringMaintenance',
                 'recoveredAfterKill', 'ordinaryDataUnchanged', 'nonemptyGuardRefusedWithoutTruncation'):
        assert state[name]
    assert state['posixChecks'] == []
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': SOURCE,
             'originalJobConclusion': 'failure', 'originalProtocolPassed': False,
             'originalFailureRetained': True, 'protocolCaseCount': len(suite['cases']),
             'verifiedPassedProtocolReports': passed, 'failedCases': failures,
             'linuxOnlyDiskStepsNotApplicable': skipped, 'missingDiskReportsNotInvented': True,
             'stateDirectoryEightProcessNativeReportVerified': True,
             'archiveSha256': archive_digest, 'jobLogSha256': hashlib.sha256(log).hexdigest(),
             'verificationPassedWithinExplicitSubset': True,
             'fullR104ProtocolQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    target = output / 'subset-verification.json'
    assert not target.exists()
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': SOURCE, 'passedReports': len(passed), 'originalFailureRetained': True,
                      'fullR104ProtocolQualified': False}))


if __name__ == '__main__':
    main()
