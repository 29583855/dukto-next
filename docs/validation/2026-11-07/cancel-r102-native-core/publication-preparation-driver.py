"""日期：2026-11-07；原件核验后公开R102双Mac编译及四平台核心取消子集，完整协议与交付仍待验。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

SOURCE = 'c1325b0b33ff4df116449c1e1c00d5b27a1a125c'


# 日期：2026-11-07；只在双编译和四平台原件齐全且严格通过后更新文档，不授予未完成的协议或发布资格。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == SOURCE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    compiled_path = root / 'docs/validation/2026-11-07/cancel-r102-macos-compiled/receipt.json'
    core_path = root / 'docs/validation/2026-11-07/cancel-r102-native-core/receipt.json'
    compiled = json.loads(compiled_path.read_text('utf-8'))
    core = json.loads(core_path.read_text('utf-8'))
    assert compiled['sourceCommit'] == core['sourceCommit'] == SOURCE
    assert compiled['bothArchitecturesCompiledAndVerified'] and len(compiled['packages']) == 2
    assert core['passed'] and core['coreTargetsEach'] == 23 and core['originalQtReportsVerified'] == 88
    assert core['explicitDarwinExpectedFailureCount'] == 2
    assert len(core['clipboardAndTextChecks']) == 4
    for row in core['clipboardAndTextChecks']:
        assert row['offscreenCancellationRows'] == 3 and row['nativeAndHighDpiCancellationRows'] == 9
    output = root / 'docs/validation/2026-11-07/cancel-r102-native-core'
    shutil.copyfile(root / '.cache/r102-published-tree-verification.json', output / 'source-publication-verification.json')
    shutil.copyfile(root / '.cache/r102-native-dispatch.json', output / 'automatic-ci-reuse.json')
    shutil.copyfile(root / '.cache/r102-inflight-long-observation.json', output / 'inflight-long-observation.json')
    shutil.copyfile(root / 'docs/validation/2026-11-07/cancel-r102-fixture/independent-comparison-inflight.json',
                    output / 'independent-comparison-inflight.json')
    report_path = root / 'docs/ci-verification-20261107-r102.json'
    report = json.loads(report_path.read_text('utf-8'))
    report.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=SOURCE,
        sourcePublication=proof(output / 'source-publication-verification.json'), nativeCIRequested=True,
        nativeCIPending=True, nativeCoreAndCancellationSubsetQualified=True,
        nativeEvidence=proof(core_path), macOSCompilationEvidence=proof(compiled_path),
        nativeRun={'runId': 42304553041, 'runUrl': compiled['run']['html_url'], 'reusedAutomaticPushRun': True},
        fullProtocolTerminalPending=True, nativeGuardOriginalJsonPending=True,
        fullNativeRegressionQualified=False, wholeF18Qualified=False,
        releaseQualified=False, deliveryComplete=False)
    save(report_path, report)
    section = '''## R102最新编译产物（2026-11-07）

精确源码`c1325b0b33ff4df116449c1e1c00d5b27a1a125c`已公开；[原生CI 42304553041](https://github.com/29583855/dukto-next/actions/runs/42304553041)的Apple Silicon/Intel原生编译、归档及附件上传均成功。两份GUI/独立CLI已取回，官方附件摘要、内部tar摘要、源码、Mach-O架构、执行权限及许可逐件核验。

| 架构 | 编译产物 | 内部tar.gz SHA-256 |
| --- | --- | --- |
'''
    for row in compiled['packages']:
        section += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['sha256'] + '` |\n'
    section += '''
[R102编译原件回执](validation/2026-11-07/cancel-r102-macos-compiled/receipt.json)。归档需要匹配Qt5/OpenSSL依赖；CI自行下载安装。含依赖开发预览包继续使用顶部R100入口，未更换其源码身份。

R102四runner各23核心、88份Qt原报告及48行取消回归已核验，含每平台原生/150%/200%场景、清理后同控制器双向内容核验；两条Darwin预期失败明确保留。[核心与取消子集回执](validation/2026-11-07/cancel-r102-native-core/receipt.json)。完整协议和原生槽负例总JSON仍待最终附件；不授完整F18、整个GUI或正式发布资格。R101原生发送取消失败继续保留，独立Ubuntu旧夹具三次成功复查也不覆盖该失败。

'''
    update(root / 'docs/macOS独立预览包.md', lambda text: text.replace('## R101最新编译产物（2026-11-07）',
        section + '## R101编译及原始失败记录（2026-11-07）', 1))
    note = '''

## R102四平台核心取消与双Mac编译收验（2026-11-07）

- [x] 精确提交c1325b0已公开并独立核对远端树；复用自动CI42304553041，未重复派发。双Mac GUI/独立CLI真实编译成功，归档源码、摘要、架构、执行位及许可已验，[下载入口](docs/macOS独立预览包.md)已更新；含依赖部署包仍为R100。
- [x] 四runner各23核心/合计88份Qt原报告严格通过；每平台3行核心offscreen取消加原生/150%/200%的9行，合计48行，验证发送/部分包头/部分正文取消、临时清理、额度归还及同控制器后续双向内容。两条精确Darwin预期失败明确披露。[原件回执](docs/validation/2026-11-07/cancel-r102-native-core/receipt.json)。
- [x] R101原四平台发送取消失败保持原报告。本轮仅调整独立慢端读取时序和排空窗口，产品传输核心未改，取消及EOF各5000ms未变。独立Ubuntu旧夹具三次复查均通过，不能据此认定间歇性失败根因全部消除；新夹具完整独立对照仍执行。
- [ ] R102完整协议终态及原生槽负例总JSON须取得最终附件后收验，完整F18/GUI、编辑器/OS剪贴板及全部资源预算、公平性/安全GC、物理LAN/3×3、各平台86400秒、依赖源码独立重建、最低干净系统及正式签名公证仍未完成。整体保持active，deliveryComplete=false、releaseQualified=false。
'''
    # 日期：2026-11-07；只更新当前事实，历史失败和之前每个包的精确身份保持原记录。
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R102四平台各23核心/88份Qt原报告及48行取消子集通过；双Mac原生编译产物已验，完整协议、独立Ubuntu对照及长期交付继续。', text, count=1, flags=re.M)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R102精确c1325b0仅改独立取消测试夹具，210份构建输入见[本轮清单](docs/ci-verification-20261107-r102.json)。四平台各23核心/88份Qt原报告及48行取消子集已验，双Mac GUI/CLI编译归档已取回。原R101失败与R100完整补跑分别保留；完整协议和交付继续。' + text[end:]
        text = text.replace('R101双架构GUI/CLI编译归档已验；R100含依赖部署/APFS子集及完整补跑已验',
            'R102双架构GUI/CLI编译及各23核心/取消子集已验；R100含依赖部署/APFS/完整补跑已验', 1)
        text = text.replace('R101发送取消夹具失败复查、完整交互/选择器和正式分发',
            '完整协议/GUI交互/选择器、最低干净系统及正式分发', 1)
        text = text.replace('R101原生取消、完整交互、真实24h终态和完整故障矩阵',
            'R102原生取消子集已验；独立对照、完整交互、真实24h及完整故障矩阵继续', 1)
        text = re.sub(r'^\| 运行中 \|.*$',
            '| 运行中 | R98 Windows/Ubuntu冻结CLI执行86400秒；R102完整协议和独立Ubuntu对照继续，R101原失败保留 | 必须取得实际终态，不以核心子集或轮数转授长期/完整回归资格 |',
            text, count=1, flags=re.M)
        text = text.replace('双Windows原生/高DPI实际取消及同实例双向后续内容核验通过；Mac/Linux与完整三平台待验，原版失败保留',
            '四原生核心及原生/高DPI取消48行与同实例双向内容核验通过；完整故障/GUI矩阵仍待，原版失败保留', 1)
        return text.rstrip() + note
    update(root / '开发计划与进度.md', plan)
    local_note = note.replace('(docs/', '(')
    update(root / 'docs/执行进度.md', lambda text: text.rstrip() + local_note)
    update(root / 'docs/构建验证摘要.md', lambda text: text.replace(text.split('\n\n', 2)[1],
        '更新日期：2026-11-07，计划v0.102。精确c1325b0双Mac编译产物已验；四runner各23核心/88份Qt原报告和48行取消子集通过，两条Darwin预期失败保留。完整协议、独立Ubuntu对照、86400秒及整体交付继续。', 1).rstrip() + local_note)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(observedUtc=report['observedUtc'], currentSourceCommit=SOURCE, currentGuiSourceCommitPending=False,
        macOSCompilationR102={'sourceCommit': SOURCE, 'packages': compiled['packages'], 'evidence': proof(compiled_path),
                             'dependenciesDeployed': False},
        nativeCoreR102={'sourceCommit': SOURCE, 'evidence': proof(core_path), 'coreTargetsEach': 23,
                       'qtReportsVerified': 88, 'cancellationRows': 48, 'explicitDarwinExpectedFailures': 2,
                       'fullProtocolQualified': False, 'nativeGuardOriginalJsonPending': True},
        currentSourceStage='R102 exact Mac compilation and four-runner 23 core / 88 Qt reports / 48 cancellation rows verified; full native protocol, independent Ubuntu comparison and delivery pending',
        releaseQualified=False, deliveryComplete=False)
    index['cancelFixtureR102'].update(manifest=proof(report_path), nativeEvidence=proof(core_path),
                                     nativeCoreAndCancellationSubsetQualified=True)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == SOURCE
    state.update(nativeCoreR102=index['nativeCoreR102'], macOSCompilationR102=index['macOSCompilationR102'],
                 workingSourceStage=index['currentSourceStage'], goalStatus='active',
                 releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    shutil.copyfile(Path(__file__), output / 'publication-preparation-driver.py')
    names = {'开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/macOS独立预览包.md',
             'docs/current-validation.json', 'docs/ci-verification-20261107-r102.json',
             'docs/validation/2026-11-06/github-api-push-r102-fixture-source.json'}
    for folder in ('cancel-r102-macos-compiled', 'cancel-r102-native-core'):
        names.update(p.relative_to(root).as_posix() for p in (root / 'docs/validation/2026-11-07' / folder).rglob('*')
                     if p.is_file() and p.suffix not in ('.zip', '.gz', '.png'))
    names = sorted(names)
    for name in names:
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    label = 'r102-native-evidence'
    (root / ('.cache/' + label + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + label + '-stage.nul')).write_bytes(b''.join(p.encode('utf-8') + b'\0' for p in names))
    (root / ('.cache/stage-' + label + '.py')).write_bytes(
        (root / '.cache/stage-r101-cancel.py').read_bytes().replace(b'r101-cancel', label.encode()))
    print(json.dumps({'explicitFiles': len(names), 'coreTargetsEach': 23, 'qtReports': 88,
                      'cancellationRows': 48, 'macArchitecturesCompiled': 2, 'wholeDeliveryQualified': False}))


if __name__ == '__main__':
    main()
