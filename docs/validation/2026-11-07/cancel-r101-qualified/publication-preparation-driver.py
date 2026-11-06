"""日期：2026-11-07；发布原生兼容取消回归和已核验Windows原件，更新计划并保留全部未完成要求。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

PARENT = '2cd57b1e810e312651025a1951b8b57f15e59c2f'


# 日期：2026-11-07；先核对实际终态回执，再按显式清单准备发布checkout，不操作索引或更改提交。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    qualified = root / 'docs/validation/2026-11-07/cancel-r101-qualified'
    receipt_path = qualified / 'verified-receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['passed'] and receipt['freshFull23TargetsRun'] and len(receipt['windows']) == 2
    assert receipt['originalTransferCoreUnchanged'] and not receipt['productionCancellationBugFixClaimed']
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    report = {'planVersion': 'v0.101', 'observedUtc': datetime.now(timezone.utc).isoformat(),
              'basedOnSourceCommit': receipt['basedOnSourceCommit'], 'buildInputs': receipt['buildInputs'],
              'changedBuildInputs': receipt['changedBuildInputs'], 'windowsEvidence': proof(receipt_path),
              'originalTransferCoreUnchanged': True, 'productionCancellationBugFixClaimed': False,
              'nativeCIRequested': False, 'nativeCIPending': True,
              'qualifiedScope': 'Windows MSVC/UCRT 23 targets each; production QML cancellation in 3 phases, native and 150/200 percent scenes, cleanup and later same-instance bidirectional content; native QtTest selector rejects clipboard slots',
              'wholeF18Qualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    report_path = root / 'docs/ci-verification-20261107-r101.json'
    assert not report_path.exists()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    note = '''

## R101兼容取消与同实例后续传输回归（2026-11-07）

- [x] 生产QML实际点击取消，分别停在发送中、8字节部分包头、64KiB不足内部256KiB块的正文；验证有界结束、部分发送EOF、临时文件清理和共享额度归还。每次取消后的同一控制器继续完成发送与接收，逐内容核对，未复制原版中止后Qt4崩溃行为。证据见`docs/validation/2026-11-07/cancel-r101-qualified/verified-receipt.json`。
- [x] 双Windows完整增量构建、各23核心目标/22份Qt原报告通过；另行原生Windows及150%/200%隔离场景各三取消行，合计18行均通过。原生QtTest执行槽限制为服务器入口和取消场景，夹带剪贴板测试在执行前退出2，避免改变系统剪贴板。
- [x] Qt JUnit的`errors`计入消息：每工具链文件交换报告的64条均为故障夹具qinfo，头像报告的一条为既有QNetworkReply qwarn，逐类型/数量披露；所有真实failure/error节点为零且testcase均pass。本轮取消及原生报告继续要求零警告，未忽略未知失败。
- [x] 首轮失败保留并纠正诊断：新测试错误要求收满内部块前进度大于零；原监听器在启动工作线程前已报告接收状态，取消入口本来可用。未验证的重复起始事件草稿已撤回，`legacy.cpp/h`与公开R100逐字节一致；本轮修改是测试接线与按钮定位名，不宣称修复了既有取消故障。后续本机收验器误读JUnit、工具路径/CTest输出格式判断失败均单独留存。
- [x] 204份维护文件零TODO/占位/简化标记，C++14/格式和修改文件原编码/BOM/换行已验。首轮任务表同步实际Windows/Linux/双Mac构建与部署事实，去除仍写“macOS未验证”的陈旧状态。
- [ ] Mac/Linux本轮原生取消仍待CI真实终态与原件；当前含依赖部署包保留R100源码身份。原版混合拖放、完整F18/GUI、全部资源与编辑器预算、公平性/安全GC、物理LAN/3×3、各平台24h、依赖源码独立重建、最低干净系统及正式发布继续未完成；不以本轮回归转授这些资格。
'''
    snapshot = '''## 当前验收快照（2026-11-07，v0.101 / 兼容取消与后续传输回归）

公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R101为生产QML取消与原生测试接线增强，210份构建输入见[本轮清单](docs/ci-verification-20261107-r101.json)，共用传输核心/CLI源码与R100一致。双Windows各23核心及原生/高DPI三取消场景通过；Mac/Linux本轮原生子项待CI原件。

| 范围 | 最近已核验的结果 | 仍需完成 |
| --- | --- | --- |
| Windows | R101双工具链各23核心及原生/150%/200%场景，取消清理后同实例双向内容核对通过；R100部署包已验 | 完整编辑器及系统剪贴板预算、真实24h终态和正式发布 |
| Linux | R100各23核心、剪贴板/草稿QML、338源码/708载荷/132 ELF与双显示部署业务已验 | R101原生取消、完整交互、真实24h终态和完整故障矩阵 |
| macOS ARM / Intel | R100各23核心、双含依赖部署包和真实APFS盘满恢复已验；首轮Intel报告上传失败已定向补跑 | R100完整协议原件、R101原生取消、完整交互/选择器和正式分发 |
| 运行中 | R98 Windows与独立Ubuntu冻结CLI各自执行86400秒；R100只补Intel任务；R101原生CI待本次源码公开后接续 | 必须取得实际终态后核验，不以轮数或新测试转授长期资格 |
| 整体 | 接收分页、发送预检/草稿恢复、剪贴板状态查询及部分资源/恢复子项已验 | 完整R6/GUI、全部预算、公平性/安全GC、物理LAN/3×3、各平台24h、依赖源码独立重建和正式发布 |

首轮取消测试中的非零进度断言有误，诊断已纠正；原监听器已有接收起始状态，未改变传输核心。当前Windows、双Mac和Linux含依赖部署包仍为R100精确源码ed4f5cf，下载与摘要见各平台预览包说明。历史失败、两条精确Darwin XFAIL及依赖证据边界继续保留，整体与正式发布仍为false。

'''

    # 日期：2026-11-07；主入口描述当前证据，原有历史记录完整保留。
    def plan(text):
        text = text.replace('文档版本：v0.100', '文档版本：v0.101', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R101取消/恢复双Windows核心和原生高DPI子项通过；Mac/Linux原生、R100 Intel报告及长期/完整交付继续。', text, count=1, flags=re.M)
        start = text.index('## 当前验收快照')
        end = text.index('## 1. 开发目标与先后顺序', start)
        text = text[:start] + snapshot + text[end:]
        old = '进行中：新端取消再接收/截断/超时子项通过，完整三平台仍待验；原版失败保留'
        assert text.count(old) == 1
        text = text.replace(old, '进行中：双Windows原生/高DPI实际取消及同实例双向后续内容核验通过；Mac/Linux与完整三平台待验，原版失败保留', 1)
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    update(root / 'docs/执行进度.md', lambda text: text.rstrip() + note)
    update(root / 'docs/构建验证摘要.md', lambda text: text.replace(text.split('\n\n', 2)[1],
        '更新日期：2026-11-07，计划v0.101。R101兼容取消/同实例后续传输双Windows各23核心与原生/高DPI回归通过，Mac/Linux本轮原生待验。R100双Mac含依赖包和APFS盘满子集已验、Intel原报告上传故障定向补跑；Windows/Linux真实24h及整体交付继续。', 1).rstrip() + note)

    # 日期：2026-11-07；首轮任务表原为陈旧的v0.20状态，按已有公开原件更新子项而不扩大整体资格。
    def tasks(text):
        text = text.replace('对应主计划：v0.20', '对应主计划：v0.101（2026-11-07同步）', 1)
        changes = {
            '进行中：Windows 两工具链及 Alpine/Ubuntu x64 GUI/CLI、SQLite/TLS 构建运行子项通过；最新会话/排队 Linux 固定快照重建中，macOS 双架构未验证':
            '进行中：Windows双工具链、Ubuntu/Alpine及macOS ARM/Intel的Qt5 GUI/CLI、SQLite/TLS已有实际构建运行；R100三平台含依赖包已验，依赖源码独立重建/最低干净系统继续',
            '主动截图无原版入口按扩展保留；原版中止对照待验':
            '主动截图无原版入口按扩展保留；发送Abort/EOF和随后原版Qt4崩溃、接收无主动中止的实际基线已保留，完整协议对照继续',
            '进行中：Windows 两工具链最新 17/17 CTest、Alpine/Ubuntu 较早固定快照各 16/16 实际通过；三平台工作流已编写，尚无远端 CI/macOS 结果':
            '进行中：Windows双工具链和Ubuntu/双Mac实际构建及各23核心已有原件；三平台CI、独立CLI和R100部署已验，最低干净系统/完整矩阵继续',
            'Linux 真实磁盘耗尽通过，三平台整体验收待补齐':
            'Linux真实磁盘耗尽和双Mac APFS盘满恢复子集通过；R101双Windows实际QML取消及同实例双向后续传输通过，三平台整体验收待补齐',
            'Windows 三页/工具栏、设置/首次说明/截图/单实例已验证，三平台缩放待验':
            'Windows基础交互及三平台原生服务器主窗口/缩放部署子项已有原件；R101双Windows原生/高DPI取消通过，完整三平台R6交互仍待',
            '主计划 v0.24 与决策 0002–0007 已细分服务器/多通道/恢复/会话/公平等待':
            '主计划v0.101及后续决策已细分并实现服务器/多通道/恢复/会话与部分共享预算，按实际子项验收',
            'Windows x64 的安装、GUI/CLI 构建和 TLS 实际握手已验证；其余目标仍待验证。':
            'Windows双工具链、Ubuntu/Alpine、macOS ARM/Intel均已有安装/构建/运行证据；三平台R100含依赖部署包已验，具体来源及原件见[当前索引](current-validation.json)。依赖源码独立重建与最低干净系统仍待验证。',
            '| Qt5/C++14 与 macOS 双架构的具体可用版本 | 大规模 GUI 开发前 | 未验证 |':
            '| Qt5/C++14 与 macOS 双架构的具体可用版本 | 大规模 GUI 开发前 | 原生ARM/Intel构建运行及R100含依赖部署已验；依赖来源已记，源码独立重建/最低系统继续 |'
        }
        for before, after in changes.items():
            assert text.count(before) == 1, before
            text = text.replace(before, after, 1)
        return text.rstrip() + '\n\n同步说明：本表记录具体子项，完整阶段以主计划及当前原件索引为准；不把构建通过当作完整功能、全资源预算或正式发布通过。\n'

    update(root / 'docs/首轮开发任务清单.md', tasks)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.101', observedUtc=report['observedUtc'], currentGuiSourceCommitPending=True,
        cancelRecoveryR101={'manifest': proof(report_path), 'windowsEvidence': proof(receipt_path),
                           'nativeCIPending': True, 'wholeF18Qualified': False},
        currentSourceStage='R101 native cancellation regression extended; Windows MSVC/UCRT complete core and native/high-DPI passed; R100 deployed package identity retained; full delivery and native qualification pending',
        releaseQualified=False, deliveryComplete=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(planVersion='v0.101', cancelRecoveryR101=report, goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], deliveryComplete=False, releaseQualified=False)
    save(state_path, state)
    shutil.copyfile(Path(__file__), qualified / 'publication-preparation-driver.py')
    shutil.copyfile(root / '.cache/r101-inflight-long-observation.json', qualified / 'inflight-long-observation.json')
    (qualified / 'local-tool-failures.json').write_text(json.dumps({
        'date': '2026-11-07', 'failuresRetained': [
            {'stage': 'Wrong Python path', 'exitCode': 1, 'productMutatedOrRun': False},
            {'stage': 'Initial cancellation test incorrectly demanded nonzero partial-block progress',
             'evidence': proof(root / 'docs/validation/2026-11-07/cancel-r101-windows/driver-result.json')},
            {'stage': 'Incorrect product diagnosis; redundant core event draft restored exactly before validation',
             'evidence': proof(root / 'docs/validation/2026-11-07/cancel-r101-windows/diagnosis-correction.json')},
            {'stage': 'Local collector expected native Qt XML instead of JUnit after UCRT 23 passed',
             'evidence': proof(root / 'docs/validation/2026-11-07/cancel-r101-corrected-windows/collector-failure.json')},
            {'stage': 'Verifier initially treated Qt JUnit message counter as failure counter',
             'evidence': proof(qualified / 'initial-verifier-failure.json')},
            {'stage': 'Native preparation required old CTest summary spelling', 'exitCode': 1,
             'failedBeforeMutation': True, 'correction': 'Accept both actual complete 23/23 summary formats'}],
        'qualificationThresholdReduced': False, 'releaseQualified': False, 'deliveryComplete': False}, indent=2) + '\n', 'utf-8')
    names = {'开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/首轮开发任务清单.md',
             'docs/current-validation.json', 'docs/ci-verification-20261107-r101.json',
             'docs/validation/2026-11-06/github-api-push-r100-original-send-abort.json',
             *receipt['changedBuildInputs']}
    for folder in ('cancel-r101-windows', 'cancel-r101-corrected-windows', 'cancel-r101-final-windows', 'cancel-r101-qualified'):
        names.update(path.relative_to(root).as_posix() for path in (root / 'docs/validation/2026-11-07' / folder).rglob('*')
                     if path.is_file() and path.suffix not in ('.zip', '.gz'))
    names = sorted(names)
    for name in names:
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    listing = root / '.cache/r101-cancel-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r101-cancel-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    stage = (root / '.cache/stage-r100-original-send-abort.py').read_bytes().replace(b'r100-original-send-abort', b'r101-cancel')
    (root / '.cache/stage-r101-cancel.py').write_bytes(stage)
    print(json.dumps({'explicitFilesPrepared': len(names), 'buildInputs': len(receipt['buildInputs']),
                      'changedBuildInputs': receipt['changedBuildInputs'], 'qualifiedWindowsToolchains': 2}))


if __name__ == '__main__':
    main()
