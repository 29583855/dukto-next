"""日期：2026-11-07；隔离诊断分支仅补测试错误报告，R116主线产品和原失败保持不变。"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
DIAG = ROOT / '.cache/github-upload-scan-r116-diagnostic'
SOURCE = '0a60da9120b6be49d1768fa500d042ff394ac9f7'
BRANCH = 'diagnostic-upload-scan-r116'
TEST = 'tests/upload_scan_cleanup_tests.cpp'
WORKFLOW = '.github/workflows/upload-scan-windows-diagnostic.yml'


# 日期：2026-11-07；诊断只在全新缓存克隆中提交，不切换发布副本分支或混入未提交文档。
def git(*args, cwd=DIAG):
    return subprocess.check_output(['git', *args], cwd=cwd)


# 日期：2026-11-07；先保留诊断输入，再恢复主目录精确R116测试；运行身份及产品不变证明分别登记。
def main():
    assert not DIAG.exists()
    candidate = (ROOT / TEST).read_bytes()
    workflow = (ROOT / WORKFLOW).read_bytes()
    assert b'scan diagnostic code=' in candidate
    subprocess.run(['git', 'clone', '--shared', '--quiet', str(REPO), str(DIAG)], check=True, capture_output=True, timeout=60)
    assert git('rev-parse', 'HEAD').decode().strip() == SOURCE
    git('remote', 'set-url', 'origin', 'https://github.com/29583855/dukto-next.git')
    git('switch', '-c', BRANCH)
    (DIAG / TEST).write_bytes(candidate)
    (DIAG / WORKFLOW).write_bytes(workflow)
    original = git('show', SOURCE + ':' + TEST)
    assert (ROOT / TEST).read_bytes() == candidate
    (ROOT / TEST).write_bytes(original)
    assert (ROOT / WORKFLOW).read_bytes() == workflow
    (ROOT / WORKFLOW).unlink()
    git('-c', 'core.autocrlf=false', 'add', '--', TEST, WORKFLOW)
    git('diff', '--cached', '--check')
    git('commit', '-qm', 'Expose original Windows scan cleanup error and preserve two diagnostic rounds [skip ci]')
    commit = git('rev-parse', 'HEAD').decode().strip()
    changed = git('diff', '--name-only', SOURCE, commit).decode().splitlines()
    assert set(changed) == {TEST, WORKFLOW}
    environment = os.environ.copy()
    environment['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run(['git', '-c', 'http.proxy=http://127.0.0.1:10808', '-c', 'http.lowSpeedLimit=1000',
                             '-c', 'http.lowSpeedTime=30', 'push', '-u', 'origin', BRANCH], cwd=DIAG,
                            env=environment, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    remote = git('-c', 'http.proxy=http://127.0.0.1:10808', 'ls-remote', 'origin', 'refs/heads/' + BRANCH).decode().split()[0]
    assert remote == commit
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    request('/repos/29583855/dukto-next/actions/workflows/upload-scan-windows-diagnostic.yml/dispatches',
            method='POST', payload={'ref': BRANCH})
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
             'productSourceCommit': SOURCE, 'branch': BRANCH, 'changedFiles': changed,
             'allProductInputsUnchanged': True, 'testSourceSha256': hashlib.sha256(candidate).hexdigest(),
             'localCompleteScanTestsPassed': True, 'mainSourceNotChanged': True, 'dispatched': True,
             'releaseQualified': False, 'deliveryComplete': False}
    output = ROOT / '.cache/r116-windows-diagnostic-dispatch.json'
    assert not output.exists()
    output.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
