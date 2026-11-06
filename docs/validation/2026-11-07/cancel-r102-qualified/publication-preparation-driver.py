"""日期：2026-11-07；发布已过双Windows的慢端测试夹具，Linux对照和Mac原生复验保持待验。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

PARENT = '67404eb89356c78ee2a8fd62cc8eda68bb197522'


# 日期：2026-11-07；保持已发布源码及原失败身份，只按实际Windows原件准备新输入的显式发布清单。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    published = json.loads((root / '.cache/r101-ci-evidence-published-tree-verification.json').read_text('utf-8'))
    assert published['passed'] and published['sourceCommit'] == PARENT
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    receipt_path = root / 'docs/validation/2026-11-07/cancel-r102-qualified/verified-receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['passed'] and len(receipt['windows']) == 2 and receipt['freshFull23TargetsRun']
    assert receipt['changedBuildInputs'] == ['tests/ui_tests.cpp'] and not receipt['productionCoreChanged']
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    report_path = root / 'docs/ci-verification-20261107-r102.json'
    assert not report_path.exists()
    report = {'planVersion': 'v0.102', 'observedUtc': datetime.now(timezone.utc).isoformat(),
        'basedOnSourceCommit': receipt['basedOnSourceCommit'], 'parentDocumentationCommit': PARENT,
        'buildInputs': receipt['buildInputs'], 'changedBuildInputs': receipt['changedBuildInputs'],
        'windowsEvidence': proof(receipt_path), 'sourceAudit': receipt['sourceAudit'],
        'productionCoreChanged': False, 'productCancellationBugFixClaimed': False,
        'cancellationAndEofBudgetMilliseconds': 5000,
        'qualifiedScope': 'Windows UCRT/MSVC fresh full 23 CTest targets each and 18 native/high-DPI cancellation rows; same-controller later bidirectional contents',
        'nativeCIRequested': False, 'nativeCIPending': True,
        'independentUbuntuOldNewComparisonStatus': 'running in separate directory; no terminal qualification yet',
        'wholeF18Qualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    note = '''

## R102取消测试慢端时序修正（2026-11-07）

- [x] 仅修改tests/ui_tests.cpp的独立慢端夹具：接管原生描述符之前即设置64KiB读取上限，取消后以256KiB窗口排空。原32MiB正文和取消/EOF各5000ms保持，未改共用传输核心或CLI，也不宣称修复产品取消缺陷。原编码/BOM/换行保持，新增函数中文日期注释和格式检查通过。
- [x] 双Windows完整构建、各23核心/22份Qt原报告与原生/150%/200%场景18行取消通过；逐行验证临时清理/额度归还，取消后的同一控制器双向传输并核对内容。原生QtTest白名单拒绝剪贴板测试的负例继续通过。
- [x] 独立收验器最初错误要求头像既有警告必定出现一次，实际两工具链均未出现；原失败收验器及XML保留。修正为只允许零条或精确一条已知警告，未知消息仍拒绝；不重复产品测试。文件交换64条已知qinfo逐条核对，全部真实失败节点为零。
- [x] 204维护文件零TODO/占位/简化标记，C++14及格式通过。[本轮输入及证据](docs/ci-verification-20261107-r102.json)。R101四runner原始发送取消失败与R100成功补跑独立保留；当前Mac下载仍为已验R101编译原件或R100含依赖包。
- [ ] 独立Ubuntu干净构建中的旧/新夹具对照、完整核心/原生/高DPI及十轮取消仍在执行；R102精确公开后的四平台CI须取得实际原件。两Mac旧EOF超时的夹具假设仍需原生复验，不以Windows通过推断全部根因已解决。
- [ ] 完整R6/GUI、编辑器及OS剪贴板/全部资源预算、公平性/安全GC、物理LAN/3×3、各平台86400秒终态、依赖源码独立重建、最低干净系统及正式签名公证继续未完成。deliveryComplete=false、releaseQualified=false，整体active。
'''
    # 日期：2026-11-07；当前快照指明新输入的已验子项，先前CI失败及包身份继续独立保留。
    def plan(text):
        text = text.replace('文档版本：v0.101', '文档版本：v0.102', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R102仅修正慢端取消测试夹具，双Windows各23核心与原生/高DPI已验；独立Ubuntu对照继续，四平台新CI待精确公开后验证。', text, count=1, flags=re.M)
        text = text.replace('v0.101 / 兼容取消与后续传输回归', 'v0.102 / 慢端测试夹具与原生复验', 1)
        text = text.replace('R101为生产QML取消与原生测试接线增强，210份构建输入见[本轮清单](docs/ci-verification-20261107-r101.json)，共用传输核心/CLI源码与R100一致。',
            'R102仅修改取消测试的独立慢接收端，210份构建输入见[本轮清单](docs/ci-verification-20261107-r102.json)，共用传输核心/CLI源码保持原字节。', 1)
        text = text.replace('R101双工具链各23核心及原生/150%/200%场景', 'R102双工具链各23核心及原生/150%/200%场景', 1)
        text = text.replace('四平台新编译成功；R101新增发送取消回归发现失败',
            'R101四平台编译成功但新增发送取消回归发现失败', 1)
        text = text.replace('R102夹具候选本机验证中', 'R102双Windows已验、独立Ubuntu对照继续，四原生新CI待公开后启动', 1)
        return text.rstrip() + note
    update(root / '开发计划与进度.md', plan)
    local_note = note.replace('(docs/', '(')
    update(root / 'docs/执行进度.md', lambda text: text.rstrip() + local_note)
    update(root / 'docs/构建验证摘要.md', lambda text: text.replace(text.split('\n\n', 2)[1],
        '更新日期：2026-11-07，计划v0.102。R102只修正独立慢端测试夹具，双Windows各23核心及原生/高DPI已验；独立Ubuntu对照继续，新四原生CI待精确公开后验证。R101双Mac编译已验、原取消失败保留；R100四平台23核心/188协议原件已验，长期与完整交付继续。', 1).rstrip() + local_note)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.102', observedUtc=report['observedUtc'], currentGuiSourceCommitPending=True,
        publicVerificationReceipt=report_path.relative_to(root).as_posix(),
        cancelFixtureR102={'manifest': proof(report_path), 'windowsEvidence': proof(receipt_path),
                          'independentUbuntuComparisonPending': True, 'nativeCIPending': True,
                          'wholeF18Qualified': False},
        currentSourceStage='R102 independent slow-peer fixture revised only; Windows two toolchains passed complete core and native/high-DPI; independent Ubuntu comparison running; native CI pending exact publication',
        releaseQualified=False, deliveryComplete=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(planVersion='v0.102', cancelFixtureR102=report, goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    qualified = root / 'docs/validation/2026-11-07/cancel-r102-qualified'
    shutil.copyfile(Path(__file__), qualified / 'publication-preparation-driver.py')
    names = {'开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/current-validation.json',
             'docs/ci-verification-20261107-r102.json', 'tests/ui_tests.cpp',
             'docs/validation/2026-11-07/cancel-r102-source-audit.json',
             'docs/validation/2026-11-06/github-api-push-r101-ci-evidence.json'}
    for folder in ('cancel-r102-windows', 'cancel-r102-qualified', 'cancel-r102-fixture', 'cancel-r102-verifier-correction'):
        names.update(p.relative_to(root).as_posix() for p in (root / 'docs/validation/2026-11-07' / folder).rglob('*')
                     if p.is_file() and p.suffix not in ('.zip', '.gz', '.png'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    label = 'r102-fixture'
    (root / ('.cache/' + label + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + label + '-stage.nul')).write_bytes(b''.join(p.encode('utf-8') + b'\0' for p in names))
    stage = (root / '.cache/stage-r101-cancel.py').read_bytes().replace(b'r101-cancel', label.encode())
    (root / ('.cache/stage-' + label + '.py')).write_bytes(stage)
    print(json.dumps({'explicitFiles': len(names), 'changedBuildInputs': ['tests/ui_tests.cpp'],
                      'windowsToolchainsVerified': 2, 'nativeCIAndUbuntuPending': True}))


if __name__ == '__main__':
    main()
