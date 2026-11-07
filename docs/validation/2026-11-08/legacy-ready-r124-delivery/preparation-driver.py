"""日期：2026-11-08；按原生实际结果准备R124下载及进度，不以重复通过推定间歇失败根因。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；原产品原件仅同步字节，动态汇总冻结后再刷新所有引用摘要。
def mirror(folder):
    for path in (REPO / folder).rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.png', '.csv']:
            target = ROOT / path.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


# 日期：2026-11-08；同时要求两Mac真实编译/含依赖包/迁移及截图，不用任一平台替另一平台授予资格。
def main():
    target = ROOT / '.cache/r124-delivery-prepared.json'
    assert not target.exists()
    source = json.loads((ROOT / '.cache/r124-source-publication.json').read_bytes())['sourceCommit']
    names = {key: BASE + 'legacy-ready-r124-' + suffix for key, suffix in
             [('native', 'native'), ('core', 'full-native-core'), ('compiled', 'macos-compiled'), ('package', 'macos-package')]}
    reports = {key: json.loads((REPO / folder / 'receipt.json').read_bytes()) for key, folder in names.items()}
    assert all(value['sourceCommit'] == source for value in reports.values())
    native, core, compiled, package = [reports[key] for key in ['native', 'core', 'compiled', 'package']]
    assert native['allFourNativeReadyCasesQualified'] and native['run']['conclusion'] == 'success'
    assert all(row['casesPassed'] == 12 for row in native['records'])
    baseline = [row for row in native['records'] if row['runner'].startswith('macos-')]
    assert len(baseline) == 2 and all(row['baselineAllCasesPassed'] for row in baseline)
    assert compiled['bothArchitecturesCompiledAndVerified']
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed'] and package['run']['conclusion'] == 'success'
    core_count = sum(row['qualified'] for row in core['records'])
    assert core_count == 4
    assert all(row['ctestTargetsPassed'] == 32 and row['qtXmlReportsVerified'] == 31 for row in core['records'] if row['qualified'])
    index = json.loads((ROOT / 'docs/ci-verification-20261108-r124.json').read_bytes())
    for row in index['qualificationInputs']:
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
        assert (ROOT / row['path']).read_bytes() == (REPO / row['path']).read_bytes()
    glibc = json.loads((ROOT / '.cache/r124-glibc/receipt.json').read_bytes())
    assert glibc['passed'] and glibc['casesPassed'] == 12 and glibc['allInstalledSourceInputsUnchanged']
    installed = json.loads((ROOT / '.cache/r124-glibc/installed-source.json').read_bytes())
    for row in index['qualificationInputs']:
        assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}, row['path']
    execution = REPO / (BASE + 'legacy-ready-r124-delivery')
    execution.mkdir(exist_ok=False)
    for path in (ROOT / '.cache/r124-glibc').rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.sha256']:
            destination = execution / 'glibc-qualified' / path.relative_to(ROOT / '.cache/r124-glibc')
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    shutil.copyfile(ROOT / '.cache/validate-r124-glibc.py', execution / 'validate-glibc.py')
    shutil.copyfile(ROOT / '.cache/r124-qt-reference-review.json', execution / 'qt-reference-review.json')
    shutil.copyfile(Path(__file__), execution / 'preparation-driver.py')
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'allFourNativeReadyCasesQualified': True, 'readyCasesEach': 12,
              'bothMacBaselineCasesEach': 12, 'bothMacBaselinesPassed': True,
              'historicalFailureReproducedByTheseBaselines': False, 'rootCauseProven': False,
              'nativeCoreJobsVerified': core_count, 'fullNativeProtocolQualified': False,
              'bothMacosCompiled': True, 'bothMacosPackagesQualified': True, 'screenshotsViewed': True,
              'independentGlibcQualified': True, 'independentGlibcCases': 12,
              'productionRootsIntegrated': False, 'globalQuotaEnforced': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (execution / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    folders = list(names.values()) + [execution.relative_to(REPO).as_posix(),
               BASE + 'state-budget-r122-native-terminal', BASE + 'state-domain-r123-native-terminal',
               BASE + 'legacy-ready-r124-native-terminal']
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    summary = (f'R124精确{source[:8]}四原生各三轮12场景通过，完整核心已验{core_count}/4；'
               '两Mac旧版对照也各12条通过，历史间歇失败未复现、根因未证明。双Mac GUI/CLI含依赖包及迁移运行已验，下载更新R124。'
               '独立Ubuntu12条通过；生产总预算、自动GC及完整交付继续。')
    section = f'''## R124四原生暂停恢复与双Mac交付（2026-11-08）

- [x] 精确{source}已公开；[四原生专项]({native['run']['html_url']})全部终态success，各三轮12场景通过。原5秒期限、6秒暂停、非法文本错误及静默/半帧断言保持；源码/夹具/程序前后身份与精确Git检出规则逐项核对。[原件](docs/validation/2026-11-08/legacy-ready-r124-native/receipt.json)。
- [x] 两Mac同环境旧版对照也各12条全部通过，未复现R122 ARM历史间歇失败；该失败仍保留，底层根因不授予已解决资格。新增最多1毫秒最终就绪等待作为防御性修正。[行为和边界](docs/R6暂停恢复与超时.md)。
- [x] 双Windows各32完整CTest/31份Qt XML；原核心279输入与程序保持，最终更正一条原因注释后重编译CLI，并冻结281输入、各12场景通过。241维护文件审计、C++14/格式、原编码/BOM/LF及源码快照13项通过。
- [{'x' if core_count == 4 else ' '}] 四原生各32完整核心/31份Qt XML当前已验{core_count}/4，精确Darwin端口XFAIL继续保留；完整协议终态另外收验。[核心原件](docs/validation/2026-11-08/legacy-ready-r124-full-native-core/receipt.json)。
- [x] Apple Silicon/Intel真实GUI与独立CLI编译成功，含Qt5/OpenSSL包终态success；官方ZIP/内部tar、源码/载荷/链接/架构/执行位、系统PATH及中文空格目录迁移、每架构五项业务、Cocoa/高DPI和四截图核验。[下载与摘要](docs/macOS独立预览包.md)。开发adhoc签名，正式签名/公证及最低干净系统继续。
- [x] 独立Ubuntu新目录真实编译、三轮12场景通过；全部安装源码、281资格输入、C++14及执行程序前后SHA一致。完整GUI/核心不由此转授。
- [x] R122原完整运行已终态failure：Windows51项、Ubuntu/Intel各47项通过，ARM原47项中46通过/1暂停后超时失败保留；没有用其他平台通过覆盖该失败。\n- [ ] 当前完整协议、生产根迁移与可调整预算、SQLite/正文/跨卷总预算及自动GC、完整R6/原生选择器、物理LAN/3×3、当前各平台24h、最低干净系统、依赖源码重建及正式分发继续；整体active。

'''
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           re.sub(r'## R124接收暂停恢复与原超时.*?(?=## R123四原生关联与双Mac交付)', lambda _: section, text, count=1, flags=re.S), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: re.sub(r'## R124接收暂停恢复与原超时.*?(?=## R123四原生关联与双Mac交付)', lambda _: section.replace('](docs/', ']('), text, count=1, flags=re.S))
    update('README.md', lambda text: re.sub(r'R124接收超时前增加最终就绪等待候选；.*?\n\n', summary + ' [本轮原件](docs/ci-verification-20261108-r124.json)。\n\n', text, count=1, flags=re.S))
    update('docs/R6暂停恢复与超时.md', lambda text: text + '\n本轮四原生各12场景全部通过，两Mac旧版对照也各12场景通过；没有复现历史间歇失败，因此不宣称根因已修复。原报告与独立断言复核见[专项收验](validation/2026-11-08/legacy-ready-r124-native/receipt.json)。\n')
    preview = f'## R124含依赖开发预览\n\n精确源码`{source}`；[逐层回执](validation/2026-11-08/legacy-ready-r124-macos-package/receipt.json)。开发adhoc签名，正式签名/公证和最低干净系统继续。\n\n'
    preview += '| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
    for row in package['records']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['artifactSha256']} | {row['packageSha256']} |\n"
    preview += '\n本机副本：dist/macos-preview-20261108-r124-legacy-ready/。解压和独立CLI用法见下文。\n\n'
    preview += '## R124原生编译归档\n\n[回执](validation/2026-11-08/legacy-ready-r124-macos-compiled/receipt.json)。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['sha256']} |\n"
    preview += '\n'
    update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + summary + '\n\n' + preview, 1).replace('## R123含依赖开发预览', '## R123含依赖开发预览（历史）', 1))
    for folder in folders:
        mirror(folder)
    for version in ['r122', 'r123', 'r124']:
        path = ROOT / ('docs/ci-verification-20261108-' + version + '.json')
        value = json.loads(path.read_bytes())
        refs = {row['path'] for row in value['receipts']}
        if version == 'r124':
            value.update(sourceCommit=source, allFourNativeReadyCasesQualified=True, nativeReadyRun=native['run'],
                         nativeCoreRun=core['run'], nativeCoreJobsVerified=core_count,
                         bothMacBaselinesPassed=True, historicalFailureReproducedByTheseBaselines=False,
                         bothMacosCompiled=True, bothMacosPackagesQualified=True, macosPackageRun=package['run'],
                         macosScreenshotsViewed=True, independentGlibcQualified=True,
                         independentGlibcQualificationPending=False)
            refs |= {folder + '/receipt.json' for folder in folders if 'r124' in folder}
        else:
            folder = BASE + ('state-budget-r122-native-terminal' if version == 'r122' else 'state-domain-r123-native-terminal')
            terminal = json.loads((ROOT / folder / 'receipt.json').read_bytes())
            value.update(nativeTerminalJobsVerified=sum(row['qualified'] for row in terminal['records']),
                         nativeRun=terminal['run'], fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'])
        value['observedUtc'] = record['observedUtc']
        value['receipts'] = [{'path': ref, 'sha256': hashlib.sha256((ROOT / ref).read_bytes()).hexdigest()} for ref in sorted(refs)]
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        shutil.copyfile(path, REPO / path.relative_to(ROOT))
    record['evidenceFolders'] = folders
    target.write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
