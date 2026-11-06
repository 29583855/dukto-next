"""日期：2026-11-07；记录已实际审阅的R100部署包，更新下载、计划和精确公开证据。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
PARENT = 'f913d5cc7c57518e9a068c4a5a70e0b8743a398b'
ROOT = Path.cwd()
BASE = ROOT / 'docs/validation/2026-11-07'


# 日期：2026-11-07；只有查看工具已实际打开的原图才登记视觉结论，原核验回执保持不变。
def qualify(folder, original_name, images, scope, proof):
    original = folder / original_name
    value = json.loads(original.read_text('utf-8'))
    assert value['sourceCommit'] == COMMIT and value['passed'] and not value['screenshotsViewed']
    visual = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'actuallyViewed': True,
              'screenshots': [proof(folder / name) for name in images], 'scope': scope,
              'fullNativeInteractionQualified': False, 'nativeSelectorsQualified': False}
    visual_path = folder / 'visual-review.json'
    qualified_path = folder / 'qualified-receipt.json'
    assert not visual_path.exists() and not qualified_path.exists()
    visual_path.write_text(json.dumps(visual, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    qualified = dict(value, originalVerifiedReceipt=proof(original), visualReview=proof(visual_path),
                     screenshotsViewed=True, screenshotsReviewed=len(images))
    qualified_path.write_text(json.dumps(qualified, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return qualified, qualified_path


# 日期：2026-11-07；实际部署三平台结果与完整协议、长测和正式发布分开登记，不改源码和测试门槛。
def main():
    checkout = ROOT / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    mac_folder = BASE / 'clipboard-r100-macos-package-terminal'
    linux_folder = BASE / 'clipboard-r100-linux-package-terminal'
    r99_folder = BASE / 'text-send-r99-native-terminal'
    r99_path = r99_folder / 'receipt.json'
    r99 = json.loads(r99_path.read_text('utf-8'))
    assert r99['sourceCommit'] == 'a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38'
    assert r99['allOriginalCoreAndProtocolReportsVerified'] and r99['protocolReports'] == 188
    assert r99['coreTargetsEach'] == 23 and r99['explicitDarwinExpectedFailureCount'] == 2
    mac_images = [label + '/build/' + name for label in ('macos-preview-ARM64', 'macos-preview-X64')
                  for name in ('package-runtime.png', 'main-window-navigation/native/Testing/QtTest/main-server-430x700.png')]
    mac, mac_path = qualify(mac_folder, 'receipt.json', mac_images,
                            'Both architecture native startup and server navigation screenshots actually viewed; Chinese labels and main controls visible', proof)
    linux, linux_path = qualify(linux_folder, 'verified-summary.json',
                                ['build/package-x11.png', 'build/package-wayland.png'],
                                'Actual X11/Wayland first-launch dialogs viewed; Chinese text, controls and receiver ready status visible', proof)
    assert mac['bothArchitecturesVerified'] and len(mac['packages']) == 2
    assert all(row['applicationSourceFiles'] == 338 and len(row['runtimeReports']) == 5 for row in mac['packages'])
    assert linux['package']['applicationSourceFiles'] == 338 and linux['core']['coreTargets'] == 23
    assert len(linux['runtimeReports']) == 2 and linux['package']['runtimeMigrationBothDisplaysQualified']
    for folder, value in (('macos-preview-20261107-r100-clipboard', mac),
                          ('linux-preview-20261107-r100-clipboard', linux)):
        target = ROOT / 'dist' / folder / 'QUALIFIED-RECEIPT.json'
        assert not target.exists()
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    audit = json.loads((ROOT / '.cache/audit-r100-packages.json').read_text('utf-8'))
    assert audit['sourceMarkersPassed'] and not audit['findings'] and audit['cxx14Configuration']
    assert audit['formatting']['passed'] and len(audit['files']) == 204
    audit_path = mac_folder / 'source-audit.json'
    shutil.copyfile(ROOT / '.cache/audit-r100-packages.json', audit_path)
    shutil.copyfile(ROOT / 'scripts/audit.py', mac_folder / 'source-audit-driver.py')
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    observed = {}
    for label, number in (('r99Native', 42276738981), ('r100Native', 42282812778)):
        run = request('/repos/29583855/dukto-next/actions/runs/' + str(number))
        observed[label] = {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')}
    run_path = mac_folder / 'full-native-observation.json'
    assert not run_path.exists()
    run_path.write_text(json.dumps(observed, indent=2) + '\n', 'utf-8')
    r99_report_path = ROOT / 'docs/ci-verification-20261107-r99.json'
    r99_report = json.loads(r99_report_path.read_text('utf-8'))
    r99_report.update(nativeCIPending=False, nativeRun=observed['r99Native'],
                      fullNativeRegressionQualified=True, nativeTerminalEvidence=proof(r99_path),
                      originalCoreTargetsEach=23, protocolReports=188,
                      explicitDarwinExpectedFailureCount=2)
    save(r99_report_path, r99_report)
    report_path = ROOT / 'docs/ci-verification-20261107-r100.json'
    report = json.loads(report_path.read_text('utf-8'))
    assert report['sourceCommit'] == COMMIT and len(report['buildInputs']) == 210
    for row in report['buildInputs']:
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
    report.update(observedUtc=datetime.now(timezone.utc).isoformat(), macosPackageEvidence=proof(mac_path),
                  macosPackages=mac['packages'], linuxPackageEvidence=proof(linux_path),
                  linuxPackage=linux['package'], packageSourceFilesEach=338,
                  packageScreenshotsReviewed=6, sourceAudit=proof(audit_path),
                  fullNativeRunObservation=proof(run_path), fullNativeRegressionQualified=False)
    save(report_path, report)
    index_path = ROOT / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index['packagesBeforeR100Deployment'] = index['packages']
    index['macOSPreviewBeforeR100Deployment'] = index['macOSPreview']
    index['linuxPreviewBeforeR100Deployment'] = index['linuxPreview']
    index['nativeFullBeforeR99Qualification'] = index['nativeFull']
    index['nativeFull'] = dict(r99['run'], sourceCommit=r99['sourceCommit'], evidence=proof(r99_path),
                               originalReportsVerified=True, coreTargetsEach=23, protocolReports=188,
                               explicitDarwinExpectedFailures=2, qualifiedWithExplicitBoundary=True)
    index['textSendGuardR99'].update(nativeCIPending=False, nativeRun=observed['r99Native'],
                                      manifest=proof(r99_report_path), nativeTerminalEvidence=proof(r99_path))
    index['packages'] = mac['packages'] + [linux['package']]
    index['macOSPreview'] = {'sourceCommit': COMMIT, 'runUrl': mac['run']['html_url'],
                            'workflowConclusion': 'success', 'runtimeReportsEach': 5,
                            'bothArchitecturesVerified': True, 'screenshotsViewed': True,
                            'evidence': proof(mac_path), 'releaseQualified': False,
                            'adhocSigned': True, 'developerIdSigned': False, 'notarized': False}
    index['linuxPreview'] = {'sourceCommit': COMMIT, 'package': linux['package'],
                            'bothDisplayRuntimesPassed': True, 'nativeCoreTargets': 23,
                            'embeddedBusinessReportsEach': 3, 'screenshotsViewed': True,
                            'evidence': proof(linux_path),
                            'binaryIdentityScope': 'ELF/launcher hashes checked; overwrite/recovery bind launcher; transfer report has no executable hash field'}
    index['packageRuntime']['macOS'] = {'sourceCommit': COMMIT, 'runUrl': mac['run']['html_url'],
                                       'bothArchitecturesVerified': True, 'evidence': proof(mac_path)}
    index['packageRuntime']['linux'] = {'sourceCommit': COMMIT, 'runUrl': linux['run']['html_url'],
                                       'bothDisplaysVerified': True, 'evidence': proof(linux_path)}
    index.update(observedUtc=report['observedUtc'], currentSourceStage='R100 deployed GUI/independent CLI packages verified on Windows, macOS ARM/Intel and Linux X11/Wayland; whole protocols and long-test qualification pending',
                 releaseQualified=False, deliveryComplete=False)
    index['clipboardAvailabilityR100'].update(manifest=proof(report_path), nativeRun=observed['r100Native'])
    save(index_path, index)
    note = '''

## R100三平台当前部署包收验（2026-11-07）

- [x] 双Mac含依赖部署包更新至精确ed4f5cf：每包338份应用源码全集逐Git blob一致；全部载荷、各71框架链接、Mach-O架构和执行权限逐件核验。系统PATH/中文空格目录迁移、独立CLI、16通道双向、1/4/16覆盖和两组4→8恢复均通过，每包5份原业务报告与父摘要一致。
- [x] Cocoa原生及150%/200%导航逐帧摘要/中文覆盖通过；双架构首次启动和服务器导航4张原生截图已查看，中文和主要控件正常。当前仍为adhoc开发预览。
- [x] Linux含依赖包更新至同一ed4f5cf：338源码、708部署文件、2链接和132 ELF核验；23核心、剪贴板/草稿实际QML、四种退出状态及原16组通过。X11/Wayland各3业务通过，两张实际启动截图已查看。
- [x] 本轮204份维护源码审计零TODO/FIXME/未实现或简化标记，C++14配置和clang-format检查通过；审计零标记不代替完整功能验收。审计脚本内历史缺项文本按原件保留，当前状态以主计划快照为准。
- [x] R99精确a316e4a四平台完整原运行终态success，各23核心、合计188协议及发送8组/草稿恢复原件逐件通过；双Mac共2条精确Darwin XFAIL继续保留，不授予内核端口独占资格。
- [ ] R100完整协议仍单独按真实终态收验；Windows/Linux真实86400秒、完整编辑器/系统剪贴板预算、全部R6/原生交互和选择器、全部资源预算/公平性/安全GC、物理LAN/3×3、各平台长期、依赖源码独立重建及正式签名发布继续未完成。
'''

    # 日期：2026-11-07；只更新当前快照的对应行，保留全部历史失败和未验收范围。
    def plan_update(text):
        text = text.replace('当前阶段：R100四平台各23核心与双Mac编译已验，当前Windows部署包通过；完整协议、Windows/Linux长测及交付继续。',
                            '当前阶段：R100四平台各23核心和三平台当前GUI/独立CLI部署包已验；完整协议、Windows/Linux长测及交付继续。', 1)
        text = text.replace('剪贴板/草稿QML、双Mac实际GUI/CLI编译产物及当前Windows部署迁移通过，完整协议仍待终态收验。',
                            '剪贴板/草稿QML、三平台当前GUI/独立CLI部署包及原迁移业务通过，完整协议仍待终态收验。', 1)
        text = text.replace('| Linux | R100云端23核心及剪贴板/草稿QML已验；R98独立干净构建和双显示部署包、20轮长测短验通过 | 完整协议、新部署包和真实24h终态 |',
                            '| Linux | R100云端及包构建各23核心、剪贴板/草稿QML、338源码/708载荷/132 ELF与双显示部署业务已验 | 完整协议、完整原生交互和真实24h终态 |', 1)
        text = text.replace('| macOS ARM / Intel | R100各23核心/剪贴板和草稿QML/双架构GUI与CLI编译产物已验；R96含依赖双部署包已验 | R99/R100完整协议终态、新部署包、完整交互和正式分发 |',
                            '| macOS ARM / Intel | R100各23核心、剪贴板/草稿QML及含依赖双部署包已验；各338源码、5迁移业务及Cocoa/高DPI导航通过 | R100完整协议终态、完整交互/选择器和正式分发 |', 1)
        text = text.replace('R99/R100原生回归继续 |', 'R99完整回归已验，R100原生回归继续 |', 1)
        text = text.replace('当前Windows部署包已更新为R100；Mac含依赖预览仍为R96、Linux为R98，最新Mac编译输出另有R100双架构下载。',
                            '当前Windows、macOS双架构和Linux含依赖部署包均为精确R100源码ed4f5cf；下载、摘要与独立视觉回执见各平台预览包说明。', 1)
        return text.rstrip() + note

    update(ROOT / '开发计划与进度.md', plan_update)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(ROOT / name, lambda text: text.rstrip() + note)
    mac_intro = ('更新日期：2026-11-07。当前含依赖预览包为R100，精确源码`' + COMMIT + '`，采用C++14、Qt5和CMake；Apple Silicon和Intel均有GUI、独立CLI及Qt5/OpenSSL依赖。\n\n'
                 '## 当前R100含依赖部署包\n\n'
                 '[双架构打包与原生迁移工作流](' + mac['run']['html_url'] + ')终态success；ZIP含tar.gz、校验文件和运行原件，附件可能需要登录GitHub。\n\n'
                 '| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n')
    for row in mac['packages']:
        mac_intro += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['sha256'] + '` |\n'
    mac_intro += ('\n每包338份应用源码全集与精确Git对象一致；各71框架链接、全部载荷、Mach-O架构和执行权限已验。每包五份原业务报告通过，覆盖独立CLI、16通道双向、1/4/16覆盖及4→8恢复；系统PATH/中文空格路径迁移通过。'
                  'Cocoa及150%/200%导航和中文覆盖通过，四张实际原生启动/导航截图已查看。[收验及独立视觉回执](validation/2026-11-07/clipboard-r100-macos-package-terminal/qualified-receipt.json)。\n\n'
                  '解压ZIP后用tar保留权限和框架链接，启动方式见下方示例。当前是adhoc开发预览；Developer ID、公证、干净系统、最低系统、完整GUI/选择器、第三方源码独立重建及正式发行继续验收。完整协议和长期按各自真实终态收验。\n\n')

    # 日期：2026-11-07；当前入口置顶，R96和编译输出仍明确保留各自历史来源。
    def mac_update(text):
        start = text.index('更新日期：')
        end = text.index('## R100最新编译产物')
        text = text[:start] + mac_intro + text[end:]
        text = text.replace('下方含依赖预览包保持已验R96。', '当前含依赖R100包见顶部；本节保留独立编译原件。', 1)
        text = text.replace('下方独立预览包已经部署依赖，其源码保持R96。', '当前含依赖R100包见顶部；本节保留R99编译身份。', 1)
        text = text.replace('## 下载与校验', '## R96下载与校验（历史）', 1)
        text = text.replace('R99完整原生回归尚在运行，编译产物不授予整轮测试通过或正式发布资格。',
                            'R99完整原生回归现已严格收验四平台各23核心和合计188协议，通过原件见R99终态回执；编译产物本身不授予正式发布资格。', 1)
        return text.replace('## 已验证范围', '## R96已验证范围（历史）', 1)

    update(ROOT / 'docs/macOS独立预览包.md', mac_update)
    package = linux['package']
    linux_intro = ('更新日期：2026-11-07。当前含依赖包为R100，精确源码`' + COMMIT + '`，包含GUI与可独立运行的CLI，采用C++14、Qt5和CMake。目标Ubuntu24.04或更新的x86_64 glibc环境，要求glibc2.39起和系统CJK字体。\n\n'
                   '## 当前R100可下载包\n\n[下载x86_64 glibc预览包](' + package['artifactUrl'] + ')（GitHub附件可能需要登录）。ZIP含tar.gz、SHA和原始证据。内部tar.gz SHA-256：`' + package['sha256'] + '`。\n\n'
                   '338份应用源码全集与精确Git对象逐字节一致；708部署文件、2链接和132 ELF已验。包构建23核心、剪贴板状态/草稿恢复实际QML、四种退出状态及原16组通过。X11和Wayland实际迁移各通过16通道双向、1/4/16覆盖及4→8恢复，双显示各三份业务报告已验。两张实际首次启动图已查看，中文和主要控件正常。\n\n'
                   '[原件及独立视觉回执](validation/2026-11-07/clipboard-r100-linux-package-terminal/qualified-receipt.json)固定程序、源码和截图身份；本机归档`dist/linux-preview-20261107-r100-clipboard`。系统需CJK字体，例如fonts-wqy-zenhei。\n\n'
                   '当前已包含R99发送文本预检/拒绝保留草稿及R100剪贴板可用状态修复。Xvfb/Weston迁移不代替完整物理桌面、干净系统、第三方源码独立重建和正式发行；完整协议及86400秒长期继续单独收验。\n\n')
    update(ROOT / 'docs/Linux独立预览包.md', lambda text: text[:text.index('更新日期：')] + linux_intro + text[text.index('## 构建依赖'):])

    # 日期：2026-11-07；README当前结论覆盖对应段落，历史精确证据与未完成项继续保留。
    def readme_update(text):
        start = text.index('公开仓库为')
        end = text.index('新增[b9d9b78上传发送端确认]')
        current = ('公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R100精确源码`ed4f5cf`的四平台各23核心、88份Qt报告和剪贴板/草稿QML已验；双Mac各保留一条明确Darwin端口共享XFAIL。'
                   '当前含依赖部署包均已更新到R100：[Windows](docs/Windows独立预览包.md)、[macOS Apple Silicon/Intel](docs/macOS独立预览包.md)、[Linux](docs/Linux独立预览包.md)，均含GUI和独立CLI，实际迁移、16通道及恢复业务通过。'
                   '完整协议、真实长期、完整GUI、物理网络及正式交付继续。见[计划](开发计划与进度.md)和[当前索引](docs/current-validation.json)。\n\n')
        return (text[:start] + current + text[end:]).rstrip() + note

    update(ROOT / 'README.md', readme_update)
    state_path = ROOT / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(r100MacosPackage={'sourceCommit': COMMIT, 'evidence': proof(mac_path), 'passed': True},
                 r100LinuxPackage={'sourceCommit': COMMIT, 'evidence': proof(linux_path), 'passed': True},
                 r99NativeTerminal={'sourceCommit': r99['sourceCommit'], 'evidence': proof(r99_path), 'passed': True})
    save(state_path, state)
    shutil.copyfile(Path(__file__), mac_folder / 'result-record-driver.py')
    shutil.copyfile(ROOT / '.cache/prepare-r100-linux-collector.py', linux_folder / 'collector-preparation.py')
    shutil.copyfile(ROOT / '.cache/r100-tag-duplicate-cancellation.json', mac_folder / 'tag-duplicate-cancellation.json')
    names = {'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/macOS独立预览包.md', 'docs/Linux独立预览包.md',
             'docs/ci-verification-20261107-r100.json', 'docs/ci-verification-20261107-r99.json', 'docs/current-validation.json',
             'docs/validation/2026-11-06/github-api-push-r100-native-core-windows-package.json'}
    for folder in (mac_folder, linux_folder, r99_folder):
        names.update(path.relative_to(ROOT).as_posix() for path in folder.rglob('*')
                     if path.is_file() and path.suffix not in ('.zip', '.gz'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    listing = ROOT / '.cache/r100-deployed-packages-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (ROOT / '.cache/r100-deployed-packages-stage.nul').write_bytes(b'\0'.join(name.encode('utf-8') for name in names) + b'\0')
    stage = (ROOT / '.cache/stage-r100-core-windows-package.py').read_bytes().replace(b'r100-core-windows-package', b'r100-deployed-packages')
    (ROOT / '.cache/stage-r100-deployed-packages.py').write_bytes(stage)
    print(json.dumps({'explicitFilesPrepared': len(names), 'sourceCommit': COMMIT,
                      'macosPackagesVerified': 2, 'linuxDisplaysVerified': 2,
                      'screenshotsActuallyReviewed': 6, 'fullProtocolQualified': False}), flush=True)


if __name__ == '__main__':
    main()
