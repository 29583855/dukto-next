"""日期：2026-11-07；单次派发精确R100双Mac独立APFS真实盘满专项，资格等待原件。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
TAG = 'package-r100-20261107'
WORKFLOW = 'macos-disk.yml'


# 日期：2026-11-07；现有原生核心、210输入和固定标签必须匹配；持久账目先落盘，网络超时不得重复派发。
def main():
    root = Path.cwd()
    ledger_path = root / '.cache/r100-macos-disk-dispatch.json'
    assert not ledger_path.exists(), 'Inspect persisted ledger and live workflow before any retry'
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    core_path = root / 'docs/validation/2026-11-07/clipboard-r100-native-core/receipt.json'
    core = json.loads(core_path.read_text('utf-8'))
    assert core['sourceCommit'] == COMMIT and core['passed'] and len(core['cores']) == 4
    assert core['coreTargetsEach'] == 23 and core['originalQtReportsVerified'] == 88
    frozen = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))
    assert len(frozen['buildInputs']) == 210
    for row in frozen['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']], cwd=checkout)
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert raw == (root / row['path']).read_bytes()
    workflow = subprocess.check_output(['git', 'show', COMMIT + ':.github/workflows/' + WORKFLOW], cwd=checkout)
    assert workflow == (root / '.github/workflows' / WORKFLOW).read_bytes()
    assert b'hdiutil create -size 256m -fs APFS' in workflow
    assert b'tests/disk_integration.py' in workflow and b'tests/parallel_disk_integration.py' in workflow
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    assert request(base + '/git/ref/tags/' + TAG)['object']['sha'] == COMMIT
    prior = request(base + '/actions/workflows/' + WORKFLOW + '/runs?per_page=100&head_sha=' + COMMIT)['workflow_runs']
    assert not any(run['head_sha'] == COMMIT for run in prior), 'Exact-source disk workflow already exists'
    ledger = {'date': '2026-11-07', 'observedUtc': datetime.now(timezone.utc).isoformat(),
              'sourceCommit': COMMIT, 'sourceRef': TAG, 'workflow': WORKFLOW,
              'workflowSha256': hashlib.sha256(workflow).hexdigest(), 'buildInputsVerified': 210,
              'nativeCoreQualificationSha256': hashlib.sha256(core_path.read_bytes()).hexdigest(),
              'scope': 'Independent 256MiB APFS images; legacy plus TLS1/4/16 rename and overwrite; host system volume unchanged',
              'dispatchAttempted': True, 'responseReceived': False,
              'nativeDiskQualificationPending': True, 'releaseQualified': False, 'deliveryComplete': False}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    request(base + '/actions/workflows/' + WORKFLOW + '/dispatches', 'POST', {'ref': TAG})
    ledger['responseReceived'] = True
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    runs = request(base + '/actions/workflows/' + WORKFLOW + '/runs?per_page=100&head_sha=' + COMMIT)['workflow_runs']
    matches = [run for run in runs if run['head_sha'] == COMMIT]
    assert len(matches) <= 1
    if matches:
        ledger.update(runId=matches[0]['id'], runUrl=matches[0]['html_url'])
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps(ledger), flush=True)


if __name__ == '__main__':
    main()
