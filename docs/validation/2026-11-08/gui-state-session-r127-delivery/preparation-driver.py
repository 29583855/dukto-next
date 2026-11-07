"""日期：2026-11-08；冻结GUI/CLI状态接入的原生核心、双Mac预览及真实公开下载证据。"""
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


# 日期：2026-11-08；只同步有界文本与实际查看截图，二进制分发仍留dist及Release。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.csv', '.png']:
            dest = target / path.relative_to(source)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, dest)


# 日期：2026-11-08；不同平台及阶段按独立原件授予资格；待完成项目不会因发布开发预览被勾选。
def main():
    target = ROOT / '.cache/r127-delivery-prepared.json'
    assert not target.exists()
    source = json.loads((ROOT / '.cache/r127-source-publication.json').read_bytes())['sourceCommit']
    folders = [BASE + 'gui-state-session-r127-' + suffix for suffix in ['full-native-core', 'macos-compiled', 'macos-package', 'native-terminal']]
    core, compiled, package, terminal = [json.loads((REPO / name / 'receipt.json').read_bytes()) for name in folders]
    assert all(value['sourceCommit'] == source for value in [core, compiled, package, terminal])
    assert core['allFourNativeCoreJobsVerified']
    assert all(row['ctestTargetsPassed'] == 34 and row['qtXmlReportsVerified'] == 33 for row in core['records'])
    for row in core['records']:
        panel, = [value for value in row['verifiedQtReports'] if value['xml'] == 'server-panel-tests.xml']
        assert panel['methods'] == 8 and not panel['diagnostics']
    assert compiled['bothArchitecturesCompiledAndVerified']
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed'] and package['run']['conclusion'] == 'success'
    preview = json.loads((ROOT / '.cache/r127-public-preview.json').read_bytes())
    downloads = json.loads((ROOT / '.cache/r127-public-download-verification.json').read_bytes())
    assert preview['sourceCommit'] == downloads['sourceCommit'] == source
    assert preview['allAssetsMatchVerifiedPackages'] and downloads['anonymousDownloadsVerified']
    assert downloads['allDownloadedBytesMatchVerifiedPackages'] and len(preview['assets']) == 4
    index_path = ROOT / 'docs/ci-verification-20261108-r127.json'
    index = json.loads(index_path.read_bytes())
    for row in index['qualificationInputs']:
        assert (ROOT / row['path']).read_bytes() == (REPO / row['path']).read_bytes()
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
    result_folder = BASE + 'gui-state-session-r127-delivery'
    output = REPO / result_folder
    output.mkdir(exist_ok=False)
    for name, dest in [('r127-public-preview.json', 'public-preview.json'),
                       ('r127-public-download-verification.json', 'anonymous-downloads.json'),
                       ('publish-r127-preview.py', 'publish-preview.py'),
                       ('verify-r127-public-download.py', 'verify-downloads.py')]:
        shutil.copyfile(ROOT / '.cache' / name, output / dest)
    glibc_qualified = False
    glibc_path = ROOT / '.cache/r127-glibc-recheck/receipt.json'
    if glibc_path.exists():
        glibc = json.loads(glibc_path.read_bytes())
        assert glibc['passed'] and glibc['rowsPassed'] == 8 and glibc['allInstalledSourceInputsUnchanged']
        installed = json.loads((ROOT / '.cache/r127-glibc/installed-source.json').read_bytes())
        for row in index['qualificationInputs']:
            assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}, row['path']
        copy(ROOT / '.cache/r127-glibc', output / 'independent-glibc-first-failed')
        copy(ROOT / '.cache/r127-glibc-recheck', output / 'independent-glibc-corrected')
        shutil.copyfile(ROOT / '.cache/recheck-r127-glibc-panel.py', output / 'recheck-glibc.py')
        shutil.copyfile(ROOT / '.cache/validate-r127-glibc.py', output / 'validate-glibc.py')
        glibc_qualified = True
    old_folder = BASE + 'cli-state-session-r126-native-terminal'
    old_terminal = json.loads((REPO / old_folder / 'receipt.json').read_bytes())
    current_count = sum(row['qualified'] for row in terminal['records'])
    old_count = sum(row['qualified'] for row in old_terminal['records'])
    failures = {key: [{'runner': row['runner'], 'conclusion': row.get('conclusion'),
                       'failedCases': [case['name'] for case in row.get('failedProtocolCases', [])]}
                      for row in value['records'] if row.get('conclusion') == 'failure']
                for key, value in [('r126', old_terminal), ('r127', terminal)]}
    assert any(set(row['failedCases']) == {'credential-rotation', 'task-items'} for row in failures['r126'])
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'nativeCoreJobsVerified': 4, 'ctestTargetsEach': 34, 'qtXmlEach': 33, 'serverPanelRowsEach': 8,
              'bothMacosCompiled': True, 'bothMacosPackagesQualified': True, 'screenshotsViewed': True,
              'publicPreviewUrl': preview['releaseUrl'], 'anonymousPublicDownloadsVerified': True,
              'independentGlibcQualified': glibc_qualified, 'independentGlibcQualificationPending': not glibc_qualified,
              'nativeProtocolJobsVerified': current_count, 'previousProtocolJobsVerified': old_count, 'originalProtocolFailures': failures,
              'fullNativeProtocolQualified': terminal['allFourNativeProtocolJobsVerified'],
              'guiRemoteAndCliSameDirectoryLifecycleQualified': True,
              'allProductionRootsIntegrated': False, 'globalQuotaEnforced': False,
              'deliveryComplete': False, 'releaseQualified': False}
    if glibc_qualified:
        record.update(independentGlibcRows=8, independentGlibcQualificationInputsMatched=291, independentGlibcOriginalDriverFailureRetained=True)
    (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'preparation-driver.py')
    folders += [result_folder, old_folder]
    for folder in folders:
        copy(REPO / folder, ROOT / folder)
    old_path = ROOT / 'docs/ci-verification-20261108-r126.json'
    old = json.loads(old_path.read_bytes())
    old.update(nativeRun=old_terminal['run'], nativeTerminalJobsVerified=old_count,
               fullNativeProtocolQualified=old_terminal['allFourNativeProtocolJobsVerified'])
    old['receipts'] = [{'path': row['path'], 'sha256': hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest()} for row in old['receipts']]
    old_path.write_text(json.dumps(old, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(old_path, REPO / old_path.relative_to(ROOT))
    index.update(sourceCommit=source, nativeCoreJobsVerified=4, nativeCoreRun=core['run'],
                 nativeQualificationPending=False, bothMacosCompiled=True, bothMacosPackagesQualified=True,
                 macosPackageRun=package['run'], macosScreenshotsViewed=True,
                 publicPreviewUrl=preview['releaseUrl'], anonymousPublicDownloadsVerified=True,
                 independentGlibcQualified=glibc_qualified, independentGlibcQualificationPending=not glibc_qualified,
                 nativeRun=terminal['run'], nativeTerminalJobsVerified=current_count,
                 fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'], observedUtc=record['observedUtc'])
    if glibc_qualified:
        index.update(independentGlibcRows=8, independentGlibcQualificationInputsMatched=291, independentGlibcOriginalDriverFailureRetained=True)
    refs = {row['path'] for row in index['receipts']} | {folder + '/receipt.json' for folder in folders}
    index['receipts'] = [{'path': ref, 'sha256': hashlib.sha256((ROOT / ref).read_bytes()).hexdigest()} for ref in sorted(refs)]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(index_path, REPO / index_path.relative_to(ROOT))
    summary = (f'R127精确{source[:8]}GUI与CLI同目录状态接入已验，四原生各34核心/33份Qt XML、面板各8项通过；'
               '双Mac含Qt5/OpenSSL预览、迁移业务与四截图已验并公开下载。'
               + ('独立Ubuntu8项通过。' if glibc_qualified else '独立Ubuntu新目录构建继续。')
               + 'R126原完整协议两项旧夹具假设已失败，原件保留；修正独立验收。普通历史迁移、全应用预算和自动GC未完成。')
    section = f'''## R127四原生GUI接入与双Mac预览（2026-11-08）

- [x] 精确{source}四平台C++14 GUI/独立CLI编译、各34完整CTest/33份Qt XML已收验；服务器面板各8项通过，包括真实GUI空闲监听阻止CLI维护及停止/启动失败释放资格。精确Darwin端口XFAIL和Windows权限跳过继续披露。[核心原件](docs/validation/2026-11-08/gui-state-session-r127-full-native-core/receipt.json)。
- [x] 双Mac含Qt5/OpenSSL部署包、中文空格目录迁移运行、各五项实际业务、Cocoa窗口/高DPI及四张截图通过；官方ZIP和内部tar摘要、源码/载荷/链接/架构/执行位逐项核对。[开发预览]({preview['releaseUrl']})四份附件已真实匿名下载核对。[摘要和用法](docs/macOS独立预览包.md)。
- [x] 开发预览固定精确源码标签；仍采用adhoc签名，Developer ID签名、公证及最低干净系统验收继续。本次预览发布不授予完整项目或正式发布资格。
GLIBC_LINE
- [x] 双Windows34核心及8项面板、真实GUI强杀后同任务续传和诊断已验，291源码及程序保持，249维护源码零标记、原编码及C++14/格式保持。GUI远程状态目录与CLI同目录域共用，普通历史和全应用预算范围见[目录契约](docs/GUI与CLI状态目录共享.md)。
- [ ] R126完整协议已收取的原生终态中，credential-rotation因复制旧根标记、task-items因仅允许锁文件的旧夹具假设失败；完整协议资格未通过，原日志与报告保留。R127沿用相同旧夹具，其原作业独立收验；后续修正先建立正确ACL的测试根并独立验证绑定拒绝，同时保留旧凭据网络负例和固定256字节标记的只读计量。不能用后续通过改写本轮原失败。R126完整协议已验{old_count}/4，本轮已验{current_count}/4，其余按原作业继续；普通历史安全迁移、全应用根/临时对象归属、实际写前额度、跨卷与未知项、有效幂等保留、自动GC、物理LAN/3×3、当前各平台24h和其余完整交付继续；整体active。

'''
    section = section.replace('GLIBC_LINE', '- [x] 独立Ubuntu新目录真实构建后，首次驱动从源码目录启动导致3项截图保存失败（5通过/3失败）；原件保留。改为CTest构建工作目录后，相同源和程序8项面板测试全部通过；291资格输入与公开提交全部相同。' if glibc_qualified else '- [ ] 独立Ubuntu新目录实际GUI专项构建继续，未完成前不授予资格。')
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace('## R127 GUI与CLI同目录状态会话', section + '## R127 GUI与CLI同目录状态会话', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace('## R127 GUI与CLI同目录状态会话', section.replace('](docs/', '](') + '## R127 GUI与CLI同目录状态会话', 1))
    update('README.md', lambda text: text.replace('R127接入GUI服务器页', summary + ' [Mac下载](docs/macOS独立预览包.md)。\n\nR127接入GUI服务器页', 1))
    update('docs/GUI与CLI状态目录共享.md', lambda text: text + '\nR127精确源码的四原生完整核心及每平台8项面板测试已验；双Mac含依赖包和迁移运行通过，公开下载见[预览说明](macOS独立预览包.md)。完整协议、独立环境和待完成范围见验证索引。\n')
    preview_text = '## R127含依赖开发预览\n\n精确源码`' + source + '`；[逐层回执](validation/2026-11-08/gui-state-session-r127-macos-package/receipt.json)。\n\n[公开开发预览与四份附件](' + preview['releaseUrl'] + ')。开发adhoc签名，正式签名、公证和最低干净系统继续。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in package['records']:
        asset, = [asset for asset in preview['assets'] if asset['name'] == row['archive']]
        assert asset['sha256'] == row['packageSha256']
        preview_text += f"| {row['architecture']} | [下载tar.gz]({asset['downloadUrl']}) · [CI原件]({row['artifactUrl']}) | {row['packageSha256']} |\n"
    preview_text += '\n本机副本：dist/macos-preview-20261108-r127-gui-state-session/。独立CLI入口及用法见下文。\n\n'
    update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + summary + '\n\n' + preview_text, 1).replace('## R125含依赖开发预览', '## R125含依赖开发预览（历史）', 1))
    record['evidenceFolders'] = folders
    target.write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
