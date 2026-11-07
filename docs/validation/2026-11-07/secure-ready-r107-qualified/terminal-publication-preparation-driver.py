"""日期：2026-11-07；发布双Mac新编译、Ubuntu真实失败及R105完整终态，生产输入保持。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess

SOURCE = 'e220461bdd0a409b10f483a3aaa321db927975c3'
LABEL = 'r107-terminal-evidence'


# 日期：2026-11-07；先核对终态原件和源码，再更新当前文档，不把编译/子集写成整体通过。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == SOURCE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    mac_path = base / 'secure-ready-r107-macos-compiled/receipt.json'
    mac = json.loads(mac_path.read_text('utf-8'))
    assert mac['sourceCommit'] == SOURCE and mac['bothArchitecturesCompiledAndVerified']
    assert len(mac['packages']) == 2 and all(not row['dependenciesDeployed'] for row in mac['packages'])
    ubuntu_path = base / 'secure-ready-r107-glibc/receipt.json'
    ubuntu = json.loads(ubuntu_path.read_text('utf-8'))
    assert ubuntu['sourceCommit'] == SOURCE and ubuntu['driverActuallyExited'] and ubuntu['driverExitCode'] == 1
    assert ubuntu['secureChannelCasesVerified'] == 31 and not ubuntu['fullOriginalTaskItemsPassed']
    terminal_path = base / 'task-items-r105-native-terminal/receipt.json'
    terminal = json.loads(terminal_path.read_text('utf-8'))
    assert terminal['run']['status'] == 'completed' and terminal['run']['conclusion'] == 'success'
    assert terminal['allOriginalCoreAndProtocolReportsVerified'] and terminal['verifiedProtocolReports'] == 192
    assert terminal['verifiedCancellationRows'] == 48 and terminal['explicitDarwinExpectedFailures'] == 2
    authors = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
               'docs/Ubuntu小文件性能诊断.md', 'docs/macOS独立预览包.md', 'docs/current-validation.json',
               'docs/ci-verification-20261107-r105.json', 'docs/ci-verification-20261107-r107.json']
    backup = root / '.cache/r107-terminal-docs-before'
    backup.mkdir(exist_ok=False)
    for name in authors:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    manifest_path = root / 'docs/ci-verification-20261107-r107.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    for row in manifest['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    manifest.update(sourceCommit=SOURCE, observedUtc=datetime.now(timezone.utc).isoformat(),
                    independentUbuntuR107Pending=False, independentUbuntuR107=proof(ubuntu_path),
                    independentUbuntuFullTaskItemsPassed=False, macosCompiledEvidence=proof(mac_path),
                    bothMacArchitecturesCompiledAndVerified=True, r105CompleteTerminal=proof(terminal_path))
    save(manifest_path, manifest)
    old_path = root / 'docs/ci-verification-20261107-r105.json'
    old = json.loads(old_path.read_text('utf-8'))
    old.update(nativeCIPending=False, fullNativeRegressionQualified=True, completeTerminalEvidence=proof(terminal_path),
               verifiedProtocolReports=192, verifiedCancellationRows=48, explicitDarwinExpectedFailures=2,
               independentUbuntuTimeoutStillRetained=True, releaseQualified=False, deliveryComplete=False)
    save(old_path, old)
    note = '''

## R107原生编译/独立Ubuntu终态与R105完整收验（2026-11-07）

- [x] R107精确e220461的Apple Silicon及Intel原生GUI/CLI编译成功；官方附件摘要、内部归档摘要、许可证、Mach-O架构及执行位逐项核对。仅为编译归档，含Qt5/OpenSSL的可运行预览包仍为R105。[双Mac编译回执](docs/validation/2026-11-07/secure-ready-r107-macos-compiled/receipt.json)。
- [x] 独立Ubuntu从R107精确源码编译并通过31 TLS边界及16通道双向专项；213输入、C++14、Qt5和执行前后二进制已核对。原完整task-items真实失败保留：16通道第二次上传在原90秒期限超时，已收到164个条目完成事件，不能当作整个批次成功。驱动实际退出1，原件收集退出0；未提高期限或盲目重试。[终态与边界](docs/validation/2026-11-07/secure-ready-r107-glibc/receipt.json)。
- [x] R105精确4652f4d的四runner已全部终态success；8份核心/最终附件摘要、四套各23核心、192份协议、48行原生/高DPI取消及4个选择器负例已严格收验。两条精确Darwin XFAIL继续披露；独立Ubuntu原失败与此云环境结果分别保留。[完整收验](docs/validation/2026-11-07/task-items-r105-native-terminal/receipt.json)。
- [ ] R107完整原生协议继续，端到端提速及独立Ubuntu原超时根因仍未证明。Windows/Ubuntu冻结86400秒长测最新92/67轮、约27648/22546秒，仍无终态；安全GC/全局磁盘预算、完整R6/GUI/选择器、物理LAN/3×3、各平台长期和正式分发继续。整体与正式发布仍为false。
'''

    # 日期：2026-11-07；当前摘要准确区分R107新源码、R105包和完整终态，历史检查点保留。
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R107双Mac编译/双Windows回归已验；独立Ubuntu完整task-items仍超时；R105四原生完整终态已验，整体交付继续。', text, count=1, flags=re.M)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R107精确e220461双Mac GUI/CLI编译及双Windows各23核心/31 TLS边界已验；独立Ubuntu31 TLS和16通道专项通过，但完整task-items的16通道重复上传仍在原90秒超时，根因及提速未定。R105四原生完整终态success、192协议/48取消已验，双Mac含依赖包仍为R105；Windows/Linux预览仍为R100。[本轮证据](docs/ci-verification-20261107-r107.json)。整体未完成。' + text[end:]
        text = text.replace('R105 ARM/Intel/GitHub Ubuntu已终态通过，Windows、R107新原生与长测继续收验', 'R105四原生完整终态通过；R107完整原生与冻结长测继续收验', 1)
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: re.sub(r'^公开仓库为.*$', '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R107双Mac GUI/CLI已原生编译，双Windows各23核心/31 TLS边界通过；独立Ubuntu31 TLS/16通道专项通过，完整小文件任务仍90秒超时，保留失败。R105四原生完整终态success、192协议/48取消已验；[双Mac含依赖预览](docs/macOS独立预览包.md)仍为R105。完整交付见[计划](开发计划与进度.md)和[本轮证据](docs/ci-verification-20261107-r107.json)。', text, count=1, flags=re.M))
    update(root / 'docs/Ubuntu小文件性能诊断.md', lambda text: text.rstrip() + '''

R107独立Ubuntu现已真实终止：31项TLS和16通道双向专项通过，完整task-items退出1，未提高90秒期限。失败在16通道第二次上传，90.197秒到期；最后有164条file-completed事件、窗口字节87760/101395，不能认定全部204条目提交。完整脚本运行303.446秒包含此前操作，不能把这个总值当作单次传输期限。新二进制和213输入均已固定核对，未重跑失败以获取通过。[完整日志](validation/2026-11-07/secure-ready-r107-glibc/results/task-items.log)、[收验回执](validation/2026-11-07/secure-ready-r107-glibc/receipt.json)。原超时根因仍未确定，端到端提速仍未证明。
''')
    table = '\n'.join('| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['sha256'] + '` |' for row in mac['packages'])
    update(root / 'docs/macOS独立预览包.md', lambda text: text.rstrip() + '''

## R107新源码编译归档

精确源码`e220461bdd0a409b10f483a3aaa321db927975c3`的两种架构已编译并核验GUI/CLI、Mach-O和摘要。以下归档未部署运行依赖；上方可运行含依赖预览仍为R105。R107完整协议及运行部署继续。

| 架构 | 编译归档 | 内部tar.gz SHA-256 |
| --- | --- | --- |
''' + table + '\n\n[编译回执](validation/2026-11-07/secure-ready-r107-macos-compiled/receipt.json)。\n')
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index['secureReadyR107'].update(manifest=proof(manifest_path), independentUbuntuPending=False,
                                   independentUbuntuEvidence=proof(ubuntu_path), independentUbuntuFullTaskItemsPassed=False,
                                   macosCompiledEvidence=proof(mac_path))
    index['taskItemsFixtureR105'].update(manifest=proof(old_path), nativeCIPending=False,
                                        completeTerminalEvidence=proof(terminal_path), fullNativeRegressionQualified=True)
    index.update(currentSourceCommit=SOURCE, currentGuiSourceCommit=SOURCE, currentGuiSourceCommitPending=False,
                 r105CompleteTerminal=proof(terminal_path), macOSCompilationR107=proof(mac_path),
                 observedUtc=manifest['observedUtc'], currentSourceStage='R107 dualMac compiled and Windows verified; independent Ubuntu task-items timed out; full new native pending',
                 releaseQualified=False, deliveryComplete=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == SOURCE
    state.update(secureReadyR107=manifest, r105CompleteTerminal=proof(terminal_path), goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    qualified = base / 'secure-ready-r107-qualified'
    shutil.copyfile(root / '.cache/r107-inflight-long-observation.json', qualified / 'inflight-long-observation.json')
    shutil.copyfile(root / '.cache/r107-native-run.json', qualified / 'native-inflight-observation.json')
    shutil.copyfile(__file__, qualified / 'terminal-publication-preparation-driver.py')
    names = set(authors + ['docs/validation/2026-11-06/github-api-push-r107-secure-ready.json',
                          (qualified / 'inflight-long-observation.json').relative_to(root).as_posix(),
                          (qualified / 'native-inflight-observation.json').relative_to(root).as_posix(),
                          (qualified / 'terminal-publication-preparation-driver.py').relative_to(root).as_posix()])
    for folder in ('secure-ready-r107-glibc', 'secure-ready-r107-macos-compiled', 'task-items-r105-native-terminal'):
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*') if path.is_file()
                     and path.suffix in ('.json', '.jsonl', '.xml', '.log', '.txt', '.sha256', '.py', '.png', '.stderr'))
    # 日期：2026-11-07；只复制与父提交不同的显式文件；发布集不包含原栈、凭据或编译二进制。
    changes = []
    for name in sorted(names):
        raw = (root / name).read_bytes()
        assert not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}', raw), name
        prior = subprocess.run(['git', 'show', 'HEAD:' + name], cwd=checkout, capture_output=True)
        if prior.returncode == 0 and prior.stdout == raw:
            continue
        changes.append(name)
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(changes, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in changes))
    template = (root / '.cache/stage-r106-evidence.py').read_bytes()
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes(template.replace(b'r106-evidence', LABEL.encode()))
    print(json.dumps({'explicitFiles': len(changes), 'applicationSourceCommit': SOURCE, 'all213BuildInputsUnchanged': True,
                      'r105CompleteProtocolReports': 192, 'independentUbuntuFullTaskItemsPassed': False, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
