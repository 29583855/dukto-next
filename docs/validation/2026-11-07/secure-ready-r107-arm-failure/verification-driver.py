"""日期：2026-11-07；逐报告收验R107 ARM失败原件，不将46项通过当成完整成功。"""
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import runpy
import shutil
import subprocess


# 日期：2026-11-07；精确脚本、命令顺序、附件摘要、失败堆栈及通过报告全部按原件核对。
def main():
    root = Path.cwd()
    out = root / 'docs/validation/2026-11-07/secure-ready-r107-arm-failure'
    observation = json.loads((out / 'observation.json').read_text('utf-8'))
    assert observation['artifactSha256'] == hashlib.sha256((out / 'original.zip').read_bytes()).hexdigest()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    item = request(base + '/actions/artifacts/13556809821')
    job = request(base + '/actions/jobs/128267038396')
    run = request(base + '/actions/runs/42327794378')
    source = 'e220461bdd0a409b10f483a3aaa321db927975c3'
    assert run['head_sha'] == source and item['digest'] == 'sha256:' + observation['artifactSha256']
    assert job['status'] == 'completed' and job['conclusion'] == 'failure'
    assert [row['name'] for row in job['steps'] if row.get('conclusion') == 'failure'] == ['Protocol integration all independent cases']
    path = out / 'original/build/protocol-suite.json'
    suite = json.loads(path.read_text('utf-8'))
    assert suite['completed'] and not suite['passed'] and suite['sourceCommit'] == source and suite['platform'] == 'darwin'
    raw = subprocess.check_output(['git', 'show', source + ':scripts/ci_protocol.py'], cwd=root / '.cache/github-29583855-dukto-next-r28')
    assert hashlib.sha256(raw).hexdigest() == suite['scriptSha256']
    module = {'__name__': 'verified_failure_protocol'}
    exec(compile(raw, source + ':scripts/ci_protocol.py', 'exec'), module)
    module['commands'].__globals__['sys'] = SimpleNamespace(platform='darwin', executable='python')
    assert [row['name'] for row in suite['cases']] == [row[0] for row in module['commands'](Path('build'))]
    assert len(suite['cases']) == 47
    failed = [row for row in suite['cases'] if not row['passed']]
    assert len(failed) == 1 and failed[0]['name'] == 'overwrite-faults'
    assert failed[0]['exitCode'] == 1 and not failed[0]['reportCreated']
    verify_passed = runpy.run_path('.cache/collect-exact-native-r87.py')['verify_passed']
    reports = []
    for row in suite['cases']:
        if not row['passed']:
            continue
        report = path.parent / Path(row['report']).name
        assert row['exitCode'] == 0 and row['reportCreated']
        assert hashlib.sha256(report.read_bytes()).hexdigest() == row['reportSha256']
        verify_passed(json.loads(report.read_text('utf-8')))
        reports.append({'path': report.relative_to(root).as_posix(), 'sha256': row['reportSha256']})
    log = (out / 'job.log').read_text('utf-8')
    assert "AssertionError: {'code': 6, 'event': 'error', 'eventVersion': 1, 'message': '源文件路径在读取期间已被替换', 'stage': 'read'}" in log
    assert 'assert error["code"] in ((3, 6) if fault == "same-size-mtime-source-change" else (3, 4)), error' in log
    source_fixture = subprocess.check_output(['git', 'show', source + ':tests/transfer_faults_integration.py'], cwd=root / '.cache/github-29583855-dukto-next-r28')
    assert 'for fault in ("same-size-mtime-source-change", "revoke", "root-reconfigure"):' in source_fixture.decode('utf-8')
    receipt = dict(observation, observedUtc=datetime.now(timezone.utc).isoformat(), failureVerifiedAsFailure=True,
                   passingReportsVerified=46, failingCase=failed[0], missingReportNotInferredPassed=True,
                   observedFailure={'code': 6, 'stage': 'read', 'message': '源文件路径在读取期间已被替换'},
                   preciseFixtureFailureEstablished=True, productionFixOrCompleteRegressionNotClaimed=True,
                   successfulReportEvidence=reports, passed=False, fullRegressionPassed=False,
                   releaseQualified=False, deliveryComplete=False)
    assert not (out / 'receipt.json').exists()
    (out / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, out / 'verification-driver.py')
    print(json.dumps({'failureVerifiedAsFailure': True, 'passingReportsVerified': 46,
                      'failingCase': failed[0]['name'], 'fullRegressionPassed': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
