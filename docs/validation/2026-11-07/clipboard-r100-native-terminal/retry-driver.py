"""日期：2026-11-07；保全首轮后仅补原Intel报告上传故障任务，不重跑三个已成功平台。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy


# 日期：2026-11-07；提交请求前先保存账目，超时后必须查询实际状态而不能盲目重发。
def main():
    ledger_path = Path('.cache/r100-intel-upload-retry.json')
    assert not ledger_path.exists(), 'Inspect existing persisted request and actual run before retry'
    evidence_path = Path('docs/validation/2026-11-07/clipboard-r100-native-terminal/first-attempt-qualified-subset.json')
    evidence = json.loads(evidence_path.read_text('utf-8'))
    assert evidence['failureJobId'] == 128115892367 and evidence['verifiedProtocolReports'] == 142
    assert evidence['firstAttempt']['run_attempt'] == 1 and not evidence['intelProtocolQualified']
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/42282812778')
    assert run['head_sha'] == evidence['sourceCommit'] and run['run_attempt'] == 1
    assert run['status'] == 'completed' and run['conclusion'] == 'failure'
    jobs = request(base + '/actions/runs/42282812778/jobs?per_page=100')['jobs']
    assert len(jobs) == 4 and all(job['status'] == 'completed' for job in jobs)
    assert [job['id'] for job in jobs if job['conclusion'] != 'success'] == [128115892367]
    ledger = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': run['head_sha'],
              'originalRunId': run['id'], 'originalJobId': 128115892367,
              'originalAttempt': 1, 'firstAttemptPreservedSha256': hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
              'scope': 'Only original failed Intel job; first-attempt failure and all downloaded originals retained',
              'requestAttempted': True, 'responseReceived': False,
              'qualificationPending': True, 'releaseQualified': False, 'deliveryComplete': False}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    request(base + '/actions/jobs/128115892367/rerun', 'POST')
    ledger['responseReceived'] = True
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps(ledger), flush=True)


if __name__ == '__main__':
    main()
