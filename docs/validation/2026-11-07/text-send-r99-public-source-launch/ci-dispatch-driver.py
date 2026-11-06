"""日期：2026-11-07；精确核对R99公开源码后复用既有原生运行或仅派发一次完整四平台CI。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-07；公开父提交及210输入必须匹配Git对象，持久记录派发前事实，避免观察中断后重复启动。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    assert request(base + '/git/ref/heads/main')['object']['sha'] == commit
    value = json.loads((root / 'docs/ci-verification-20261107-r99.json').read_text('utf-8'))
    assert len(value['buildInputs']) == 210
    listing = subprocess.check_output(['git', 'ls-tree', '-r', '-z', commit], cwd=checkout)
    blobs = {}
    for item in listing.split(b'\0'):
        if item:
            header, name = item.split(b'\t', 1)
            blobs[name.decode('utf-8')] = header.split()[2].decode()
    for row in value['buildInputs']:
        raw = (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blobs[row['path']]
    ledger_path = root / '.cache/r99-native-dispatch.json'
    assert not ledger_path.exists(), 'Inspect existing dispatch ledger and actual run; never dispatch again blindly'
    runs = request(base + '/actions/workflows/build.yml/runs?per_page=100&head_sha=' + commit)['workflow_runs']
    exact = [row for row in runs if row['head_sha'] == commit]
    ledger = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
              'workflow': 'build.yml', 'buildInputsVerified': 210,
              'workflowSha256': hashlib.sha256((root / '.github/workflows/build.yml').read_bytes()).hexdigest(),
              'dispatchAttempted': False, 'responseReceived': False,
              'reusedExistingRun': bool(exact)}
    if exact:
        assert len(exact) == 1, 'Multiple exact-source runs require inspection'
        ledger.update(runId=exact[0]['id'], sourceRef=exact[0]['head_branch'], responseReceived=True,
                      runUrl=exact[0]['html_url'])
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    else:
        tag = 'ci-r99-20261107'
        refs = request(base + '/git/matching-refs/tags/' + tag)
        assert not refs or len(refs) == 1 and refs[0]['ref'] == 'refs/tags/' + tag and refs[0]['object']['sha'] == commit
        if not refs:
            result = request(base + '/git/refs', 'POST', {'ref': 'refs/tags/' + tag, 'sha': commit})
            assert result['object']['sha'] == commit
        assert request(base + '/git/ref/tags/' + tag)['object']['sha'] == commit
        ledger.update(sourceRef=tag, dispatchAttempted=True)
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
        request(base + '/actions/workflows/build.yml/dispatches', 'POST', {'ref': tag})
        ledger['responseReceived'] = True
        ledger_path.write_text(json.dumps(ledger, indent=2) + '\n', 'utf-8')
    print(json.dumps(ledger), flush=True)


if __name__ == '__main__':
    main()
