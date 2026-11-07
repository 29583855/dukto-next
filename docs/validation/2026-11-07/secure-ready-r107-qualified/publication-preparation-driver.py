"""日期：2026-11-07；双Windows通过后更新计划，保留独立Ubuntu诊断及原失败范围。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess

PARENT = '944271024992ed00bc5e1f76e071c0a04aa9b0d4'
LABEL = 'r107-secure-ready'


# 日期：2026-11-07；先核验通过原件，再以保持编码/换行的方式修改当前摘要及显式发布集。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    receipt_path = base / 'secure-ready-r107-qualified/receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['passed'] and len(receipt['windows']) == 2 and not receipt['throughputImprovementProven']
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    intel_path = base / 'task-items-r105-native-job-terminals/macos-15-intel/receipt.json'
    intel = json.loads(intel_path.read_text('utf-8'))
    assert intel['sourceCommit'] == '4652f4dce23b014e18f2db56c6a75e81e76deafa' and intel['thisNativeJobVerified']
    assert intel['job']['conclusion'] == 'success' and intel['verifiedProtocol']['cases'] == 47
    profile_path = base / 'task-items-r107-glibc-profile/sample-verification.json'
    profile = json.loads(profile_path.read_text('utf-8'))
    assert profile['actualProcessExitCode'] == profile['profilingProcessExitCode'] == 0
    assert profile['filesExternallyVerified'] == 201 and profile['originalTaskItemsNotRerunOrQualified']
    assert profile['rawStackDataKeptPrivateOnVM'] and not profile['originalTimeoutCauseEstablished']
    for item in profile['evidence']:
        assert hashlib.sha256((profile_path.parent / item['path']).read_bytes()).hexdigest() == item['sha256']
    authors = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
               'docs/Ubuntu小文件性能诊断.md', 'docs/current-validation.json']
    backup = root / '.cache/secure-ready-r107-docs-before'
    backup.mkdir(exist_ok=False)
    for name in authors:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    manifest = {'planVersion': 'v0.107', 'observedUtc': datetime.now(timezone.utc).isoformat(),
                'basedOnPublishedCommit': PARENT, 'buildInputs': receipt['buildInputs'],
                'changedBuildInputs': receipt['changedBuildInputs'], 'windowsEvidence': proof(receipt_path),
                'nativeCIPending': True, 'independentUbuntuR107Pending': True,
                'r105IntelTerminal': proof(intel_path), 'r107UnchangedBinaryCpuProfile': proof(profile_path),
                'throughputImprovementProven': False, 'originalUbuntuTimeoutCauseEstablished': False,
                'releaseQualified': False, 'deliveryComplete': False}
    manifest_path = root / 'docs/ci-verification-20261107-r107.json'
    assert not manifest_path.exists()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    note = '''

## R107安全通道就绪路径与Intel终态（2026-11-07）

- [x] 安全通道在正文/写队列已就绪时直接完成检查，只有实际等待时建立Qt事件循环和信号连接；取消、绝对期限、同请求远端失败及断开尾帧的原顺序保持。仅改一处生产函数，未改变授权巡检或传输持久化规则。
- [x] 双Windows工具链各23核心/22 XML、31安全通道边界、4/16通道双向逐项查询及16通道双向传输通过。新增512帧连续缓冲、断开尾帧和缓冲中取消均通过，构建输入与执行程序保持身份。[本轮回执](docs/validation/2026-11-07/secure-ready-r107-qualified/receipt.json)。
- [x] R105 Intel原生完整作业终态success及47协议原件已验；连同Apple Silicon/GitHub Ubuntu共141份协议报告，Windows仍收验，整个运行尚未授予通过。
- [x] 独立Ubuntu原二进制49Hz用户CPU采样及聚合符号已保存；一次201文件16通道下载69.90秒、201外部摘要一致。原栈数据留在私有VM，未上传；该单次诊断不是完整task-items，原两次超时及R106失败继续保留。[诊断边界](docs/Ubuntu小文件性能诊断.md)。
- [x] 207份维护源码重新扫描，无TODO/FIXME/占位/简化实现标记；新增/修改函数保留中文日期注释，C++14及原UTF-8无BOM/LF保持。这不代替完整功能验收。
- [ ] R107新Mac/Linux原生及独立Ubuntu新源码测试继续收验；尚未证明端到端提速或原超时根因。当前双Mac含依赖包仍为R105，Windows/Linux仍为R100。安全GC/全局磁盘预算、完整R6/GUI、物理LAN/3×3、各平台24h、最低干净系统和正式分发继续，整体与正式发布仍为false。
'''

    # 日期：2026-11-07；只标记证据支持的子项，当前包版本与新应用源码阶段分别记录。
    def plan(text):
        assert '文档版本：v0.106' in text
        text = text.replace('文档版本：v0.106', '文档版本：v0.107', 1)
        text = text.replace('v0.106 / 原生作业终态与独立Ubuntu性能诊断', 'v0.107 / 安全通道就绪路径与Intel终态', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R107安全通道就绪路径通过双Windows；R105双Mac包及三组原生作业已验，新原生/独立Ubuntu/完整交付继续。', text, count=1, flags=re.M)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R107已减少安全通道就绪时的等待对象开销，双Windows各23核心和31 TLS边界通过，端到端提速尚未证明，新原生结果继续。R105双Mac含依赖包已验，ARM/Intel/GitHub Ubuntu各47协议作业终态通过；Windows继续收验。独立Ubuntu原90秒超时保留，另一次原二进制CPU采样69.90秒完成单次201文件下载，不授予完整测试资格。[本轮证据](docs/ci-verification-20261107-r107.json)。整体未完成。' + text[end:]
        text = text.replace('R105 Apple Silicon/GitHub Ubuntu已终态通过，Intel/Windows与长测继续收验', 'R105 ARM/Intel/GitHub Ubuntu已终态通过，Windows、R107新原生与长测继续收验', 1)
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: re.sub(r'^公开仓库为.*$', '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。[macOS Apple Silicon/Intel GUI与独立CLI](docs/macOS独立预览包.md)的R105含Qt5/OpenSSL开发包已编译并通过迁移业务。R107安全通道就绪路径通过双Windows各23核心和31 TLS边界，新Mac/Linux验证继续；尚未证明提速或独立Ubuntu原超时根因。完整交付见[计划](开发计划与进度.md)和[本轮证据](docs/ci-verification-20261107-r107.json)。', text, count=1, flags=re.M))
    update(root / 'docs/Ubuntu小文件性能诊断.md', lambda text: text.rstrip() + '''

## R107补充采样与源码验证

原R104二进制未变。49Hz用户CPU采样期间，一次16通道下载201文件在69.897秒完成，退出0且所有外部摘要一致；没有执行完整task-items的重复改名和其余用例，不能替换原失败。732样本、零丢失；QtCore自耗约34.43%、libc18.58%、SQLite16.67%，事件调度器累计约21.58%。聚合栈有缺失、采样有开销，不能推定唯一根因；原始栈数据留在VM私有目录，公开内容只有聚合符号和有界进程指标。[样本核验](validation/2026-11-07/task-items-r107-glibc-profile/sample-verification.json)。

源码检查发现安全通道每次就绪读写仍先创建等待循环并连接信号。R107先将相同检查放到等待对象构造之前，双Windows验证原TLS边界及连续缓冲/取消/尾帧，未放宽90秒期限或250ms授权巡检。新源码独立Ubuntu在隔离目录重新编译及执行原完整task-items，结果继续收验；目前不宣称端到端提速或超时修复。[源码与验证](ci-verification-20261107-r107.json)。
''')
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.107', observedUtc=manifest['observedUtc'], currentGuiSourceCommitPending=True,
                 publicVerificationReceipt=manifest_path.relative_to(root).as_posix(),
                 secureReadyR107={'windowsEvidence': proof(receipt_path), 'nativeCIPending': True,
                                 'independentUbuntuPending': True, 'throughputImprovementProven': False},
                 r105IntelNativeTerminal=proof(intel_path),
                 currentSourceStage='R107 secure-channel ready path; Windows verified; new native and independent Ubuntu pending',
                 releaseQualified=False, deliveryComplete=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(planVersion='v0.107', secureReadyR107=manifest, goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    shutil.copyfile(__file__, receipt_path.parent / 'publication-preparation-driver.py')
    names = set(authors + ['docs/ci-verification-20261107-r107.json',
                          'docs/validation/2026-11-06/github-api-push-r106-evidence.json'])
    names.update(receipt['changedBuildInputs'])
    for folder in ('secure-ready-r107-windows', 'secure-ready-r107-qualified',
                   'task-items-r105-native-job-terminals/macos-15-intel', 'task-items-r107-glibc-profile'):
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*')
                     if path.is_file() and path.suffix in ('.json', '.jsonl', '.xml', '.log', '.txt', '.sha256', '.py', '.stderr'))
    names = sorted(names)
    # 日期：2026-11-07；仅扫描显式发布文件，遇真实密钥/令牌中止而不打印其内容。
    findings = []
    for name in names:
        raw = (root / name).read_bytes()
        if re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}', raw):
            findings.append(name)
    assert not findings, findings
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    template = (root / '.cache/stage-r106-evidence.py').read_bytes()
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes(template.replace(b'r106-evidence', LABEL.encode()))
    print(json.dumps({'explicitFiles': len(names), 'changedBuildInputs': receipt['changedBuildInputs'],
                      'planVersion': 'v0.107', 'nativeCIPending': True, 'sourceMarkerFindings': 0}))


if __name__ == '__main__':
    main()
