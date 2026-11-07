"""日期：2026-11-07；GitHub新工作流不在默认分支不能手动派发，改由隔离分支的明确push触发。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-upload-scan-r116-diagnostic'
SOURCE = '0a60da9120b6be49d1768fa500d042ff394ac9f7'
BRANCH = 'diagnostic-upload-scan-r116'


# 日期：2026-11-07；原诊断提交/404记录保留，分支只增诊断触发并限制该分支的常规矩阵。
def main():
    workflow = REPO / '.github/workflows/upload-scan-windows-diagnostic.yml'
    raw = workflow.read_bytes()
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    if b'  push:' not in raw:
        workflow.write_bytes(raw.replace(b'on:' + newline, b'on:' + newline + b'  push:' + newline +
                             b'    branches: [diagnostic-upload-scan-r116]' + newline, 1))
    else:
        assert b'    branches: [diagnostic-upload-scan-r116]' in raw
    build = REPO / '.github/workflows/build.yml'
    raw = build.read_bytes()
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    assert raw.count(b'  push:' + newline) == 1
    if b'    branches: [main]' not in raw:
        build.write_bytes(raw.replace(b'  push:' + newline, b'  push:' + newline + b'    branches: [main]' + newline, 1))
    def git(*args):
        # 日期：2026-11-07；只读对象和明确路径的分支操作不触碰主线未提交文档。
        return subprocess.check_output(['git', *args], cwd=REPO)
    # 日期：2026-11-07；克隆检出CRLF的既有工作流在Git中仍保存原LF，不把检出换行混入补丁。
    git('-c', 'core.autocrlf=true', 'add', '--renormalize', '--', '.github/workflows/build.yml')
    git('-c', 'core.autocrlf=false', 'add', '--', '.github/workflows/upload-scan-windows-diagnostic.yml')
    git('diff', '--cached', '--check')
    git('commit', '-qm', 'Run Windows scan diagnostics on its isolated branch')
    commit = git('rev-parse', 'HEAD').decode().strip()
    changed = git('diff', '--name-only', SOURCE, commit).decode().splitlines()
    assert set(changed) == {'tests/upload_scan_cleanup_tests.cpp', '.github/workflows/build.yml', '.github/workflows/upload-scan-windows-diagnostic.yml'}
    assert not git('diff', '--name-only', SOURCE, commit, '--', 'src', 'ui', 'resources', 'CMakeLists.txt')
    push = subprocess.run(['git', '-c', 'http.proxy=http://127.0.0.1:10808', '-c', 'http.lowSpeedLimit=1000',
                           '-c', 'http.lowSpeedTime=30', 'push', 'origin', BRANCH], cwd=REPO,
                          capture_output=True, text=True, timeout=120)
    assert push.returncode == 0, push.stderr
    assert git('-c', 'http.proxy=http://127.0.0.1:10808', 'ls-remote', 'origin', 'refs/heads/' + BRANCH).decode().split()[0] == commit
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
             'productSourceCommit': SOURCE, 'branch': BRANCH, 'allProductInputsUnchanged': True,
             'changedFiles': changed, 'trigger': 'isolated branch push', 'mainSourceNotChanged': True,
             'initialManualDispatch404Preserved': True, 'firstDiagnosticCommit': 'e6a98377d3556771e9ffae86b15f37faa909c62a',
             'testSourceSha256': hashlib.sha256((REPO / 'tests/upload_scan_cleanup_tests.cpp').read_bytes()).hexdigest(),
             'releaseQualified': False, 'deliveryComplete': False}
    (ROOT / '.cache/r116-windows-diagnostic-dispatch.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
