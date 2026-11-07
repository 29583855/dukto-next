"""日期：2026-11-08；汇总独立Ubuntu专项、真实环境差异及归属设计后公开，不改变产品输入。"""
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
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；独立验证完成后更新具体进度，原报告和失败记录均保留。
def prepare():
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    qualified = ROOT / '.cache/r121-glibc-qualified'
    verified = json.loads((qualified / 'verified-receipt.json').read_bytes())
    assert verified['passed'] and verified['stateInventory']['rowsPassed'] == 15
    folder = REPO / (BASE + 'state-inventory-r121-followup')
    assert folder.exists() and not (folder / 'receipt.json').exists()
    for path in qualified.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.log', '.xml', '.txt', '.sha256']:
            destination = folder / 'glibc-qualified' / path.relative_to(qualified)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    for name in ['validate-r121-glibc-qualified.py', 'verify-r121-glibc-final-evidence.py', 'r121-delivery-source-audit.json']:
        shutil.copyfile(ROOT / '.cache' / name, folder / name)
    shutil.copyfile(Path(__file__), folder / 'publication-driver.py')
    observation = json.loads((folder / 'r121-followup-long-observation.json').read_bytes())
    assert observation['ubuntu']['allFrozenInputsUnchanged']
    assert not observation['ubuntu']['allRuntimeDependenciesUnchanged']
    terminal = json.loads((REPO / (BASE + 'state-inventory-r121-native-terminal/receipt.json')).read_bytes())
    count = sum(row['qualified'] for row in terminal['records'])
    note = ('- [x] 独立Ubuntu新目录干净构建CLI与状态专项真实退出0；15条全通过、零跳过，'
            '415份实际源码/268份冻结资格输入、C++14编译参数及程序前后摘要均核验。'
            '首次缺Qt私有头文件配置失败继续保留；这不是该环境全部30核心或GUI验收。'
            '[严格回执](docs/validation/2026-11-08/state-inventory-r121-followup/glibc-qualified/verified-receipt.json)。\n'
            '- [x] 231份维护源码无TODO/占位/简化标记，C++14与格式检查通过；产品输入保持CI源30169754。\n')
    for name in ['开发计划与进度.md', 'docs/执行进度.md']:
        relative_note = note.replace('](docs/', '](') if name.startswith('docs/') else note
        update(name, lambda text, addition=relative_note: text.replace(
            '## 全状态入口核对与冻结环境差异（2026-11-08）\n\n',
            '## 全状态入口核对与冻结环境差异（2026-11-08）\n\n' + addition, 1))
    for name in ['README.md', '开发计划与进度.md', 'docs/macOS独立预览包.md']:
        update(name, lambda text: re.sub(r'完整协议终态已验[0-4]/4', '完整协议终态已验' + str(count) + '/4',
               text.replace('独立Ubuntu干净构建仍在执行。', '独立Ubuntu干净构建及15条状态专项已验。', 1), count=1))
    for name in ['开发计划与进度.md', 'docs/执行进度.md']:
        update(name, lambda text: re.sub(r'R121完整协议按独立终态已验[0-4]/4',
                                         'R121完整协议按独立终态已验' + str(count) + '/4', text, count=1))
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'independentGlibcStateInventoryQualified': True,
             'actualSourceFileCount': 415, 'actualQualificationInputCount': 268, 'stateInventoryRows': 15,
             'allSourceInputsUnchangedAfterTest': True, 'binariesUnchangedAfterTest': True,
             'fullIndependentCoreQualified': False, 'frozenUbuntuLongStillRunningAtObservation': True,
             'frozenUbuntuRuntimeDependencyDriftDetected': True, 'stateOwnershipEntryAuditCompleted': True,
             'runtimeOwnershipRegistryImplemented': False, 'completeNativeProtocolJobsVerified': count,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    (folder / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    index_path = REPO / 'docs/ci-verification-20261108-r121.json'
    index = json.loads(index_path.read_bytes())
    index.update(observedUtc=value['observedUtc'], independentGlibcQualified=True,
                 independentGlibcQualificationScope=verified['qualificationScope'],
                 frozenUbuntuRuntimeDependencyDriftDetected=True, stateOwnershipEntryAuditCompleted=True,
                 runtimeOwnershipRegistryImplemented=False, nativeRun=terminal['run'],
                 nativeTerminalJobsVerified=count, fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'],
                 nativeQualificationPending=count != 4, deliveryComplete=False, releaseQualified=False)
    names = {row['path'] for row in index['receipts']} | {folder.relative_to(REPO).as_posix() + '/receipt.json',
            folder.relative_to(REPO).as_posix() + '/glibc-qualified/verified-receipt.json'}
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((REPO / name).read_bytes()).hexdigest()} for name in sorted(names)]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(index_path, ROOT / index_path.relative_to(REPO))
    evidence = [folder.relative_to(REPO).as_posix(), BASE + 'state-inventory-r121-native-terminal']
    for name in evidence:
        for path in (REPO / name).rglob('*'):
            if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.sha256', '.py', '.png']:
                destination = ROOT / path.relative_to(REPO)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    return evidence, value


# 日期：2026-11-08；限定范围逐字节暂存和非强制推送，核对远端main及全部新增原件。
def main():
    target = ROOT / '.cache/r121-followup-publication.json'
    assert not target.exists()
    helper = runpy.run_path(str(ROOT / '.cache/publish-r120-native-delivery.py'))
    git, tree, blob = helper['git'], helper['tree'], helper['blob']
    assert git('rev-parse', 'HEAD').decode().strip() == '35cf1862b2ffd372cbf053c3acb1e72891a684fb'
    assert not git('diff', '--cached', '--name-only')
    evidence, value = prepare()
    explicit = {'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/macOS独立预览包.md',
                'docs/状态存储归属清单.md', 'docs/跨进程磁盘预算设计.md', 'docs/磁盘总配额实施清单.md',
                'docs/ci-verification-20261108-r121.json'}
    index = json.loads((REPO / 'docs/ci-verification-20261108-r121.json').read_bytes())
    current_tree = tree(index['ciSourceCommit'])
    for row in index['ciQualificationInputs']:
        raw = (ROOT / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256'] and blob(raw) == current_tree[row['path']], row['path']
    for row in index['receipts']:
        assert hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest() == row['sha256'], row['path']
    for name in evidence:
        for path in (REPO / name).rglob('*'):
            if path.is_file():
                if path.suffix not in ['.json', '.xml', '.log', '.txt', '.sha256', '.py', '.png']:
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
    git('commit', '-qm', 'Verify isolated Ubuntu state inventory and document complete storage entry points [skip ci]')
    commit = git('rev-parse', 'HEAD').decode().strip()
    environment = os.environ.copy()
    environment['GIT_TERMINAL_PROMPT'] = '0'
    result = subprocess.run(['git', '-c', 'http.proxy=http://127.0.0.1:10808', '-c', 'http.lowSpeedLimit=1000',
                             '-c', 'http.lowSpeedTime=30', 'push', 'origin', 'main'], cwd=REPO, env=environment,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr
    assert git('-c', 'http.proxy=http://127.0.0.1:10808', 'ls-remote', 'origin', 'refs/heads/main').decode().split()[0] == commit
    committed = tree(commit)
    for name in paths:
        assert blob((REPO / name).read_bytes()) == committed[name], name
    assert not git('status', '--porcelain')
    value.update(commit=commit, remoteMainVerified=True, publishedFileCount=len(paths),
                 changedFileCount=len(staged), pushWasNonForced=True)
    target.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
