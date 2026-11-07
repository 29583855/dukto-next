"""日期：2026-11-08；公开已核验R122双Mac预览及四原生账本，精确原件/输入不变，非强制推送。"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-08；收集器停止后限定范围暂存原字节，推送后核对远端提交及全部blob。
def main():
    target = ROOT / '.cache/r122-delivery-publication.json'
    assert not target.exists()
    helper = runpy.run_path(str(ROOT / '.cache/publish-r120-native-delivery.py'))
    git, tree, blob = helper['git'], helper['tree'], helper['blob']
    prepared = json.loads((ROOT / '.cache/r122-delivery-prepared.json').read_bytes())
    source = prepared['sourceCommit']
    assert git('rev-parse', 'HEAD').decode().strip() == source
    assert not git('diff', '--cached', '--name-only')
    execution = 'docs/validation/2026-11-08/state-budget-r122-delivery'
    for base in [ROOT, REPO]:
        shutil.copyfile(Path(__file__), base / execution / 'publication-driver.py')
    explicit = {'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/macOS独立预览包.md',
                'docs/持久预算账本底层.md', 'docs/ci-verification-20261108-r121.json', 'docs/ci-verification-20261108-r122.json'}
    index = json.loads((REPO / 'docs/ci-verification-20261108-r122.json').read_bytes())
    source_tree = tree(source)
    for row in index['qualificationInputs']:
        raw = (ROOT / row['path']).read_bytes()
        assert raw == (REPO / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256'] and blob(raw) == source_tree[row['path']], row['path']
    for name in ['docs/ci-verification-20261108-r121.json', 'docs/ci-verification-20261108-r122.json']:
        for row in json.loads((REPO / name).read_bytes())['receipts']:
            assert hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    for folder in prepared['evidenceFolders']:
        for path in (REPO / folder).rglob('*'):
            if not path.is_file():
                continue
            if path.suffix not in ['.json', '.xml', '.txt', '.log', '.sha256', '.png', '.py']:
                assert re.fullmatch(r'LastTest\.log\.tmp[0-9a-f]+', path.name), path
                assert git('check-ignore', '--', path.relative_to(REPO).as_posix())
                continue
            explicit.add(path.relative_to(REPO).as_posix())
    dirty = {name.decode('utf-8') for name in git('diff', '--name-only', '-z').split(b'\0') if name}
    untracked = {name.decode('utf-8') for name in git('ls-files', '--others', '--exclude-standard', '-z').split(b'\0') if name}
    assert dirty <= explicit, dirty - explicit
    assert untracked <= explicit, untracked - explicit
    patterns = [re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'), re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),
                re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'), re.compile(rb'Bearer\s+[A-Za-z0-9_.-]{20,}')]
    paths = sorted(explicit)
    for name in paths:
        raw = (REPO / name).read_bytes()
        assert raw == (ROOT / name).read_bytes(), name
        assert len(raw) <= 32 * 1024**2 and not any(pattern.search(raw) for pattern in patterns), name
    for offset in range(0, len(paths), 40):
        git('-c', 'core.autocrlf=false', 'add', '-f', '--', *paths[offset:offset + 40])
    staged = {name.decode('utf-8') for name in git('diff', '--cached', '--name-only', '-z').split(b'\0') if name}
    assert staged and staged <= explicit
    git('diff', '--cached', '--check', '--', '.', ':(exclude)docs/validation')
    git('commit', '-qm', 'Verify R122 durable budget on four platforms and publish native macOS previews [skip ci]')
    commit = git('rev-parse', 'HEAD').decode().strip()
    environment = os.environ.copy()
    environment['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run(['git', '-c', 'http.proxy=http://127.0.0.1:10808', '-c', 'http.lowSpeedLimit=1000',
                             '-c', 'http.lowSpeedTime=30', 'push', 'origin', 'main'], cwd=REPO, env=environment,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert git('-c', 'http.proxy=http://127.0.0.1:10808', 'ls-remote', 'origin', 'refs/heads/main').decode().split()[0] == commit
    committed = tree(commit)
    for name in set(paths) | {row['path'] for row in index['qualificationInputs']}:
        assert blob((REPO / name).read_bytes()) == committed[name], name
    assert not git('status', '--porcelain')
    prepared.update(publishedCommit=commit, remoteMainVerified=True, pushWasNonForced=True,
                    publishedFileCount=len(paths), changedFileCount=len(staged), allEvidenceBytesPreserved=True)
    target.write_text(json.dumps(prepared, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: prepared[key] for key in ['sourceCommit', 'publishedCommit', 'remoteMainVerified',
                     'publishedFileCount', 'changedFileCount', 'allFourNativeBudgetFoundationQualified',
                     'bothMacosPackagesQualified', 'completeNativeCoreJobsVerified', 'independentGlibcQualified']}), flush=True)


if __name__ == '__main__':
    main()
