"""日期：2026-11-07；保全R100首次终态与附件上传故障，只授予已有完整原件的三平台协议子集。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
RUN = 42282812778
OUTPUT = Path('docs/validation/2026-11-07/clipboard-r100-native-terminal')


# 日期：2026-11-07；保留首次观察的原字节，不用恢复后的运行身份覆盖失败记录。
def preserve(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


# 日期：2026-11-07；仅当业务步骤成功且唯一故障为报告上传时允许登记基础设施故障。
def main():
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    observation = json.loads((OUTPUT / 'terminal-artifact-observation.json').read_text('utf-8'))
    assert observation['sourceCommit'] == COMMIT
    assert observation['run']['id'] == RUN and observation['run']['run_attempt'] == 1
    assert observation['run']['status'] == 'completed' and observation['run']['conclusion'] == 'failure'
    assert observation['allArtifactDigestsVerified'] and len(observation['artifacts']) == 7
    failed, = [job for job in observation['jobs'] if job['conclusion'] == 'failure']
    assert failed['id'] == 128115892367 and failed['name'] == 'native (macos-15-intel, brew)'
    failures = [step['name'] for step in failed['steps'] if step['conclusion'] == 'failure']
    assert failures == ['Preserve validation logs']
    for name in ('Compile', 'Core and GUI controller tests', 'Protocol integration all independent cases',
                 'Cocoa main window server navigation', 'Native Cocoa GUI render and process recovery'):
        step, = [step for step in failed['steps'] if step['name'] == name]
        assert step['conclusion'] == 'success'
    logs = []
    for job in observation['jobs']:
        path = OUTPUT / ('first-attempt-job-' + str(job['id']) + '.log')
        if not path.exists():
            if job['id'] == failed['id']:
                preserve(path, Path('.cache/r100-native-intel-original-job.log').read_bytes())
            else:
                preserve(path, request('/repos/29583855/dukto-next/actions/jobs/' + str(job['id']) + '/logs', binary=True))
        logs.append(helper['proof'](path))
    intel_log = (OUTPUT / ('first-attempt-job-' + str(failed['id']) + '.log')).read_text('utf-8-sig')
    assert 'Failed to CreateArtifact' in intel_log and 'Request timeout:' in intel_log
    assert 'after 5 attempts' in intel_log
    suites = []
    for runner in ('windows-2022', 'ubuntu-22.04', 'macos-15'):
        job, = [job for job in observation['jobs'] if job['name'].startswith('native (' + runner + ',')]
        assert job['conclusion'] == 'success'
        paths = list((OUTPUT / ('validation-' + runner)).rglob('protocol-suite.json'))
        assert len(paths) == 1
        suites.append(dict(helper['protocol'](paths[0], COMMIT), runner=runner, jobId=job['id']))
    assert sum(suite['cases'] for suite in suites) == 142
    assert not (OUTPUT / 'validation-macos-15-intel').exists()
    core_path = Path('docs/validation/2026-11-07/clipboard-r100-native-core/receipt.json')
    core = json.loads(core_path.read_text('utf-8'))
    assert core['sourceCommit'] == COMMIT and core['coreTargetsEach'] == 23
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
             'firstAttempt': observation['run'], 'terminalObservation': helper['proof'](OUTPUT / 'terminal-artifact-observation.json'),
             'jobLogs': logs, 'failureJobId': failed['id'], 'failedStep': failures[0],
             'failureCategory': 'GitHub artifact service CreateArtifact request timed out after five attempts',
             'intelBusinessStepsPassedAccordingToJobMetadata': True,
             'intelProtocolOriginalReportsAvailable': False, 'intelProtocolQualified': False,
             'existingFourPlatformCoreEvidence': helper['proof'](core_path),
             'verifiedProtocolSuites': suites, 'verifiedProtocolReports': 142,
             'allProtocolOriginalReportsVerified': False, 'fullNativeRegressionQualified': False,
             'retryScope': 'Only the failed original Intel job; original three successful jobs retained',
             'collectorFailurePreserved': True, 'deliveryComplete': False, 'releaseQualified': False}
    path = OUTPUT / 'first-attempt-qualified-subset.json'
    if path.exists():
        old = json.loads(path.read_text('utf-8'))
        assert {k: v for k, v in old.items() if k != 'observedUtc'} == {k: v for k, v in value.items() if k != 'observedUtc'}
    else:
        preserve(path, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    preserve(OUTPUT / 'first-collector-failure.json', (json.dumps({
        'date': '2026-11-07', 'exitCode': 1,
        'driver': helper['proof'](Path('.cache/collect-r100-native-terminal.py')),
        'message': 'AssertionError: Original terminal failure preserved; inspect without relaxing qualification',
        'expectedRejection': True, 'qualificationGranted': False}, indent=2) + '\n').encode('utf-8'))
    shutil.copyfile('.cache/collect-r100-native-terminal.py', OUTPUT / 'first-collector-driver.py')
    shutil.copyfile(__file__, OUTPUT / 'first-attempt-preservation-driver.py')
    print(json.dumps({'originalRunFailurePreserved': True, 'verifiedProtocolReports': 142,
                      'intelUploadFailureOnly': True, 'wholeRegressionQualified': False}))


if __name__ == '__main__':
    main()
