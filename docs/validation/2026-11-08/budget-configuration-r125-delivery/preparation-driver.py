"""日期：2026-11-08；按实际四原生配置与双Mac含依赖结果更新交付，生产总预算继续未完成。"""
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


# 日期：2026-11-08；仅同步文本、原XML及已查看截图，产品原件保持，不下载或复制秘密。
def mirror(folder):
    for path in (REPO / folder).rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.png', '.csv']:
            target = ROOT / path.relative_to(REPO)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)


# 日期：2026-11-08；两架构分别要求源码/载荷/迁移和截图，完整核心及协议按各自范围登记。
def main():
    target = ROOT / '.cache/r125-delivery-prepared.json'
    assert not target.exists()
    source = json.loads((ROOT / '.cache/r125-source-publication.json').read_bytes())['sourceCommit']
    public_preview = json.loads((ROOT / '.cache/r125-public-preview.json').read_bytes())
    assert public_preview['sourceCommit'] == source and public_preview['allAssetsMatchVerifiedPackages']
    assert public_preview['prerelease'] and len(public_preview['assets']) == 4
    downloads = json.loads((ROOT / '.cache/r125-public-download-verification.json').read_bytes())
    assert downloads['sourceCommit'] == source and downloads['anonymousDownloadsVerified']
    assert downloads['allDownloadedBytesMatchVerifiedPackages']
    names = {key: BASE + 'budget-configuration-r125-' + suffix for key, suffix in
             [('native', 'native'), ('core', 'full-native-core'), ('compiled', 'macos-compiled'), ('package', 'macos-package')]}
    reports = {key: json.loads((REPO / folder / 'receipt.json').read_bytes()) for key, folder in names.items()}
    assert all(value['sourceCommit'] == source for value in reports.values())
    native, core, compiled, package = [reports[key] for key in ['native', 'core', 'compiled', 'package']]
    assert native['allFourNativeConfigurationQualified'] and native['run']['conclusion'] == 'success'
    assert all(row['rowsPassed'] == 16 and row['warnings'] == row['skipped'] == 0 for row in native['records'])
    assert compiled['bothArchitecturesCompiledAndVerified']
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed'] and package['run']['conclusion'] == 'success'
    core_count = sum(row['qualified'] for row in core['records'])
    assert core_count == 4
    assert all(row['ctestTargetsPassed'] == 33 and row['qtXmlReportsVerified'] == 32 for row in core['records'])
    index = json.loads((ROOT / 'docs/ci-verification-20261108-r125.json').read_bytes())
    glibc = json.loads((ROOT / '.cache/r125-glibc/receipt.json').read_bytes())
    assert glibc['passed'] and glibc['rowsPassed'] == 16 and glibc['allInstalledSourceInputsUnchanged']
    installed = json.loads((ROOT / '.cache/r125-glibc/installed-source.json').read_bytes())
    differing = []
    for row in index['qualificationInputs']:
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
        assert (ROOT / row['path']).read_bytes() == (REPO / row['path']).read_bytes()
        if installed['files'][row['path']] != {'bytes': row['bytes'], 'sha256': row['sha256']}:
            differing.append(row['path'])
    assert differing == ['.github/workflows/budget-configuration-regression.yml']
    delta = json.loads((ROOT / '.cache/r125-glibc-input-difference.json').read_bytes())
    assert delta['productAndTestInputsMatch'] and len(delta['differences']) == 1
    execution = REPO / (BASE + 'budget-configuration-r125-delivery')
    execution.mkdir(exist_ok=False)
    shutil.copyfile(ROOT / '.cache/r125-public-preview.json', execution / 'public-preview.json')
    shutil.copyfile(ROOT / '.cache/publish-r125-preview.py', execution / 'publish-preview.py')
    shutil.copyfile(ROOT / '.cache/r125-public-download-verification.json', execution / 'anonymous-downloads.json')
    shutil.copyfile(ROOT / '.cache/verify-r125-public-download.py', execution / 'verify-public-downloads.py')
    for path in (ROOT / '.cache/r125-glibc').rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.sha256']:
            to = execution / 'glibc-qualified' / path.relative_to(ROOT / '.cache/r125-glibc')
            to.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, to)
    shutil.copyfile(ROOT / '.cache/validate-r125-glibc.py', execution / 'validate-glibc.py')
    shutil.copyfile(ROOT / '.cache/r125-glibc-input-difference.json', execution / 'glibc-input-difference.json')
    shutil.copyfile(Path(__file__), execution / 'preparation-driver.py')
    terminal_names = {version: BASE + name for version, name in
                      [('r123', 'state-domain-r123-native-terminal'), ('r124', 'legacy-ready-r124-native-terminal'),
                       ('r125', 'budget-configuration-r125-native-terminal')]}
    terminals = {version: json.loads((REPO / folder / 'receipt.json').read_bytes()) for version, folder in terminal_names.items()}
    assert terminals['r123']['allFourNativeProtocolJobsVerified']
    protocol_counts = {version: sum(row['qualified'] for row in value['records']) for version, value in terminals.items()}
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'allFourNativeConfigurationQualified': True, 'configurationRowsEach': 16,
              'nativeCoreJobsVerified': 4, 'bothMacosCompiled': True, 'bothMacosPackagesQualified': True,
              'screenshotsViewed': True, 'independentGlibcQualified': True, 'independentGlibcRows': 16,
              'publicPreviewUrl': public_preview['releaseUrl'], 'publicPreviewTag': public_preview['tag'],
              'anonymousPublicDownloadsVerified': True,
              'independentGlibcQualificationInputsMatched': 285, 'independentGlibcNonExecutedWorkflowLabelDifference': differing,
              'protocolTerminalJobsVerified': protocol_counts,
              'fullNativeProtocolQualified': terminals['r125']['allFourNativeProtocolJobsVerified'],
              'productionRootsIntegrated': False, 'globalQuotaEnforced': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (execution / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    folders = list(names.values()) + [execution.relative_to(REPO).as_posix()] + list(terminal_names.values())
    summary = (f'R125精确{source[:8]}四原生持久配置/真实CLI各16条通过，完整核心4/4各33项；'
               '双Mac GUI/CLI含依赖包、迁移运行及截图已验，下载更新R125。独立Ubuntu16条通过。'
               '生产根/历史迁移、实际总预算和自动GC继续。')
    old_checkpoint = '- [ ] 最终四原生配置专项、完整GUI/核心/协议、双Mac含依赖包和独立Ubuntu新目录继续按精确身份验收；当前可用Mac包仍R124。'
    new_checkpoint = '- [x] 四原生配置专项、完整GUI/核心、双Mac含依赖包和独立Ubuntu专项已按精确身份收验，当前下载R125；完整协议按独立作业继续收验，见本轮交付记录。'
    section = f'''## R125四原生配置与双Mac交付（2026-11-08）

- [x] 精确{source}已非强制公开；[四原生配置专项]({native['run']['html_url']})全部终态success，每平台16条、零跳过/警告。实际源码、CLI和测试程序前后保持，全部输入按精确Git检出规则核对。[原件](docs/validation/2026-11-08/budget-configuration-r125-native/receipt.json)。
- [x] Windows、Ubuntu、Apple Silicon、Intel各33完整CTest/32份Qt XML收验4/4；精确Darwin端口XFAIL与实际Windows权限跳过继续披露，不能由核心通过推定完整协议通过。[核心原件](docs/validation/2026-11-08/budget-configuration-r125-full-native-core/receipt.json)。
- [x] 双Mac GUI/独立CLI编译成功，含Qt5/OpenSSL包终态success；官方ZIP/内部tar、精确源码/载荷/链接/架构/执行位、系统PATH和中文空格目录迁移、每架构五项业务、Cocoa/高DPI及四张截图核验。[下载与摘要](docs/macOS独立预览包.md)。开发adhoc签名，正式签名/公证与最低干净系统继续。
- [x] [公开Mac开发预览]({public_preview['releaseUrl']})固定精确源码标签，两架构tar.gz及两份SHA-256附件已上传；四份附件实际匿名下载后逐字节摘要核对，无需GitHub登录。预览发布不代表正式发布验收完成。
- [x] 独立Ubuntu新目录真实编译及16条配置专项通过，全部安装快照、C++14和程序前后SHA保持。286资格输入中285份与最终提交相同；唯一差异为未在该环境执行的工作流注释/步骤标签，产品和测试输入全部相同，差异原SHA保留，不声称286份完全相同。[范围](docs/validation/2026-11-08/budget-configuration-r125-delivery/receipt.json)。
- [x] R123四原生完整协议终态全部通过；R124完整协议当前已验{protocol_counts['r124']}/4，R125已验{protocol_counts['r125']}/4，剩余按原作业继续。R122 ARM历史失败仍保留，R124旧版对照也通过，底层间歇根因不宣称已解决。
- [x] 额度配置支持原修订比较、固定持久意图/五布局恢复、真实进程退出和有保留额时拒绝收缩；三平台CLI显式域/根管理、64位输出、参数拒绝及原历史保持已验。[用法](docs/预算域管理与配置.md)。245维护源码零遗留/占位/简化标记，C++14/格式和原编码保持。
- [ ] 生产全部入口映射、普通历史安全迁移、SQLite/原子替换/正文及物理分配/跨卷准入、有效幂等保留与自动GC、完整R6/选择器、物理LAN/3×3、当前各平台24h、依赖源码重建、最低干净系统和正式发布继续；整体active。

'''
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace(old_checkpoint, new_checkpoint).replace('## R125持久预算配置与三平台CLI', section + '## R125持久预算配置与三平台CLI', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace(old_checkpoint, new_checkpoint).replace('## R125持久预算配置与三平台CLI', section.replace('](docs/', '](') + '## R125持久预算配置与三平台CLI', 1))
    update('README.md', lambda text: text.replace('R125新增持久额度配置及state budget/root CLI', summary + ' [Mac下载](docs/macOS独立预览包.md)。\n\nR125新增持久额度配置及state budget/root CLI', 1))
    update('docs/预算域管理与配置.md', lambda text: text + '\nR125精确源码四原生各16条专项及各33完整核心已核验；本机双Windows和独立Ubuntu专项通过。原生结果及边界见[验证索引](ci-verification-20261108-r125.json)。生产写入总预算仍未接入。\n')
    preview = f'## R125含依赖开发预览\n\n精确源码`{source}`；[逐层回执](validation/2026-11-08/budget-configuration-r125-macos-package/receipt.json)。开发adhoc签名，正式签名/公证和最低干净系统继续。\n\n'
    preview += '[公开开发预览与四份附件](' + public_preview['releaseUrl'] + ')。\n\n'
    preview += '| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
    for row in package['records']:
        asset, = [asset for asset in public_preview['assets'] if asset['name'] == row['archive']]
        assert asset['sha256'] == row['packageSha256']
        preview += f"| {row['architecture']} | [下载tar.gz]({asset['downloadUrl']}) · [CI原件]({row['artifactUrl']}) | {row['artifactSha256']} | {row['packageSha256']} |\n"
    preview += '\n本机副本：dist/macos-preview-20261108-r125-budget-configuration/。解压和独立CLI用法见下文。\n\n'
    preview += '## R125原生编译归档\n\n[回执](validation/2026-11-08/budget-configuration-r125-macos-compiled/receipt.json)。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['sha256']} |\n"
    preview += '\n'
    update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + summary + '\n\n' + preview, 1).replace('## R124含依赖开发预览', '## R124含依赖开发预览（历史）', 1))
    for folder in folders:
        mirror(folder)
    for version in ['r123', 'r124', 'r125']:
        path = ROOT / ('docs/ci-verification-20261108-' + version + '.json')
        value = json.loads(path.read_bytes())
        refs = {row['path'] for row in value['receipts']}
        if version == 'r125':
            value.update(sourceCommit=source, allFourNativeConfigurationQualified=True,
                         nativeConfigurationRun=native['run'], nativeCoreRun=core['run'], nativeCoreJobsVerified=4,
                         bothMacosCompiled=True, bothMacosPackagesQualified=True, macosPackageRun=package['run'],
                         publicPreviewUrl=public_preview['releaseUrl'], publicPreviewTag=public_preview['tag'],
                         anonymousPublicDownloadsVerified=True,
                         macosScreenshotsViewed=True, independentGlibcQualified=True,
                         independentGlibcQualificationPending=False, independentGlibcQualificationInputsMatched=285,
                         independentGlibcNonExecutedWorkflowLabelDifference=differing)
            refs |= {folder + '/receipt.json' for folder in folders if 'r125' in folder}
        value.update(nativeRun=terminals[version]['run'], nativeTerminalJobsVerified=protocol_counts[version],
                     fullNativeProtocolQualified=terminals[version]['allFourNativeProtocolJobsVerified'],
                     observedUtc=record['observedUtc'])
        value['receipts'] = [{'path': ref, 'sha256': hashlib.sha256((ROOT / ref).read_bytes()).hexdigest()} for ref in sorted(refs)]
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        shutil.copyfile(path, REPO / path.relative_to(ROOT))
    record['evidenceFolders'] = folders
    target.write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
