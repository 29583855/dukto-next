"""日期：2026-11-07；发布剪贴板进度查询修正及R98独立Ubuntu终态，保留未完成的整体范围。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess


# 日期：2026-11-07；仅从严格回执提升具体子项，显式准备源码、文档和原件，暂不操作Git索引。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == 'eed4b5a8c1d74ed2f3f87ed1dc8bf9756d280202'
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    folder = root / 'docs/validation/2026-11-07/clipboard-r100-qualified'
    receipt_path = folder / 'verified-receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['passed'] and len(receipt['windows']) == 2 and len(receipt['buildInputs']) == 210
    assert receipt['originalBodyRequestsBefore'] == 15 and receipt['originalBodyRequestsAfter'] == 115
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    glibc_path = root / 'docs/validation/2026-11-07/exit-state-r98-final-glibc/verified-receipt.json'
    glibc = json.loads(glibc_path.read_text('utf-8'))
    assert glibc['passed'] and glibc['cleanBuild'] and glibc['coreTargets'] == 23
    report = {'planVersion': 'v0.100', 'observedUtc': datetime.now(timezone.utc).isoformat(),
              'basedOnSourceCommit': receipt['basedOnSourceCommit'], 'buildInputs': receipt['buildInputs'],
              'changedBuildInputs': receipt['changedBuildInputs'], 'windowsEvidence': helper['proof'](receipt_path),
              'nativeCIRequested': False, 'nativeCIPending': True,
              'passedScope': 'Windows clipboard availability avoids body requests on progress notifications; original empty and latest-send behavior preserved',
              'fullEditorAndSystemClipboardBudgetQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    report_path = root / 'docs/ci-verification-20261107-r100.json'
    assert not report_path.exists()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.100', observedUtc=report['observedUtc'], currentGuiSourceCommitPending=True,
                 clipboardAvailabilityR100={'manifest': helper['proof'](report_path), 'windowsEvidence': helper['proof'](receipt_path),
                                           'nativeCIPending': True, 'fullClipboardBudgetQualified': False},
                 currentSourceStage='R100 clipboard availability cache qualified on Windows; R98 independent Ubuntu clean build verified; full native latest GUI and delivery remain pending',
                 releaseQualified=False, deliveryComplete=False)
    helper['save'](index_path, index)
    note = '''

## R100剪贴板可用状态与进度解耦（2026-11-07）

- [x] 原生产QML实际复现：100次状态通知将正文请求从15增至115，失败原件保留。现在只在初始化及剪贴板变化时刷新空值布尔状态，进度查询不请求正文，不缓存待发送正文。
- [x] 双Windows完整增量构建后各4个相关GUI目标通过；其余19个原完整回归测试二进制逐SHA未变。本轮没有重新运行完整23目标。生产菜单实测100次通知不重读、空值禁用、替换后启用，实际点击向独立TCP端发送最新正文且只新增一次读取；R99草稿重试和既有拖放/复制回归继续通过。
- [x] R98独立Ubuntu完成186步干净编译、23核心/22 Qt原报告及另行监听/双栈/重启、四退出状态/原16组专项，333源文件与精确b2e4659一致；该旧GUI资格不转授R100。
- [x] 204份维护文件零TODO/占位/简化标记，C++14/格式及3份修改文件原编码/BOM/换行通过。
- [ ] R100原生Mac/Linux与新部署包继续；原R99运行42276738981仍按a316e4a独立收验。超大系统剪贴板读取前限制、生命周期、编辑器粘贴/撤销/布局、完整资源预算、完整R6/物理LAN/3×3、各平台24h、依赖源码独立重建及正式发布继续未完成。
'''
    snapshot = '''## 当前验收快照（2026-11-07，v0.100 / 剪贴板状态查询子项）

公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。本轮只修改GUI控制器的剪贴板可用状态和实际QML回归，210份构建输入见[本轮清单](docs/ci-verification-20261107-r100.json)；共用传输核心/CLI未改。双Windows子项通过，R100原生Mac/Linux资格尚待实际回归。

| 范围 | 最近已核验的结果 | 仍需完成 |
| --- | --- | --- |
| Windows | R100各4个相关GUI目标通过、其余19原测试二进制未变；生产QML的进度不重读/空值/最新正文发送通过；R98包已验 | 完整编辑器及系统剪贴板预算、真实24h终态和正式发布 |
| Linux | R98独立186步干净编译、23核心及监听/退出专项通过；R98包双显示迁移和业务/333源码/132 ELF已验 | R100原生GUI、新部署包及最新长期 |
| macOS ARM / Intel | R99实际GUI/CLI编译产物已验；R98各23核心/退出专项，R96完整协议与双部署包已验 | R99完整原运行终态、R100原生回归及新部署包、完整交互和正式分发 |
| 运行中 | R98 Windows冻结CLI的86400秒测试真实运行；旧R99精确源码完整协议继续 | 必须取得真实终态后核验，不以轮数或新GUI修改转授长期资格 |
| 整体 | 已验接收分页、发送转换预检/草稿拒绝恢复、剪贴板状态查询及部分共享资源额度/上传下载恢复子项 | 完整R6/原生GUI、全部缓存/句柄/线程预算、公平性/安全GC、物理LAN/3×3、各平台24h、依赖源码独立重建和正式发布 |

当前各平台可下载包保持原有提交身份，R100修正尚未进入已验部署包。正文请求次数不等于OS剪贴板分配峰值；完整编辑器/系统剪贴板预算继续未完成，见[决策0056](docs/decisions/0056-剪贴板可用状态与传输进度解耦.md)。历史失败、精确Darwin XFAIL和依赖证据边界均保留，整体与正式发布仍为false。

'''
    for name in ('开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md'):
        # 日期：2026-11-07；只重写当前入口，历史观察及其当时结论继续保留。
        def transform(text):
            if name == '开发计划与进度.md':
                text = text.replace('文档版本：v0.99', '文档版本：v0.100', 1)
                text = re.sub(r'^当前阶段：.*$', '当前阶段：R100剪贴板进度不重读双Windows通过，R98独立Ubuntu干净构建已验；最新原生及完整交付继续。', text, count=1, flags=re.M)
                start = text.index('## 当前验收快照')
                end = text.index('## 1. 开发目标与先后顺序', start)
                text = text[:start] + snapshot + text[end:]
            elif name == 'docs/构建验证摘要.md':
                text = text.replace(text.split('\n\n', 2)[1],
                    '更新日期：2026-11-07，计划v0.100。R100剪贴板进度查询双Windows相关GUI通过，R98独立Ubuntu干净构建及原监听/退出专项已验。R99旧完整运行、R100最新原生/部署和Windows真实24h继续；整体及正式发布未完成。', 1)
            return text + note
        helper['update'](root / name, transform)
    helper['update'](root / 'docs/Linux独立预览包.md', lambda text: text.replace(
        '该包为R98，尚未包含R99发送文本预检及拒绝保留草稿修复。',
        '该包为R98，尚未包含R99发送文本预检/拒绝保留草稿及R100剪贴板可用状态修复。', 1))
    helper['update'](root / 'docs/补充需求与关键设计.md', lambda text: text +
        '\n\n## R100：剪贴板状态与进度通知（2026-11-07）\n\n可用状态只缓存空值布尔量，在初始化/实际剪贴板变化时刷新；进度查询不读取正文，显式发送继续读取最新文本。双Windows生产QML回归通过，完整系统剪贴板和编辑器预算仍单独开放，见[决策0056](decisions/0056-剪贴板可用状态与传输进度解耦.md)。\n')
    helper['update'](root / 'README.md', lambda text: text +
        '\n\n2026-11-07 R100：传输进度刷新不再反复读取剪贴板正文，双Windows实际QML及相关GUI回归通过；R98独立Ubuntu干净编译与23核心/退出专项通过。新GUI原生回归及整体交付继续，当前下载包身份不变。\n')
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(planVersion='v0.100', r100ClipboardAvailability=report, goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], deliveryComplete=False, releaseQualified=False)
    helper['save'](state_path, state)
    shutil.copyfile(Path(__file__), folder / 'publication-preparation-driver.py')
    names = [*receipt['changedBuildInputs'], 'docs/decisions/0056-剪贴板可用状态与传输进度解耦.md',
             'docs/ci-verification-20261107-r100.json', 'docs/ci-verification-20261107-r98.json',
             'docs/current-validation.json', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/Linux独立预览包.md', 'docs/补充需求与关键设计.md', 'README.md',
             'docs/validation/2026-11-06/github-api-push-r99-platform-results.json']
    for relative in ('clipboard-r100-baseline', 'clipboard-r100-windows', 'clipboard-r100-qualified', 'exit-state-r98-final-glibc'):
        names.extend(path.relative_to(root).as_posix() for path in (root / 'docs/validation/2026-11-07' / relative).rglob('*')
                     if path.is_file() and path.suffix not in ('.zip', '.gz'))
    names = sorted(set(names))
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / '.cache/r100-clipboard-publish-files.json').write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r100-clipboard-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    stage = (root / '.cache/stage-r99-text-send.py').read_text('utf-8-sig')
    stage = stage.replace('r99-text-send-publish-files.json', 'r100-clipboard-publish-files.json').replace('r99-text-send-stage.nul', 'r100-clipboard-stage.nul')
    (root / '.cache/stage-r100-clipboard.py').write_text(stage, 'utf-8')
    print(json.dumps({'publishFiles': len(names), 'changedBuildInputs': len(receipt['changedBuildInputs']),
                      'windowsRelatedTargetsEach': 4, 'independentR98UbuntuQualified': True}), flush=True)


if __name__ == '__main__':
    main()
