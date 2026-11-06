"""日期：2026-11-07；公开已核验的R103编译/核心、R102对照及R101失败子集，不改构建输入。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

SOURCE = 'cd92c43f301e5a60584b7896a450247855f0bdfd'
LABEL = 'r103-native-evidence'


# 日期：2026-11-07；原件和精确身份全部核对后才编制显式发布清单，保留原编码/换行和所有失败。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == SOURCE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    paths = [base / name for name in ('diagnostics-r103-macos-compiled/receipt.json',
        'diagnostics-r103-native-core/receipt.json', 'cancel-r102-glibc/verified-receipt.json',
        'cancel-r101-native-terminal/verified-subsets.json')]
    compiled, core, ubuntu, failure = [json.loads(path.read_text('utf-8')) for path in paths]
    assert compiled['sourceCommit'] == core['sourceCommit'] == SOURCE
    assert compiled['bothArchitecturesCompiledAndVerified'] and len(compiled['packages']) == 2
    assert core['passed'] and core['coreTargetsEach'] == 23 and core['originalQtReportsVerified'] == 88
    assert core['newDiagnosticMethodsVerified'] and core['explicitDarwinExpectedFailureCount'] == 2
    assert ubuntu['passed'] and ubuntu['originalCoreTargets'] == 23 and ubuntu['fixedRepeatedCancellationRows'] == 30
    assert not ubuntu['oldFailureReproduced'] and not ubuntu['intermittentFailureRootCauseProved']
    assert failure['run']['conclusion'] == 'failure' and failure['originalFailureRetained']
    assert failure['independentlyVerifiedProtocolReports'] == 188 and not failure['fullCoreAndNavigationQualified']
    assert len(failure['skippedAdditionalReports']) == 2 and all(not row['qualified'] for row in failure['skippedAdditionalReports'])
    output = paths[1].parent
    for source, name in (('.cache/r103-published-tree-verification.json', 'source-publication-verification.json'),
            ('.cache/r103-native-run.json', 'automatic-ci-observation.json'),
            ('.cache/r103-followup-inflight-long-observation.json', 'inflight-long-observation.json')):
        assert not (output / name).exists()
        shutil.copyfile(root / source, output / name)
    report_path = root / 'docs/ci-verification-20261107-r103.json'
    report = json.loads(report_path.read_text('utf-8'))
    assert len(report['buildInputs']) == 213
    for row in report['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    report.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=SOURCE,
        nativeCIRequested=True, nativeCIPending=True, nativeCoreQualified=True,
        nativeEvidence=proof(paths[1]), macOSCompilationEvidence=proof(paths[0]),
        sourcePublication=proof(output / 'source-publication-verification.json'),
        nativeRun={'runId': 42311369310, 'runUrl': compiled['run']['html_url'], 'reusedAutomaticPushRun': True},
        fullProtocolTerminalPending=True, nativeGuardOriginalJsonPending=True,
        fullNativeRegressionQualified=False, nativeSaveDialogVerified=False, entireR10Qualified=False,
        releaseQualified=False, deliveryComplete=False)
    save(report_path, report)
    r102_path = root / 'docs/ci-verification-20261107-r102.json'
    r102 = json.loads(r102_path.read_text('utf-8'))
    r102.update(independentUbuntuComparison=proof(paths[2]), independentUbuntuComparisonPending=False,
        oldFixtureFailureReproduced=False, intermittentFailureRootCauseProved=False)
    save(r102_path, r102)
    section = '## R103最新编译产物（2026-11-07）\n\n精确源码' + SOURCE + '已公开；[原生CI 42311369310](' + compiled['run']['html_url'] + ')的Apple Silicon/Intel编译、归档及上传成功。两份GUI/独立CLI的GitHub附件/内部tar摘要、源码、Mach-O架构、执行位及许可已逐件核验。\n\n| 架构 | 编译产物 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        section += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | ' + row['sha256'] + ' |\n'
    section += '\n[R103编译回执](validation/2026-11-07/diagnostics-r103-macos-compiled/receipt.json)。归档需要匹配Qt5/OpenSSL依赖，CI自行下载安装；含依赖预览仍为顶部R100。四runner各23核心/88份Qt原报告已验，含新增诊断核心及GUI方法，两条精确Darwin预期失败保留。[核心回执](validation/2026-11-07/diagnostics-r103-native-core/receipt.json)。完整协议、真实CLI诊断原生专项、保存选择器及整个R10仍待验。\n\n'
    update(root / 'docs/macOS独立预览包.md', lambda text: text.replace('## R102最新编译产物（2026-11-07）', section + '## R102编译记录（2026-11-07）', 1))
    note = '''

## R103公开编译/核心与独立Ubuntu对照收验（2026-11-07）

- [x] 精确cd92c43已公开并独立核对远端main及整树，复用自动CI42311369310。双Mac GUI/独立CLI编译产物摘要、源码、架构、执行位及许可已验，[下载入口](docs/macOS独立预览包.md)已更新；含依赖部署包仍为R100。
- [x] R103四runner各23核心/合计88份Qt原报告通过，含有界配置诊断、目录/端口失败、原子导出及GUI导出；原生/150%/200%取消共48行也已验，两条精确Darwin预期失败披露。[核心原件](docs/validation/2026-11-07/diagnostics-r103-native-core/receipt.json)。
- [x] R102独立Ubuntu对照完成：23核心、原生/高DPI及十轮30行取消通过，二进制和210份输入核验；旧夹具三次均成功，未复现旧间歇失败，不宣称证明根因。[独立回执](docs/validation/2026-11-07/cancel-r102-glibc/verified-receipt.json)。
- [x] R101原四平台终态failure及UI/导航失败保留；188份协议报告独立通过。Ubuntu两磁盘步骤因前序失败而skipped，明确未验。初收验器误要求缺失disk.json导致退出1也保留，修正后只登记真实执行子集。[终态子集回执](docs/validation/2026-11-07/cancel-r101-native-terminal/verified-subsets.json)。
- [ ] R102/R103完整协议、R103真实CLI诊断原生专项及保存选择器继续；R98 Windows/Ubuntu冻结86400秒仍运行，不以轮数代替时长。完整R6/GUI、编辑器/OS剪贴板及全部资源、公平性/安全GC、物理LAN/3×3、各平台长期、依赖源码独立重建、最低干净系统及正式签名公证未完成。deliveryComplete=false、releaseQualified=false，整体active。
'''
    # 日期：2026-11-07；当前摘要只声明已核验子项，历史观察保持原样。
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R103四原生各23核心/88份Qt报告及双Mac编译已验；R102独立Ubuntu对照完成，完整协议与长期交付继续。', text, count=1, flags=re.M)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R103本地诊断/原子导出213份构建输入见[本轮清单](docs/ci-verification-20261107-r103.json)；双Mac编译及四原生各23核心/88份Qt原报告已验，完整协议与真实CLI诊断专项继续。R102独立Ubuntu对照完成但未复现旧间歇失败；R101终态失败与188协议通过分开记录。含依赖包仍为R100。' + text[end:]
        text = text.replace('R103诊断/CLI通过；初轮23目标后定向复验2个QML，其余20个Qt程序SHA未变；R102原生取消及R100部署另验', 'R103云原生23核心及本机双工具链诊断子项通过；初轮UI夹具失败保留；R100部署另验', 1)
        text = text.replace('R102各23核心及原生/高DPI取消子集已验；R100含依赖部署已验；R103诊断待原生验证', 'R103原生23核心及诊断核心/GUI方法通过；R102独立Ubuntu23核心/十轮取消通过；R100部署另验', 1)
        text = text.replace('R102双架构GUI/CLI编译和核心取消已验；R100部署/APFS/完整补跑已验；R103待原生验证', 'R103双架构GUI/CLI编译及各23核心/诊断核心/GUI子项通过；R100部署/APFS/完整补跑另验', 1)
        text = text.replace('独立对照、完整交互、真实24h及完整故障矩阵', '完整CLI诊断/交互、真实24h及完整故障矩阵', 1)
        text = re.sub(r'^\| 运行中 \|.*$', '| 运行中 | R98 Windows/Ubuntu冻结CLI执行86400秒；R102/R103完整协议继续，R101原终态失败保留 | 必须取得实际终态，不以核心子集或轮数授予长期/完整回归资格 |', text, count=1, flags=re.M)
        return text.rstrip() + note
    update(root / '开发计划与进度.md', plan)
    update(root / 'docs/执行进度.md', lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'docs/构建验证摘要.md', lambda text: text.replace(text.split('\n\n', 2)[1], '更新日期：2026-11-07，计划v0.103。R103双Mac编译及四runner各23核心/88份Qt报告已验；新增诊断核心/GUI方法通过。R102独立Ubuntu对照完成但旧失败未复现，R101终态failure与188协议通过分别保持。完整协议/诊断CLI原生专项、保存选择器、86400秒及整体交付继续。', 1).rstrip() + note.replace('(docs/', '('))
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(observedUtc=report['observedUtc'], currentSourceCommit=SOURCE, currentGuiSourceCommitPending=False,
        macOSCompilationR103={'sourceCommit': SOURCE, 'packages': compiled['packages'], 'evidence': proof(paths[0]), 'dependenciesDeployed': False},
        nativeCoreR103={'sourceCommit': SOURCE, 'evidence': proof(paths[1]), 'coreTargetsEach': 23, 'qtReportsVerified': 88, 'newDiagnosticMethodsVerified': True, 'fullProtocolQualified': False},
        independentUbuntuR102=proof(paths[2]), originalR101TerminalFailureAndProtocolSubset=proof(paths[3]),
        currentSourceStage='R103 exact Mac compilation and four-runner core/diagnostic GUI methods verified; real native CLI doctor/protocol and entire delivery pending',
        releaseQualified=False, deliveryComplete=False)
    index['diagnosticsR103'].update(manifest=proof(report_path), nativeCoreEvidence=proof(paths[1]), macOSCompilationEvidence=proof(paths[0]), nativeCoreQualified=True, realNativeCliDoctorPending=True)
    index['cancelFixtureR102'].update(manifest=proof(r102_path), independentUbuntuComparison=proof(paths[2]), independentUbuntuComparisonPending=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == SOURCE
    state.update(nativeCoreR103=index['nativeCoreR103'], macOSCompilationR103=index['macOSCompilationR103'], independentUbuntuR102=proof(paths[2]), originalR101TerminalFailureAndProtocolSubset=proof(paths[3]), workingSourceStage=index['currentSourceStage'], goalStatus='active', releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    shutil.copyfile(Path(__file__), output / 'publication-preparation-driver.py')
    names = {'开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/macOS独立预览包.md', 'docs/current-validation.json', 'docs/ci-verification-20261107-r103.json', 'docs/ci-verification-20261107-r102.json', 'docs/validation/2026-11-06/github-api-push-r103-diagnostics-source.json'}
    for folder in ('diagnostics-r103-macos-compiled', 'diagnostics-r103-native-core', 'cancel-r102-glibc', 'cancel-r101-native-terminal'):
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*') if path.is_file() and path.suffix not in ('.zip', '.gz', '.png'))
    names = sorted(names)
    for name in names:
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes((root / '.cache/stage-r103-diagnostics.py').read_bytes().replace(b'r103-diagnostics', LABEL.encode()))
    print(json.dumps({'explicitFiles': len(names), 'newCoreRunnersVerified': 4, 'independentUbuntuVerified': True, 'r101OriginalFailurePreserved': True, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
