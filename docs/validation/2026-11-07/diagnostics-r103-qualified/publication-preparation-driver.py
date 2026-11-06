"""日期：2026-11-07；只发布已验诊断子项，原生复验、长测和整体交付保持未完成。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess

PARENT = '91a968b8637de5fa00ac3a2af6c4096299a651ca'


# 日期：2026-11-07；严格依据收验原件编制显式文件清单，暂存、提交和上传必须随后各自实际成功。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    verified = json.loads((root / '.cache/r102-native-evidence-published-tree-verification.json').read_text('utf-8'))
    assert verified['passed'] and verified['sourceCommit'] == PARENT
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    receipt_path = root / 'docs/validation/2026-11-07/diagnostics-r103-qualified/verified-receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['passed'] and len(receipt['windows']) == 2 and len(receipt['buildInputs']) == 213
    assert not receipt['entireR10Qualified'] and not receipt['macLinuxR103RuntimeVerified']
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    report_path = root / 'docs/ci-verification-20261107-r103.json'
    assert not report_path.exists()
    report = {'planVersion': 'v0.103', 'observedUtc': datetime.now(timezone.utc).isoformat(),
        'basedOnPublishedCommit': PARENT, 'buildInputs': receipt['buildInputs'],
        'windowsEvidence': proof(receipt_path), 'sourceAudit': receipt['sourceAudit'],
        'qualifiedScope': 'Windows UCRT/MSVC initial full23 execution, original fixture failure retained; final two QML targets rechecked, other20 Qt binaries unchanged; real CLI doctor/contract/human output passed',
        'nativeCIPending': True, 'nativeSaveDialogVerified': False, 'entireR10Qualified': False,
        'macLinuxR103RuntimeVerified': False, 'releaseQualified': False, 'deliveryComplete': False}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    observation = root / '.cache/r103-inflight-long-observation.json'
    long_copy = receipt_path.parent / 'inflight-long-observation.json'
    assert not long_copy.exists()
    shutil.copyfile(observation, long_copy)
    note = '''

## R103本地诊断与JSON导出（2026-11-07）

- [x] GUI设置新增“导出本地诊断”，CLI doctor共用核心：检查运行库、配置、状态/接收目录及TCP监听；目录使用固定短探针实际创建/写入/同步/清理，不遍历用户文件。显式INI在Qt解析前有界读取，配置和报告各64KiB上限；默认未建立目录明确not-created，显式不存在则失败。
- [x] CLI只有显式--profile才使用已有配对资料主动连接，核验TLS身份和认证，输出已知能力布尔值；撤销后失败，不改变资料/信任，不创建传输任务。报告不收集令牌、配置值、绝对文件路径或传输正文，不自动上传。同目录原子提交，已有报告拒绝覆盖，临时文件自动清理。[用法](docs/本地诊断.md)。
- [x] 双Windows初轮完整23目标均有新增UI夹具失败，原件保持：测试缺生产版本上下文并在设置弹窗打开前找视觉按钮。修正后各2个QML目标、真实CLI诊断12类/CLI契约/终端逐项结果通过，其余20个Qt测试程序前后SHA未变并复用首轮通过原件；不称修正后重新执行全部23目标。[严格回执](docs/validation/2026-11-07/diagnostics-r103-qualified/verified-receipt.json)。
- [x] 207维护文件零TODO/占位/简化标记，C++14、clang-format及原编码/BOM/换行通过，213份构建输入冻结。R102旧夹具失败、四原生核心取消子项和已验Mac编译归档保持各自身份；当前三平台含依赖部署包继续为R100。
- [ ] R103新Mac/Linux编译和运行须精确公开后按实际CI原件验证，原生保存选择器交互及整个R10分阶段日志仍待验。R102完整协议与独立Ubuntu对照另行收验，Windows/Linux冻结86400秒仍运行；完整R6/GUI、编辑器及OS剪贴板/全部资源、公平性/安全GC、物理LAN/3×3、各平台长期、依赖源码独立重建、最低干净系统及正式签名公证继续。deliveryComplete=false、releaseQualified=false，整体active。
'''
    def plan(t):
        assert '文档版本：v0.102' in t
        t = t.replace('文档版本：v0.102', '文档版本：v0.103', 1)
        t = re.sub(r'^当前阶段：.*$', '当前阶段：R103本地诊断/原子JSON导出和已配对能力检查通过双Windows子项；新四原生验证待公开触发，R102协议/Ubuntu对照及长期交付继续。', t, count=1, flags=re.M)
        t = t.replace('v0.102 / 慢端测试夹具与原生复验', 'v0.103 / 本地诊断与原子导出', 1)
        start = t.index('公开仓库：', t.index('## 当前验收快照'))
        end = t.index('\n\n| 范围', start)
        t = t[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R103增加GUI/CLI共用本地诊断和有界原子JSON导出，213份构建输入见[本轮清单](docs/ci-verification-20261107-r103.json)；双Windows子项已验，新Mac/Linux运行待精确公开后验证。R102四平台核心/48行取消及双Mac编译原件、R101原失败和R100完整补跑分别保持，不转授新源码全部资格。' + t[end:]
        t = t.replace('R102双工具链各23核心及原生/150%/200%场景，取消清理后同实例双向内容核对通过；R100部署包已验', 'R103诊断/CLI通过；初轮23目标后定向复验2个QML，其余20个Qt程序SHA未变；R102原生取消及R100部署另验', 1)
        t = t.replace('R102各23核心及原生/高DPI取消子集已验；R100含依赖部署与双显示业务已验', 'R102各23核心及原生/高DPI取消子集已验；R100含依赖部署已验；R103诊断待原生验证', 1)
        t = t.replace('R102双架构GUI/CLI编译及各23核心/取消子集已验；R100含依赖部署/APFS/完整补跑已验', 'R102双架构GUI/CLI编译和核心取消已验；R100部署/APFS/完整补跑已验；R103待原生验证', 1)
        t = t.replace('| `doctor` | 只读检查配置、依赖、路径、端口及对端能力，导出诊断 | `dukto-cli doctor --json` |', '| `doctor` | 检查配置/依赖，短探针检查目录和TCP；显式资料认证查能力，原子导出本地报告 | `dukto-cli doctor --report report.json --json` |', 1)
        t = t.replace('诊断导出与完整阶段观测待验', 'R103本地诊断/原子导出双Windows子项已验；新原生/保存选择器和完整阶段观测待验', 1)
        return t.rstrip() + note
    update(root / '开发计划与进度.md', plan)
    local_note = note.replace('(docs/', '(')
    update(root / 'docs/执行进度.md', lambda t: t.rstrip() + local_note)
    update(root / 'docs/构建验证摘要.md', lambda t: t.replace(t.split('\n\n', 2)[1],
        '更新日期：2026-11-07，计划v0.103。GUI/CLI共用本地诊断、64KiB原子JSON导出和显式已配对能力检查已通过双Windows子项；初轮UI夹具失败原件保留，2个QML目标修正后复验通过，其余20个Qt程序SHA未变。新Mac/Linux、原生选择器及完整R10/整体交付继续。', 1).rstrip() + local_note)
    update(root / 'docs/补充需求与关键设计.md', lambda t: t.rstrip() + '''

## 本地诊断实施补充（2026-11-07）

R103提供共用核心的GUI设置导出和CLI doctor --report；明确临时目录写探针与显式TCP绑定，只有--profile才连接已有配对对端。INI先有界读再解析，报告/INI各64KiB，固定JSON字段白名单不包含令牌、任意配置值或文件正文。同目录原子发布且不覆盖已有目标。双Windows子项已验，完整R10分阶段日志、原生保存选择器和Mac/Linux新源码验证继续，详见[本地诊断](本地诊断.md)。
''')
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.103', observedUtc=report['observedUtc'], currentGuiSourceCommitPending=True,
        publicVerificationReceipt=report_path.relative_to(root).as_posix(),
        diagnosticsR103={'manifest': proof(report_path), 'windowsEvidence': proof(receipt_path),
                        'macLinuxNativePending': True, 'nativeSaveDialogVerified': False, 'entireR10Qualified': False},
        currentSourceStage='R103 bounded local diagnostics/export and explicit paired capabilities; Windows qualified subset; new native CI pending publication',
        releaseQualified=False, deliveryComplete=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(planVersion='v0.103', diagnosticsR103=report, goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    shutil.copyfile(Path(__file__), receipt_path.parent / 'publication-preparation-driver.py')
    names = {'开发计划与进度.md', 'README.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
        'docs/补充需求与关键设计.md', 'docs/本地诊断.md', 'docs/current-validation.json',
        'docs/ci-verification-20261107-r103.json', 'src/core/diagnostics.cpp', 'src/core/diagnostics.h',
        'tests/doctor_integration.py', 'docs/validation/2026-11-07/diagnostics-r103-source-audit.json',
        'docs/validation/2026-11-06/github-api-push-r102-native-evidence.json'}
    backup = root / '.cache/diagnostics-r103-originals'
    names.update(path.relative_to(backup).as_posix() for path in backup.rglob('*') if path.is_file())
    for folder in ('diagnostics-r103-windows', 'diagnostics-r103-correction', 'diagnostics-r103-recheck', 'diagnostics-r103-qualified'):
        names.update(path.relative_to(root).as_posix() for path in (root / 'docs/validation/2026-11-07' / folder).rglob('*')
                     if path.is_file() and path.suffix not in ('.zip', '.gz', '.png'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    label = 'r103-diagnostics'
    (root / ('.cache/' + label + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + label + '-stage.nul')).write_bytes(b''.join(path.encode('utf-8') + b'\0' for path in names))
    (root / ('.cache/stage-' + label + '.py')).write_bytes((root / '.cache/stage-r101-cancel.py').read_bytes().replace(b'r101-cancel', label.encode()))
    print(json.dumps({'explicitFiles': len(names), 'buildInputs': 213, 'planVersion': 'v0.103', 'nativeCIPending': True}))


if __name__ == '__main__':
    main()
