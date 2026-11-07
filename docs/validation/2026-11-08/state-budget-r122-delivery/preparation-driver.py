"""日期：2026-11-08；双Mac实际包及四原生账本通过后更新可下载结果，完整项目仍按原边界执行。"""
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


# 日期：2026-11-08；复制已验原件到工作区，动态汇总允许更新，历史原件不重新生成。
def copy_folder(name):
    for path in (REPO / name).rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.log', '.xml', '.txt', '.sha256', '.py', '.png']:
            target = ROOT / path.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


# 日期：2026-11-08；只根据真实终态与已查看截图更新下载入口，未完成协议及业务预算保持未完成。
def main():
    target = ROOT / '.cache/r122-delivery-prepared.json'
    assert not target.exists()
    names = {key: BASE + 'state-budget-r122-' + suffix for key, suffix in
             [('native', 'native'), ('compiled', 'macos-compiled'), ('package', 'macos-package'), ('core', 'full-native-core')]}
    reports = {key: json.loads((REPO / name / 'receipt.json').read_bytes()) for key, name in names.items()}
    source = json.loads((ROOT / '.cache/r122-source-publication.json').read_bytes())['sourceCommit']
    assert all(value['sourceCommit'] == source for value in reports.values())
    native, compiled, package, core = [reports[key] for key in ['native', 'compiled', 'package', 'core']]
    assert native['allFourNativeBudgetFoundationQualified'] and native['run']['conclusion'] == 'success'
    assert compiled['bothArchitecturesCompiledAndVerified']
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed'] and package['run']['conclusion'] == 'success'
    assert all(row['rowsPassed'] == 23 for row in native['records'])
    windows_record, = [row for row in native['records'] if row['runner'] == 'windows-2022']
    assert len(windows_record['checkoutLineEndingConversions']) == 257
    core_count = sum(row['qualified'] for row in core['records'])
    old_name = BASE + 'state-inventory-r121-native-terminal'
    old_terminal = json.loads((REPO / old_name / 'receipt.json').read_bytes())
    assert old_terminal['allFourNativeProtocolJobsVerified'] and old_terminal['run']['conclusion'] == 'success'
    folders = list(names.values()) + [old_name]
    execution = REPO / (BASE + 'state-budget-r122-delivery')
    execution.mkdir(exist_ok=False)
    glibc_path = ROOT / '.cache/r122-glibc/receipt.json'
    glibc = json.loads(glibc_path.read_bytes()) if glibc_path.exists() else None
    if glibc and glibc.get('passed'):
        assert glibc['rowsPassed'] == 23 and glibc['allInstalledSourceInputsUnchanged']
        installed = json.loads((glibc_path.parent / 'installed-source.json').read_bytes())
        index = json.loads((ROOT / 'docs/ci-verification-20261108-r122.json').read_bytes())
        for row in index['qualificationInputs']:
            assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}, row['path']
        for path in glibc_path.parent.rglob('*'):
            if path.is_file() and path.suffix in ['.json', '.log', '.xml', '.txt', '.sha256']:
                to = execution / 'glibc-qualified' / path.relative_to(glibc_path.parent)
                to.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, to)
        shutil.copyfile(ROOT / '.cache/validate-r122-glibc.py', execution / 'validate-r122-glibc.py')
    shutil.copyfile(ROOT / '.cache/r122-source-snapshot-test.json', execution / 'source-snapshot-test.json')
    shutil.copyfile(ROOT / '.cache/r122-publication-source-audit.json', execution / 'source-audit.json')
    shutil.copyfile(Path(__file__), execution / 'preparation-driver.py')
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'allFourNativeBudgetFoundationQualified': True, 'budgetRowsEach': 23,
             'completeNativeCoreJobsVerified': core_count, 'fullNativeProtocolQualified': False,
             'bothMacosCompiled': True, 'bothMacosPackagesQualified': True, 'screenshotsViewed': True,
             'independentGlibcQualified': bool(glibc and glibc.get('passed')),
             'allR121NativeProtocolQualified': True, 'sourceSnapshotTestsPassed': True,
             'windowsNativeCheckoutHas257ExactCrlfConversions': True,
             'runtimeOwnershipRegistryImplemented': False, 'globalQuotaEnforced': False,
             'automaticGcImplemented': False, 'deliveryComplete': False, 'releaseQualified': False}
    (execution / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    folders.append(execution.relative_to(REPO).as_posix())
    summary = (f'R122精确{source[:8]}的四原生账本专项各23条通过；完整核心已验{core_count}/4。'
               '双Mac GUI/独立CLI及含Qt5/OpenSSL包、迁移运行、五项业务与四截图已验，下载已更新。'
               + ('独立Ubuntu干净构建及23条专项已验。' if value['independentGlibcQualified'] else '独立Ubuntu仍在新目录构建。')
               + 'R121四原生完整协议全部通过。生产总预算、自动GC与完整交付仍未完成。')
    section = f"""## R122四原生账本与双Mac交付（2026-11-08）

- [x] 精确提交{source}已非强制公开，274份资格输入逐blob核对；[四原生账本专项]({native['run']['html_url']})全部终态success，各23条、零跳过/警告，真实进程、线程、退出保留和日志恢复均通过。[原件](docs/validation/2026-11-08/state-budget-r122-native/receipt.json)。
- [x] 原收验器要求Windows工作树与Git原字节相同而失败，真实测试job成功。逐件证明257个UTF-8文本文件仅由Git默认LF转CRLF；既有CRLF和固定vendor原件保持。按精确Git检出规则核对268份执行输入，源/二进制前后稳定，原失败收验器与全部摘要保留；未重跑产品测试。
- [x] 双Mac实际GUI/独立CLI编译成功，含Qt5/OpenSSL包全部终态success；官方ZIP/内部tar、精确源码、载荷/链接/架构/执行位、系统PATH迁移、每架构五项业务、Cocoa/高DPI及四截图核验。[下载与摘要](docs/macOS独立预览包.md)更新至R122。开发adhoc签名，正式签名/公证及最低干净系统仍继续。
- [{'x' if core_count == 4 else ' '}] R122四平台各31完整核心/30份Qt XML已收验{core_count}/4；两Mac精确Darwin端口XFAIL继续披露，完整协议终态另行收验。[核心回执](docs/validation/2026-11-08/state-budget-r122-full-native-core/receipt.json)。
- [x] R121完整原生运行全部终态success：Windows51条，三个POSIX各47条协议原件已核验；R122生产写入尚未接入预算，不据此授予Q01–Q08整体完成。
- [ ] 全根归属/真实占用对账、SQLite/原子替换/正文预算接入和自动GC、完整R6/原生选择器、物理LAN/3×3、当前各平台24h、依赖源码重建、最低干净系统及正式发布继续；整体active。

"""
    if value['independentGlibcQualified']:
        section = section.replace('- [ ] 全根归属', '- [x] 独立Ubuntu从冻结快照新目录构建CLI与账本，23条通过，全部' + str(glibc['actualSourceFileCount']) + '份安装源码及274资格输入、C++14和程序前后摘要一致；这是底层专项，不是该环境全部核心/GUI验收。\n- [ ] 全根归属', 1)
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary, text, count=1, flags=re.M)
           .replace('## R122持久预算账本底层', section + '## R122持久预算账本底层', 1))
    update('docs/执行进度.md', lambda text: text.replace('## R122持久预算账本底层', section.replace('](docs/', '](') + '## R122持久预算账本底层', 1))
    update('README.md', lambda text: text.replace('R122持久预算底层及双Windows', summary + ' [Mac下载](docs/macOS独立预览包.md)。\n\nR122持久预算底层及双Windows', 1))
    for name in ['开发计划与进度.md', 'docs/执行进度.md', 'README.md', 'docs/macOS独立预览包.md']:
        update(name, lambda text: text.replace('完整协议终态已验3/4', '完整协议终态已验4/4')
               .replace('- [ ] R121完整协议按独立终态已验3/4；其余原作业仍运行，不重启、不预记为成功。',
                        '- [x] R121完整协议按独立终态已验4/4；四个平台全部终态通过。'))
    preview = ('## R122含依赖开发预览\n\n' + f'精确源码`{source}`；[逐层回执](validation/2026-11-08/state-budget-r122-macos-package/receipt.json)。'
               '双架构GUI/独立CLI、Qt5/OpenSSL部署、迁移运行、每包五项实际业务及四截图已验。开发adhoc签名，正式签名/公证及最低干净系统继续。\n\n'
               '| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n')
    for row in package['records']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['artifactSha256']} | {row['packageSha256']} |\n"
    preview += '\n本机副本：dist/macos-preview-20261108-r122-state-budget/。解压和独立CLI用法见下文。\n\n## R122原生编译归档\n\n'
    preview += '[回执](validation/2026-11-08/state-budget-r122-macos-compiled/receipt.json)。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['sha256']} |\n"
    preview += '\n'
    update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + summary + '\n\n', 1)
           .replace('## R121含依赖开发预览', preview + '## R121含依赖开发预览（历史）', 1))
    update('docs/持久预算账本底层.md', lambda text: text + '\nR122四原生底层专项各23条已通过。Windows Git默认检出存在257份LF→CRLF转换，按精确规则核对全部268份执行输入，vendor仍原字节；原始收验失败及差异清单保留。双Mac实际编译/含依赖包和迁移运行已验；完整项目及总预算仍未完成。\n')
    for index_name, report in [('docs/ci-verification-20261108-r122.json', None), ('docs/ci-verification-20261108-r121.json', old_terminal)]:
        p = REPO / index_name
        index = json.loads(p.read_bytes())
        if report is None:
            index.update(observedUtc=value['observedUtc'], sourceCommit=source, nativeBudgetRegressionRun=native['run'],
                         allFourNativeBudgetFoundationQualified=True, nativeCoreRun=core['run'], nativeCoreJobsVerified=core_count,
                         nativeQualificationPending=True, bothMacosCompiled=True, bothMacosPackagesQualified=True,
                         macosScreenshotsViewed=True, macosPackageRun=package['run'], independentGlibcQualified=value['independentGlibcQualified'],
                         independentGlibcQualificationPending=not value['independentGlibcQualified'], sourceSnapshotTestsPassed=True)
            refs = {row['path'] for row in index['receipts']} | {name + '/receipt.json' for name in folders if 'r122' in name}
        else:
            index.update(observedUtc=value['observedUtc'], nativeRun=report['run'], nativeTerminalJobsVerified=4,
                         fullNativeProtocolQualified=True, nativeQualificationPending=False)
            refs = {row['path'] for row in index['receipts']}
        index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((REPO / name).read_bytes()).hexdigest()} for name in sorted(refs)]
        p.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        shutil.copyfile(p, ROOT / index_name)
    for folder in folders:
        copy_folder(folder)
    value['evidenceFolders'] = folders
    target.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
