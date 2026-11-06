"""日期：2026-11-07；四平台核心已验后并行构建固定R100部署包，完整协议资格仍单独等待终态。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'


# 日期：2026-11-07；核心、源码、现有运行及单次派发账目分别核对；发布包仍须独立迁移原件和完整发布验收。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('workflow', choices=('macos-package.yml', 'linux-package.yml'))
    args = parser.parse_args()
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    evidence = root / 'docs/validation/2026-11-07/clipboard-r100-native-core/receipt.json'
    core = json.loads(evidence.read_text('utf-8'))
    assert core['passed'] and core['sourceCommit'] == COMMIT and len(core['cores']) == 4
    assert core['coreTargetsEach'] == 23 and core['originalQtReportsVerified'] == 88
    assert core['explicitDarwinExpectedFailureCount'] == 2
    assert len(core['clipboardAndTextChecks']) == 4
    assert all('clipboardAvailabilityDoesNotReadOnProgress' in row['guiMethodsVerified']
               and row['outgoingTextEncodingRowsVerified'] == 8 for row in core['clipboardAndTextChecks'])
    compiled = json.loads((root / 'docs/validation/2026-11-07/clipboard-r100-macos-compiled/receipt.json').read_text('utf-8'))
    assert compiled['sourceCommit'] == COMMIT and compiled['bothArchitecturesCompiledAndVerified']
    ledger_path = root / ('.cache/r100-' + args.workflow.removesuffix('.yml') + '-dispatch.json')
    assert not ledger_path.exists(), 'Inspect persisted ledger and exact-source runs before any retry'
    frozen = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))
    assert len(frozen['buildInputs']) == 210
    for row in frozen['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']], cwd=checkout)
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert raw == (root / row['path']).read_bytes()
    workflow = subprocess.check_output(['git', 'show', COMMIT + ':.github/workflows/' + args.workflow], cwd=checkout)
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    prior = request(base + '/actions/workflows/' + args.workflow + '/runs?per_page=100&head_sha=' + COMMIT)['workflow_runs']
    assert not any(row['head_sha'] == COMMIT for row in prior), 'An exact-source package run already exists'
    tag = 'package-r100-20261107'
    refs = request(base + '/git/matching-refs/tags/' + tag)
    assert not refs or len(refs) == 1 and refs[0]['ref'] == 'refs/tags/' + tag and refs[0]['object']['sha'] == COMMIT
    if not refs:
        created = request(base + '/git/refs', 'POST', {'ref': 'refs/tags/' + tag, 'sha': COMMIT})
        assert created['object']['sha'] == COMMIT
    assert request(base + '/git/ref/tags/' + tag)['object']['sha'] == COMMIT
    ledger = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
              'sourceRef': tag, 'workflow': args.workflow, 'buildInputsVerified': 210,
              'workflowSha256': hashlib.sha256(workflow).hexdigest(),
              'nativeCoreQualificationSha256': hashlib.sha256(evidence.read_bytes()).hexdigest(),
              'qualificationGate': 'four native cores and clipboard QML verified; independent package migration follows',
              'fullNativeProtocolRegressionQualified': False,
              'dispatchAttempted': True, 'responseReceived': False,
              'releaseQualified': False, 'deliveryComplete': False}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    request(base + '/actions/workflows/' + args.workflow + '/dispatches', 'POST', {'ref': tag})
    ledger['responseReceived'] = True
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    runs = request(base + '/actions/workflows/' + args.workflow + '/runs?per_page=100&head_sha=' + COMMIT)['workflow_runs']
    exact = [row for row in runs if row['head_sha'] == COMMIT]
    assert len(exact) <= 1
    if exact:
        ledger.update(runId=exact[0]['id'], runUrl=exact[0]['html_url'])
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps(ledger), flush=True)


if __name__ == '__main__':
    main()
