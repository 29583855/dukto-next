"""日期：2026-11-07；仅在独立Windows核验完成后更新进度并准备显式发布集。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess

PARENT = '8f5d6050f85415e2eed5ffb651dbe1f97a3af247'
LABEL = 'r108-expiry'


# 日期：2026-11-07；每项完成凭原件标记，独立Linux及新Mac回归保持待验收。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    receipt_path = base / 'expiry-r108-qualified/receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['passed'] and len(receipt['windows']) == 2
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    native_core = base / 'secure-ready-r107-native-core/receipt.json'
    ubuntu = base / 'secure-ready-r107-native-job-terminals/ubuntu-22.04/receipt.json'
    old = json.loads(ubuntu.read_text('utf-8'))
    assert old['thisNativeJobVerified'] and old['job']['conclusion'] == 'success'
    authors = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
               'docs/状态目录维护保护.md', 'docs/current-validation.json']
    backup = root / '.cache/expiry-r108-docs-before'
    backup.mkdir(exist_ok=True)
    for name in authors:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == (root / name).read_bytes()
        else:
            shutil.copyfile(root / name, target)
    manifest = {'planVersion': 'v0.108', 'observedUtc': datetime.now(timezone.utc).isoformat(),
                'basedOnPublishedCommit': PARENT, 'buildInputs': receipt['buildInputs'],
                'changedBuildInputs': receipt['changedBuildInputs'], 'windowsEvidence': proof(receipt_path),
                'sourceStage': 'R108 targeted expired upload temporary body cleanup and CLI; original metadata retained',
                'r107NativeCoreEvidence': proof(native_core), 'r107UbuntuTerminal': proof(ubuntu),
                'nativeCIPending': True, 'independentUbuntuPending': True,
                'globalDiskBudgetImplemented': False, 'clientDownloadCleanupImplemented': False,
                'throughputImprovementProven': False, 'originalUbuntuTimeoutCauseEstablished': False,
                'releaseQualified': False, 'deliveryComplete': False}
    manifest_path = root / 'docs/ci-verification-20261107-r108.json'
    assert not manifest_path.exists()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    note = '''

## R108过期上传临时文件维护（2026-11-07）

- [x] 增加本机`serve cleanup preview|run --client UUID --task UUID`。暂停/中断保留7天、失败/取消保留30天；独占维护、任务及接收租约、强清单和根身份核对后，回收已记录原生身份的接收临时文件。[用法与范围](docs/过期任务临时文件清理.md)。
- [x] 任务过期与凭据先FULL提交，逐文件删除意图和清理确认分别FULL提交；真实子进程在删除后、确认前退出可以重入。源文件、最终文件、目录及未知身份项保留，提交不确定项拒绝；任务元数据及原请求幂等键不删除。
- [x] 双Windows各24核心/23 XML、18行清理专项（含初始化/结束）、31 TLS、完整4/16通道逐项查询及16通道双向传输通过；两套真实八进程分别验证版本一/二迁移到三、字段保持和锁恢复。[独立收验](docs/validation/2026-11-07/expiry-r108-qualified/receipt.json)。
- [x] 开发中的编译错误、104项夹具误关未完成接收以及旧版本二断言失败原件分别保留。修正迁移Python夹具后，以同一二进制重验；原全驱动输入稳定性false保留，独立核对仅这一未参与原五条命令的夹具有改动，C++及原协议输入未变。
- [x] R107四平台核心附件、88 XML及48取消行已验；GitHub Ubuntu完整作业终态success和47协议已收验。R107其他作业继续，独立Ubuntu原小文件超时仍保留，不宣称根因解决或端到端提速。
- [x] 210份维护源码无TODO/FIXME/占位/简化标记；C++14、格式、中文日期函数注释及原UTF-8无BOM/LF保持。
- [ ] R108独立Ubuntu及新原生回归继续。全局自动GC、客户端下载/目录临时项回收、256MiB历史及活动清单总磁盘预算、完整R6/GUI、物理LAN/3×3、各平台24h和正式分发仍待完成。本命令不释放任务记录数量上限，整体与发布资格仍为false。
'''

    # 日期：2026-11-07；当前快照突出新完成子项，历史失败及原平台包版本继续保留。
    def plan(text):
        assert '文档版本：v0.107' in text
        text = text.replace('文档版本：v0.107', '文档版本：v0.108', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R108过期上传临时文件维护与CLI通过双Windows；独立Ubuntu和新原生继续，整体交付未完成。', text, count=1, flags=re.M)
        text = text.replace('v0.107 / 安全通道就绪路径与Intel终态', 'v0.108 / 过期上传临时文件维护', 1)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R108新增过期服务器上传临时正文的有界预览与可重入清理CLI，保留任务/请求幂等记录；双Windows各24核心、31 TLS及原传输专项通过。R107 GitHub Ubuntu完整47协议已验，其余原生及R108新验证继续；独立Ubuntu原超时保留。双Mac含依赖预览仍为R105，Windows/Linux仍为R100。[本轮证据](docs/ci-verification-20261107-r108.json)。整体未完成。' + text[end:]
        text = text.replace('R104双工具链各23核心及占用/崩溃恢复专项通过，原测试夹具失败保留；R100部署另验', 'R108双工具链各24核心、过期清理/CLI及原传输专项通过；R100部署另验', 1)
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: re.sub(r'^公开仓库为.*$', '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R108新增[过期上传临时文件维护CLI](docs/过期任务临时文件清理.md)，双Windows各24核心及原传输专项已验；新Linux/macOS回归继续。R107双Mac GUI/CLI已有编译归档，[含依赖双Mac预览](docs/macOS独立预览包.md)仍为R105。完整交付见[计划](开发计划与进度.md)和[本轮证据](docs/ci-verification-20261107-r108.json)。', text, count=1, flags=re.M))
    update(root / 'docs/状态目录维护保护.md', lambda text: text.replace('R104先提供维护互斥基础。过期任务回收、临时数据清理、全局磁盘配额和CLI清理入口仍须分别实现与验收。', 'R104提供维护互斥基础；R108新增[过期服务器上传临时文件维护CLI](过期任务临时文件清理.md)。全局自动回收、客户端下载/目录临时项回收及总磁盘预算仍须分别实现与验收。', 1).replace('暂不开放任何删除命令。', 'R108仅开放明确指定任务、保留期及原生身份约束下的临时正文清理，不开放按目录或终态批量删除。', 1).replace('回收的后续步骤仍包括：有界预览、区分可恢复任务和完成结果、保留有效幂等键、固定临时文件身份、崩溃可重入的回收顺序、SQLite旁路文件和总磁盘预算。', 'R108已提供指定服务器上传任务的有界预览、有效幂等键保留、固定临时文件身份及崩溃可重入删除顺序；SQLite回滚由引擎处理且拒绝WAL接收库。其余回收范围与全局总磁盘预算继续。', 1))
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.108', observedUtc=manifest['observedUtc'],
                 publicVerificationReceipt=manifest_path.relative_to(root).as_posix(),
                 currentSourceStage=manifest['sourceStage'], currentGuiSourceCommitPending=True,
                 expiredUploadCleanupR108={'manifest': proof(manifest_path), 'windowsEvidence': proof(receipt_path),
                                          'nativeCIPending': True, 'independentUbuntuPending': True,
                                          'globalDiskBudgetImplemented': False},
                 releaseQualified=False, deliveryComplete=False)
    index['secureReadyR107'].update(nativeCoreEvidence=proof(native_core), ubuntuCompleteTerminal=proof(ubuntu))
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(planVersion='v0.108', expiredUploadCleanupR108=manifest, goalStatus='active',
                 workingSourceStage=manifest['sourceStage'], releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    qualified = receipt_path.parent
    shutil.copyfile(__file__, qualified / 'publication-preparation-driver.py')
    shutil.copyfile(root / '.cache/r108-inflight-long-observation.json', qualified / 'inflight-long-observation.json')
    shutil.copyfile(root / '.cache/r107-native-run.json', qualified / 'r107-native-observation.json')
    names = set(authors + receipt['changedBuildInputs'] + ['docs/ci-verification-20261107-r108.json',
                'docs/过期任务临时文件清理.md', 'docs/validation/2026-11-06/github-api-push-r107-terminal-evidence.json'])
    for folder in ('expiry-r108-windows', 'expiry-r108-qualified', 'expiry-r108-processes', 'expiry-r108-development',
                   'secure-ready-r107-native-core', 'secure-ready-r107-native-job-terminals/ubuntu-22.04'):
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*')
                     if path.is_file() and path.suffix in ('.json', '.jsonl', '.xml', '.log', '.txt', '.sha256', '.py', '.png', '.stderr'))
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
    print(json.dumps({'explicitFiles': len(changes), 'changedBuildInputs': receipt['changedBuildInputs'],
                      'planVersion': 'v0.108', 'independentUbuntuPending': True, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
