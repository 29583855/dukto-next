"""日期：2026-11-07；R100四平台原件通过后按固定提交单次派发Mac或Linux部署包。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；包工作流单独持久记录，响应不确定时必须查询既有运行，不能再次盲目派发。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('workflow', choices=('macos-package.yml', 'linux-package.yml'))
    args = parser.parse_args()
    root = Path.cwd()
    commit = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
    qualification = root / 'docs/validation/2026-11-07/clipboard-r100-native-terminal/receipt.json'
    value = json.loads(qualification.read_text('utf-8'))
    assert value['sourceCommit'] == commit and value['allOriginalCoreAndProtocolReportsVerified']
    assert value['run']['status'] == 'completed' and value['run']['conclusion'] == 'success'
    assert value['protocolReports'] == 188 and value['explicitDarwinExpectedFailureCount'] == 2
    assert len(value['textSendChecks']) == 4 and all(row['encodingRows'] == 8 and row['draftRecovery'] for row in value['textSendChecks'])
    assert all(row['clipboardAvailabilityThroughProductionQml'] for row in value['textSendChecks'])
    ledger_path = root / ('.cache/r100-' + args.workflow.removesuffix('.yml') + '-dispatch.json')
    assert not ledger_path.exists(), 'Inspect exact-source workflow runs and prior ledger before any retry'
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    frozen = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))
    assert len(frozen['buildInputs']) == 210
    for row in frozen['buildInputs']:
        raw = subprocess.check_output(['git', 'show', commit + ':' + row['path']], cwd=checkout)
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert raw == (root / row['path']).read_bytes()
    raw = subprocess.check_output(['git', 'show', commit + ':.github/workflows/' + args.workflow], cwd=checkout)
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    prior = request(base + '/actions/workflows/' + args.workflow + '/runs?per_page=100&head_sha=' + commit)['workflow_runs']
    assert not any(row['head_sha'] == commit for row in prior), 'Exact-source package run already exists'
    source_ref = 'main'
    if request(base + '/git/ref/heads/main')['object']['sha'] != commit:
        source_ref = 'package-r100-20261107'
        refs = request(base + '/git/matching-refs/tags/' + source_ref)
        assert not refs or len(refs) == 1 and refs[0]['ref'] == 'refs/tags/' + source_ref and refs[0]['object']['sha'] == commit
        if not refs:
            result = request(base + '/git/refs', 'POST', {'ref': 'refs/tags/' + source_ref, 'sha': commit})
            assert result['object']['sha'] == commit
        assert request(base + '/git/ref/tags/' + source_ref)['object']['sha'] == commit
    ledger = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
              'sourceRef': source_ref, 'workflow': args.workflow, 'buildInputsVerified': 210,
              'workflowSha256': hashlib.sha256(raw).hexdigest(),
              'nativeQualificationSha256': hashlib.sha256(qualification.read_bytes()).hexdigest(),
              'dispatchAttempted': True, 'responseReceived': False}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    request(base + '/actions/workflows/' + args.workflow + '/dispatches', 'POST', {'ref': source_ref})
    ledger['responseReceived'] = True
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps(ledger), flush=True)


if __name__ == '__main__':
    main()
