"""日期：2026-11-07；先保存首轮取消及其余三平台原件，再仅补跑未启动的ARM任务。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys

COMMIT = '88f33b2c83f2950307c362fb64c693f7e9e5929d'
RUN = 42252931531
JOB = 128012531171


# 日期：2026-11-07；只接受原ARM零步骤容量取消及其他平台成功，不对真实测试失败自动补跑。
def main():
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    focused = runpy.run_path('.cache/collect-r96-native-regression.py')
    complete = runpy.run_path('.cache/collect-r96-complete-native.py')
    ledger_path = Path('.cache/r96-arm-capacity-terminal-retry.json')
    assert not ledger_path.exists(), 'Retry intent exists; query current attempt instead of resending'
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    assert run['head_sha'] == COMMIT and run['run_attempt'] == 1
    if run['status'] != 'completed':
        print(json.dumps({'originalRunStillRunning': True, 'retrySent': False}), flush=True)
        return
    jobs = request(base + '/actions/runs/' + str(RUN) + '/attempts/1/jobs?per_page=100')['jobs']
    assert len(jobs) == 4 and all(job['status'] == 'completed' for job in jobs)
    arm, = [job for job in jobs if job['id'] == JOB]
    assert arm['conclusion'] == 'cancelled' and not arm['steps'] and not arm['runner_name']
    assert all(job['conclusion'] == 'success' for job in jobs if job['id'] != JOB)
    assert run['conclusion'] in ('cancelled', 'failure')
    output = Path('docs/validation/2026-11-07/boundary-r96-native-terminal')
    result = subprocess.run([sys.executable, '-X', 'utf8', '.cache/collect-r96-complete-native.py', 'native'],
                            capture_output=True, timeout=600)
    assert result.returncode != 0, 'First cancelled run cannot qualify as a complete pass'
    (output / 'attempt-1-collector.log').write_bytes(result.stdout + result.stderr)
    observation = json.loads((output / 'terminal-artifact-observation.json').read_text('utf-8'))
    assert observation['sourceCommit'] == COMMIT and observation['allArtifactDigestsVerified']
    cores = [complete['verify_core'](p, helper, focused) for p in output.iterdir()
             if p.is_dir() and p.name.startswith('core-validation-')]
    suites = [helper['protocol'](p, COMMIT) for p in output.rglob('protocol-suite.json')]
    assert len(cores) == len(suites) == 3
    assert sum(len(item['expectedFailures']) for item in cores) == 1
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
             'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url', 'run_attempt')},
             'jobs': [{k: job[k] for k in ('id', 'name', 'status', 'conclusion', 'runner_name', 'steps')}
                      for job in jobs], 'cores': cores, 'protocolSuites': suites,
             'remainingThreePlatformsOriginalReportsVerified': True,
             'originalArmApplicationTestsExecuted': False,
             'originalRunQualified': False, 'retryOnlyUnstartedCapacityJob': JOB,
             'releaseQualified': False, 'deliveryComplete': False}
    proof_path = output / 'attempt-1-partial-verification.json'
    assert not proof_path.exists()
    proof_path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'capacity-retry-driver.py')
    ledger = {'observedUtc': value['observedUtc'], 'sourceCommit': COMMIT, 'runId': RUN,
              'originalJobId': JOB, 'originalAttempt': 1, 'responseReceived': False,
              'retryAttempted': True, 'originalEvidence': helper['proof'](proof_path)}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    try:
        response = request(base + '/actions/jobs/' + str(JOB) + '/rerun', 'POST')
    except Exception as error:
        ledger['requestError'] = str(error)[:1500]
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
        raise
    ledger.update(responseReceived=True, response=response)
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps({'remainingPlatformsVerified': 3,
                      'protocolReports': sum(item['cases'] for item in suites),
                      'armRetryAccepted': True, 'originalCancelledAttemptPreserved': True}), flush=True)


if __name__ == '__main__':
    main()
