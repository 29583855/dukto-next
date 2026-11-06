"""日期：2026-11-07；用固定源码标签生成当前Linux部署包，保留旧包及独立派发账目。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；先逐字节核对输入和Mac新夹具原件，再只发一次Linux包运行。
def main():
    root = Path.cwd()
    commit = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    tag = 'ci-r98-20261107'
    ledger_path = root / '.cache/r98-linux-package-dispatch.json'
    assert not ledger_path.exists(), 'Inspect the existing ledger and run before any retry'
    qualification = root / 'docs/validation/2026-11-07/ci-guard-r98-native-regression-terminal/fixture-qualification.json'
    value = json.loads(qualification.read_text('utf-8'))
    assert value['sourceCommit'] == commit and value['newFixtureQualified']
    frozen = json.loads((root / 'docs/ci-verification-20261107-r98.json').read_text('utf-8'))
    assert len(frozen['buildInputs']) == 210
    for row in frozen['buildInputs']:
        raw = subprocess.check_output(['git', 'show', commit + ':' + row['path']],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert raw == (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    workflow = '.github/workflows/linux-package.yml'
    raw = subprocess.check_output(['git', 'show', commit + ':' + workflow],
                                  cwd=root / '.cache/github-29583855-dukto-next-r28')
    assert raw == (root / workflow).read_bytes()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    prior = request(base + '/actions/workflows/linux-package.yml/runs?per_page=100&head_sha=' + commit)['workflow_runs']
    assert not any(row['head_sha'] == commit for row in prior), 'An exact-source run already exists'
    refs = request(base + '/git/matching-refs/tags/' + tag)
    assert not refs or len(refs) == 1 and refs[0]['ref'] == 'refs/tags/' + tag and refs[0]['object']['sha'] == commit
    if not refs:
        result = request(base + '/git/refs', 'POST', {'ref': 'refs/tags/' + tag, 'sha': commit})
        assert result['object']['sha'] == commit
    assert request(base + '/git/ref/tags/' + tag)['object']['sha'] == commit
    ledger = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
              'sourceRef': tag, 'workflow': 'linux-package.yml', 'buildInputsVerified': 210,
              'workflowSha256': hashlib.sha256(raw).hexdigest(),
              'fixtureQualificationSha256': hashlib.sha256(qualification.read_bytes()).hexdigest(),
              'dispatchAttempted': True, 'responseReceived': False}
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    request(base + '/actions/workflows/linux-package.yml/dispatches', 'POST', {'ref': tag})
    ledger['responseReceived'] = True
    ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps(ledger), flush=True)


if __name__ == '__main__':
    main()
