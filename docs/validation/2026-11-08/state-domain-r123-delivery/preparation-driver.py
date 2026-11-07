"""日期：2026-11-08；按真实四平台关联专项与双Mac包更新下载和进度，原失败继续保留。"""
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


# 日期：2026-11-08；当前收验器元数据允许同步，原产品报告的SHA已由对应独立收验器核对。
def mirror(folder):
    for path in (REPO / folder).rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.png', '.csv']:
            target = ROOT / path.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


# 日期：2026-11-08；从已下载官方原件和实际截图审核更新可用包，源码身份和未完成范围分别保留。
def main():
    target = ROOT / '.cache/r123-delivery-prepared.json'
    assert not target.exists()
    names = {name: BASE + 'state-domain-r123-' + suffix for name, suffix in
             [('native', 'native'), ('compiled', 'macos-compiled'), ('package', 'macos-package'), ('core', 'full-native-core')]}
    reports = {key: json.loads((REPO / name / 'receipt.json').read_bytes()) for key, name in names.items()}
    source = json.loads((ROOT / '.cache/r123-source-publication.json').read_bytes())['sourceCommit']
    assert all(report['sourceCommit'] == source for report in reports.values())
    native, compiled, package, core = [reports[key] for key in ['native', 'compiled', 'package', 'core']]
    assert native['allFourNativeDomainFoundationQualified'] and native['run']['conclusion'] == 'success'
    assert all(row['rowsPassed'] == 12 and row['warnings'] == row['skipped'] == 0 for row in native['records'])
    assert compiled['bothArchitecturesCompiledAndVerified']
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed'] and package['run']['conclusion'] == 'success'
    core_count = sum(row['qualified'] for row in core['records'])
    assert all(row.get('ctestTargetsPassed') == 32 and row.get('qtXmlReportsVerified') == 31
               for row in core['records'] if row['qualified'])
    old_name = BASE + 'state-budget-r122-native-terminal'
    old = json.loads((REPO / old_name / 'receipt.json').read_bytes())
    old_count = sum(row['qualified'] for row in old['records'])
    arm = json.loads((REPO / old_name / 'macos-15/verified-passed-subsets.json').read_bytes())
    assert arm['originalJobConclusion'] == 'failure' and len(arm['passedProtocolReports']) == 46
    assert len(arm['failedProtocolReports']) == 1 and not arm['completeNativeProtocolQualified']
    folders = list(names.values()) + [old_name]
    glibc_path = ROOT / '.cache/r123-glibc/receipt.json'
    glibc = json.loads(glibc_path.read_bytes()) if glibc_path.exists() else None
    execution = REPO / (BASE + 'state-domain-r123-delivery')
    execution.mkdir(exist_ok=False)
    if glibc and glibc.get('passed'):
        assert glibc['rowsPassed'] == 12 and glibc['allInstalledSourceInputsUnchanged']
        actual = json.loads((glibc_path.parent / 'installed-source.json').read_bytes())
        index = json.loads((ROOT / 'docs/ci-verification-20261108-r123.json').read_bytes())
        for row in index['qualificationInputs']:
            assert actual['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}, row['path']
        for path in glibc_path.parent.rglob('*'):
            if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.sha256']:
                to = execution / 'glibc-qualified' / path.relative_to(glibc_path.parent)
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, to)
        shutil.copyfile(ROOT / '.cache/validate-r123-glibc.py', execution / 'validate-r123-glibc.py')
    snapshot = json.loads((ROOT / '.cache/r123-source-snapshot-test.json').read_bytes())
    assert snapshot['passed']
    shutil.copyfile(ROOT / '.cache/r123-source-snapshot-test.json', execution / 'source-snapshot-test.json')
    shutil.copyfile(Path(__file__), execution / 'preparation-driver.py')
    native_folder = REPO / names['native']
    shutil.copyfile(ROOT / '.cache/collect-r123-domain-native-first.py', native_folder / 'first-collector.py')
    (native_folder / 'first-collector-failure.json').write_text(json.dumps({
        'collectorPassed': False, 'reason': 'collector used previous state-budget artifact prefix for state-domain workflow',
        'actualJobsFailedByThisCollector': False, 'productReportsModified': False}, indent=2) + '\n', 'utf-8')
    old_folder = REPO / old_name / 'macos-15'
    shutil.copyfile(ROOT / '.cache/verify-r122-arm-failed-subsets-first.py', old_folder / 'first-failed-subsets-verifier.py')
    (old_folder / 'first-failed-subsets-collection-failure.json').write_text(json.dumps({
        'collectorPassed': False, 'reason': 'collector required dictionary envelope; original protocol reports also include lists',
        'productReportsModified': False}, indent=2) + '\n', 'utf-8')
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'allFourNativeDomainFoundationQualified': True, 'domainMethodsEach': 12,
              'nativeCoreJobsVerified': core_count, 'fullNativeProtocolQualified': False,
              'bothMacosCompiled': True, 'bothMacosPackagesQualified': True, 'screenshotsViewed': True,
              'independentGlibcQualified': bool(glibc and glibc.get('passed')),
              'r122ProtocolJobsQualified': old_count, 'r122ArmProtocolFailed': True,
              'productionRootsIntegrated': False, 'globalQuotaEnforced': False, 'automaticGcImplemented': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (execution / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    folders.append(execution.relative_to(REPO).as_posix())
    summary = (f'R123精确{source[:8]}四原生目录关联各12条通过，完整核心已验{core_count}/4；'
               '双Mac GUI/独立CLI和含Qt5/OpenSSL包、迁移及五项业务和四截图已验，下载更新至R123。'
               + ('独立Ubuntu12条通过。' if record['independentGlibcQualified'] else '独立Ubuntu仍在新目录编译。')
               + 'R122 ARM完整协议保留暂停后超时失败。生产总预算、自动GC及完整交付继续。')
    section = f'''## R123四原生关联与双Mac交付（2026-11-08）

- [x] 精确{source}已非强制公开；[四原生关联专项]({native['run']['html_url']})全部终态success，每平台12条、零跳过/警告。逐Git检出规则核对全部执行输入和前后程序身份，不以单平台推断其他平台。[原件](docs/validation/2026-11-08/state-domain-r123-native/receipt.json)。
- [x] 双Mac GUI/独立CLI实际编译成功，含Qt5/OpenSSL部署包终态success；官方ZIP/内部tar、源码/载荷/链接/架构/执行位、中文空格目录/系统PATH迁移、每架构五业务、Cocoa/高DPI及四原生截图已验。[下载与摘要](docs/macOS独立预览包.md)。仍为开发adhoc签名，正式签名/公证及最低干净系统继续。
- [{'x' if core_count == 4 else ' '}] R123四平台各32完整核心/31份Qt XML已收验{core_count}/4，两Mac精确Darwin端口XFAIL保留；完整协议按各原作业终态另外收验。[核心回执](docs/validation/2026-11-08/state-domain-r123-full-native-core/receipt.json)。
- [x] R122 ARM原作业完整协议failure已保留：47份原件中46份通过；暂停6秒后非法文本预期内容错误6，实际网络超时3/stage=transfer。完整原报告、源码/摘要和失败保持，根因未证实；缓冲有效正文及静默/部分停顿超时通过，不以其他子项覆盖此失败。[原件](docs/validation/2026-11-08/state-budget-r122-native-terminal/macos-15/verified-passed-subsets.json)。
- [x] 源码快照13项通过；收验器沿用旧附件前缀、误要求所有协议报告为字典的两次失败及修正原件保持，没有重跑产品测试。R98 Ubuntu真实24h业务/资源子项与glib依赖漂移导致的原驱动失败继续分开登记。
- [ ] 生产GUI/CLI/服务器根映射、实际分配/跨卷准入及SQLite/正文总预算、孤立登记维护和自动GC、完整R6/原生选择器、物理LAN/3×3、当前三平台24h、依赖源码重建、最低干净系统与正式发布继续；整体active。

'''
    if record['independentGlibcQualified']:
        section = section.replace('- [ ] 生产GUI', '- [x] 独立Ubuntu新目录实际构建与12条专项通过，所有安装源码、279资格输入、C++14及程序前后摘要核对；不是该环境完整核心/GUI验收。\n- [ ] 生产GUI', 1)
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace('## R123持久预算域与多根关联', section + '## R123持久预算域与多根关联', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace('## R123持久预算域与多根关联', section.replace('](docs/', '](') + '## R123持久预算域与多根关联', 1))
    update('README.md', lambda text: text.replace('R123持久预算域/多根关联底层', summary + ' [Mac下载](docs/macOS独立预览包.md)。\n\nR123持久预算域/多根关联底层', 1))
    preview = '## R123含依赖开发预览\n\n' + f'精确源码`{source}`；[逐层回执](validation/2026-11-08/state-domain-r123-macos-package/receipt.json)。开发adhoc签名，正式签名/公证和最低干净系统继续。\n\n'
    preview += '| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
    for row in package['records']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['artifactSha256']} | {row['packageSha256']} |\n"
    preview += '\n本机副本：dist/macos-preview-20261108-r123-state-domain/。解压和独立CLI用法见下文。\n\n'
    preview += '## R123原生编译归档\n\n[回执](validation/2026-11-08/state-domain-r123-macos-compiled/receipt.json)。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['sha256']} |\n"
    preview += '\n'
    update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + summary + '\n\n' + preview, 1)
           .replace('## R122含依赖开发预览', '## R122含依赖开发预览（历史）', 1))
    for name in ['docs/ci-verification-20261108-r122.json', 'docs/ci-verification-20261108-r123.json']:
        path = REPO / name
        value = json.loads(path.read_bytes())
        value['observedUtc'] = record['observedUtc']
        refs = {row['path'] for row in value['receipts']}
        if 'r123' in name:
            value.update(sourceCommit=source, allFourNativeDomainFoundationQualified=True,
                         nativeDomainRun=native['run'], nativeCoreRun=core['run'], nativeCoreJobsVerified=core_count,
                         bothMacosCompiled=True, bothMacosPackagesQualified=True, macosPackageRun=package['run'],
                         macosScreenshotsViewed=True, independentGlibcQualified=record['independentGlibcQualified'],
                         independentGlibcQualificationPending=not record['independentGlibcQualified'], sourceSnapshotTestsPassed=True)
            refs |= {folder + '/receipt.json' for folder in folders if 'r123' in folder}
        else:
            value.update(nativeTerminalJobsVerified=old_count, nativeRun=old['run'],
                         fullNativeProtocolQualified=old['allFourNativeProtocolJobsVerified'], r122ArmProtocolFailed=True)
        value['receipts'] = [{'path': ref, 'sha256': hashlib.sha256((REPO / ref).read_bytes()).hexdigest()} for ref in sorted(refs)]
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        shutil.copyfile(path, ROOT / name)
    for folder in folders:
        mirror(folder)
    for name in ['docs/ci-verification-20261108-r122.json', 'docs/ci-verification-20261108-r123.json']:
        for row in json.loads((ROOT / name).read_bytes())['receipts']:
            assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
    record['evidenceFolders'] = folders
    target.write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
