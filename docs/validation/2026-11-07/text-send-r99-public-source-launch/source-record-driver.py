"""日期：2026-11-07；核对已公开R99提交与自动CI身份，记录本机计划，不追加触发文档专用CI。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；实际API及精确Git对象共同证明已上传；运行中只记录观察，不授予原生成功资格。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    commit = 'a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == commit
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    assert request(base + '/git/ref/heads/main')['object']['sha'] == commit
    ledger = json.loads((root / '.cache/r99-native-dispatch.json').read_text('utf-8'))
    assert ledger['sourceCommit'] == commit and ledger['reusedExistingRun'] and not ledger['dispatchAttempted']
    run = request(base + '/actions/runs/' + str(ledger['runId']))
    assert run['head_sha'] == commit and run['id'] == 42276738981
    output = root / 'docs/validation/2026-11-07/text-send-r99-public-source-launch'
    output.mkdir(exist_ok=False)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
             'remoteMainVerified': True, 'buildInputsVerified': 210,
             'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'automaticRunReused': True, 'duplicateDispatched': False,
             'nativeQualificationComplete': False, 'releaseQualified': False, 'deliveryComplete': False}
    receipt = output / 'observation.json'
    receipt.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/r99-native-dispatch.json', output / 'ci-dispatch-ledger.json')
    shutil.copyfile(root / '.cache/dispatch-r99-native.py', output / 'ci-dispatch-driver.py')
    shutil.copyfile(Path(__file__), output / 'source-record-driver.py')
    path = root / 'docs/ci-verification-20261107-r99.json'
    public = json.loads(path.read_text('utf-8'))
    listing = subprocess.check_output(['git', 'ls-tree', '-r', '-z', commit], cwd=checkout)
    blobs = {row.split(b'\t', 1)[1].decode('utf-8'): row.split(b'\t', 1)[0].split()[2].decode()
             for row in listing.split(b'\0') if row}
    for row in public['buildInputs']:
        raw = (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest() == blobs[row['path']]
    public.update(sourceCommit=commit, nativeCIRequested=True, nativeCIAutomaticRunReused=True,
                  nativeRun=value['run'], nativeCIPending=True, publicSourceEvidence=helper['proof'](receipt))
    helper['save'](path, public)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(productionCommit=commit, testCommit=commit, coreProductionCommit='88f33b2c83f2950307c362fb64c693f7e9e5929d',
                 currentGuiSourceCommitPending=False, textSendGuardR99=public,
                 observedUtc=value['observedUtc'], releaseQualified=False, deliveryComplete=False)
    helper['save'](index_path, index)
    note = ('\n\nR99公开启动补记（2026-11-07，本机新增观察）：精确提交`' + commit +
            '`已上传并核对全部210构建输入，自动四平台运行[42276738981](https://github.com/29583855/dukto-next/actions/runs/42276738981)已复用；未重复派发。原生终态及新GUI的Mac/Linux资格尚待收验。该启动观察将在下一批实质结果中一起公开，当前源码与初轮文档已公开于上述提交。\n')
    for name in ('开发计划与进度.md', 'docs/执行进度.md'):
        helper['update'](root / name, lambda text: text + note)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(currentRepositoryCommit=commit, r99TextSendGuard=public,
                 goalStatus='active', deliveryComplete=False, releaseQualified=False)
    helper['save'](state_path, state)
    print(json.dumps({'sourceCommit': commit, 'runId': run['id'], 'status': run['status'],
                      'localObservationAwaitingNextPublication': True}), flush=True)


if __name__ == '__main__':
    main()
