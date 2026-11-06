"""日期：2026-11-07；发布R100四平台核心及Windows真实部署结果，完整协议和长期资格继续独立验收。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
PARENT = '0c3ac949d92051da2ad25f9987a93116c5d21fe9'


# 日期：2026-11-07；截图已实际查看；原收验回执保持不变，新增可复核的视觉观察和限定范围资格。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    core_folder = root / 'docs/validation/2026-11-07/clipboard-r100-native-core'
    core_path = core_folder / 'receipt.json'
    core = json.loads(core_path.read_text('utf-8'))
    assert core['passed'] and core['sourceCommit'] == COMMIT
    assert core['coreTargetsEach'] == 23 and core['originalQtReportsVerified'] == 88
    assert len(core['cores']) == 4 and core['explicitDarwinExpectedFailureCount'] == 2
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    package_dispatch = {}
    for workflow in ('macos-package.yml', 'linux-package.yml'):
        ledger_path = root / ('.cache/r100-' + workflow.removesuffix('.yml') + '-dispatch.json')
        ledger = json.loads(ledger_path.read_text('utf-8'))
        assert ledger['sourceCommit'] == COMMIT and ledger['responseReceived']
        runs = request('/repos/29583855/dukto-next/actions/workflows/' + workflow + '/runs?per_page=100&head_sha=' + COMMIT)['workflow_runs']
        run, = [row for row in runs if row['head_sha'] == COMMIT]
        ledger.update(runId=run['id'], runUrl=run['html_url'])
        save(ledger_path, ledger)
        package_dispatch[workflow] = dict(ledger, status=run['status'], conclusion=run['conclusion'])
    dispatch_path = core_folder / 'package-dispatch-observation.json'
    assert not dispatch_path.exists()
    dispatch_path.write_text(json.dumps(package_dispatch, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/dispatch-r100-preview-from-core.py', core_folder / 'package-dispatch-driver.py')
    package_folder = root / 'docs/validation/2026-11-07/clipboard-r100-windows-package'
    original_path = package_folder / 'verified-receipt.json'
    windows = json.loads(original_path.read_text('utf-8'))
    assert windows['passed'] and windows['sourceCommit'] == COMMIT
    assert windows['sourceFilesVerified'] == 338 and windows['allSourceBlobsMatchExactGitCommit']
    assert windows['signedDependencyFiles'] == 364 and windows['signedLicenseFiles'] == 53
    assert windows['guiTargetsRechecked'] == 4 and windows['existingCoreBinariesUnchanged'] == 19
    screenshot = package_folder / 'runtime.png'
    visual = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'screenshot': proof(screenshot),
              'actuallyViewed': True, 'scope': 'Actual deployed Windows first-launch dialog; Chinese text, action controls and ready receiver visible; full interaction and selectors remain separate'}
    visual_path = package_folder / 'visual-review.json'
    assert not visual_path.exists()
    visual_path.write_text(json.dumps(visual, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    qualified = dict(windows, originalVerifiedReceipt=proof(original_path),
                     visualReview=proof(visual_path), screenshotsViewed=True, screenshotsReviewed=1,
                     fourPlatformCoreEvidence=proof(core_path), fullNativeProtocolRegressionQualified=False)
    qualified_path = package_folder / 'qualified-receipt.json'
    assert not qualified_path.exists()
    qualified_path.write_text(json.dumps(qualified, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    distribution = root / 'dist/windows-preview-20261107-r100-clipboard'
    build_receipt = distribution / 'BUILD-RECEIPT.json'
    assert not build_receipt.exists()
    build_receipt.write_text(json.dumps(qualified, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    report_path = root / 'docs/ci-verification-20261107-r100.json'
    report = json.loads(report_path.read_text('utf-8'))
    assert report['sourceCommit'] == COMMIT and len(report['buildInputs']) == 210
    for row in report['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    report.update(observedUtc=visual['observedUtc'], nativeCoreEvidence=proof(core_path),
                  nativeCoreTargetsEach=23, nativeCoreRunners=4, nativeOriginalQtReports=88,
                  explicitDarwinExpectedFailureCount=2, clipboardQmlFourPlatformsQualified=True,
                  windowsPackage=qualified, windowsPackageEvidence=proof(qualified_path),
                  macosLinuxPackageDispatch=proof(dispatch_path),
                  fullNativeRegressionQualified=False)
    save(report_path, report)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index['windowsPreviewBeforeR100'] = index.get('windowsPreview')
    index.update(observedUtc=visual['observedUtc'], windowsPreview=qualified,
                 nativeCoreR100={'sourceCommit': COMMIT, 'evidence': proof(core_path),
                                 'runners': 4, 'coreTargetsEach': 23, 'qtReports': 88,
                                 'explicitDarwinExpectedFailures': 2},
                 previewPackageRunsR100=package_dispatch,
                 currentSourceStage='R100 four native cores and clipboard QML qualified; dual macOS compilation and Windows deployment verified; complete protocol and long tests remain pending',
                 releaseQualified=False, deliveryComplete=False)
    index['clipboardAvailabilityR100'].update(manifest=proof(report_path), nativeCoreEvidence=proof(core_path),
                                             nativeCoreQualified=True, nativeCIPending=True)
    index['packageRuntime'].update(windows='R100 actual ZIP relocated with system-only PATH; GUI, independent CLI, 16-channel duplex and original recovery/business suites passed',
                                   windowsZipSha256=windows['archiveSha256'])
    save(index_path, index)
    note = '''

## R100四平台完整核心与Windows当前部署包（2026-11-07）

- [x] 精确ed4f5cf的Windows、Ubuntu、macOS Apple Silicon/Intel各23核心通过；四份原CTest、88份Qt XML逐件收验，剪贴板进度不重读、草稿拒绝恢复及拖放/复制生产QML方法均实际PASS，发送8组编码边界均通过。双Mac各一条精确已知Darwin端口共享XFAIL明确保留，其余失败/跳过一律拒绝。
- [x] 新Windows实际ZIP含338份精确Git源码和GUI/独立CLI，构建绑定无工作重编译且程序字节未变；本机此前4个相关GUI回归/19个既有相同核心二进制范围保持，另有四平台CI各23核心原件。系统PATH/中文空格路径迁移、16通道双向、会话/排队/重试/最终确认/fail/overwrite及4→8恢复均通过，实际首次说明截图已查看。
- [x] 新包24个未变依赖的364部署文件和53许可逐件匹配公开摘要固定的验签原件；缓存归档/配方摘要重新核对，本次没有重新验签。当前Windows包和源码身份已更新，R98旧包及运行中的冻结24h输入保持原件。
- [x] 四平台核心通过后按精确ed4f5cf分别单次派发Mac/Linux部署流程；固定package-r100-20261107标签、210构建输入与真实运行身份已记录。采用已验核心作为并行构建门槛，部署迁移和完整协议结论分别保留，当前包下载不提前替换。
- [ ] 完整R99/R100协议终态仍按各自精确提交收验；Mac/Linux新部署包、Windows/Linux真实86400秒终态及完整资源趋势、完整编辑器/OS剪贴板预算、全部R6/原生交互、物理LAN/3×3、各平台长期、第三方对应源码独立重建和正式发布仍未完成。
'''
    plan_path = root / '开发计划与进度.md'

    # 日期：2026-11-07；当前表格只提升已收验子项；历史失败、完整协议、物理网络和长期要求不变。
    def plan_update(text):
        text = text.replace('当前阶段：R100已公开上传且双Mac实际编译已验；双Windows剪贴板子项通过，Windows/Linux长测运行，完整原生及交付继续。',
                            '当前阶段：R100四平台各23核心与双Mac编译已验，当前Windows部署包通过；完整协议、Windows/Linux长测及交付继续。', 1)
        text = text.replace('双Windows子项通过；精确源码`ed4f5cf`的[四平台运行42282812778](https://github.com/29583855/dukto-next/actions/runs/42282812778)已自动启动，双Mac实际GUI/CLI编译产物已验，完整原生运行资格尚待终态回归。',
                            '精确源码`ed4f5cf`的[四平台运行42282812778](https://github.com/29583855/dukto-next/actions/runs/42282812778)各23核心和88份Qt原件已验；剪贴板/草稿QML、双Mac实际GUI/CLI编译产物及当前Windows部署迁移通过，完整协议仍待终态收验。', 1)
        text = text.replace('| Windows | R100各4个相关GUI目标通过、其余19原测试二进制未变；生产QML的进度不重读/空值/最新正文发送通过；R98包已验 |',
                            '| Windows | R100云端23核心及本机4个相关GUI目标通过、其余19原测试二进制未变；当前R100实际包迁移/16通道/恢复通过 |', 1)
        text = text.replace('| Linux | R98独立186步干净编译、23核心及监听/退出专项通过；R98包双显示迁移和业务/333源码/132 ELF已验 | R100原生GUI、新部署包及最新长期 |',
                            '| Linux | R100云端23核心及剪贴板/草稿QML已验；R98独立干净构建和双显示部署包、20轮长测短验通过 | 完整协议、新部署包和真实24h终态 |', 1)
        text = text.replace('| macOS ARM / Intel | R100实际GUI/CLI编译产物和双架构已验；R98各23核心/退出专项，R96完整协议与双部署包已验 | R99原完整运行终态、R100完整原生回归及新部署包、完整交互和正式分发 |',
                            '| macOS ARM / Intel | R100各23核心/剪贴板和草稿QML/双架构GUI与CLI编译产物已验；R96含依赖双部署包已验 | R99/R100完整协议终态、新部署包、完整交互和正式分发 |', 1)
        text = text.replace('当前各平台可下载包保持原有提交身份，R100修正尚未进入已验部署包。',
                            '当前Windows部署包已更新为R100；Mac含依赖预览仍为R96、Linux为R98，最新Mac编译输出另有R100双架构下载。', 1)
        return text.rstrip() + note

    update(plan_path, plan_update)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note)
    windows_doc = root / 'docs/Windows独立预览包.md'
    intro = ('## 当前R100预览包（2026-11-07）\n\n'
             '`dist/windows-preview-20261107-r100-clipboard/DuktoNext-windows-x64-preview.zip`，SHA-256：`' + windows['archiveSha256'] + '`。'
             '精确源码`' + COMMIT + '`，338份应用源码全集与Git逐字节一致。新增发送UTF-8预检、拒绝保留草稿及剪贴板进度不重读，GUI/独立CLI和Qt5/OpenSSL依赖均在包内。\n\n'
             '实际ZIP在中文空格目录、仅系统PATH下通过GUI启动、CLI、16通道双向、会话/排队/重试/最终确认/fail/overwrite和4→8恢复。实际430×700首次说明截图已查看，中文、按钮和接收就绪正常。完整原生交互和选择器仍另验。\n\n'
             'R100四平台CI各23核心及88份Qt原件已收验；双Mac各保留一条明确Darwin XFAIL。完整协议和长期继续按真实终态收验。24个未变依赖的364部署文件、53许可按公开摘要固定的验签原件核对，本次未重新验签。'
             '[部署原件及独立视觉回执](validation/2026-11-07/clipboard-r100-windows-package/qualified-receipt.json)固定全部程序/来源；干净系统、对应第三方源码重建和正式签名发布未完成。R98冻结CLI长测不被此包替换。\n\n')
    update(windows_doc, lambda text: text.replace('当前R98采用精确b2e4659源码，包含当前接收分页、资源授信、服务器上传下载及恢复/冲突处理。',
                                                '当前R100采用精确ed4f5cf源码，包含发送预检、草稿恢复、剪贴板状态修正及服务器上传下载/恢复。', 1).replace(
                                                    '## 当前R98预览包（2026-11-07）', intro + '## R98预览包（历史，2026-11-07）', 1))

    # 日期：2026-11-07；README顶部展示当前结果，历史章节及全部精确来源记录继续保留。
    def readme_update(text):
        start = text.index('公开仓库为')
        end = text.index('新增[b9d9b78上传发送端确认]')
        current = ('公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R100精确源码`ed4f5cf`的四平台各23核心、88份Qt原报告和剪贴板/草稿QML已收验；双Mac各保留一条明确Darwin端口共享XFAIL。'
                   '[macOS双架构最新编译输出](docs/macOS独立预览包.md)为R100；[Windows当前部署包](docs/Windows独立预览包.md)已更新到R100，GUI/独立CLI迁移、16通道及恢复通过。'
                   'Mac含依赖预览包仍为R96，Linux为R98；完整协议、真实长期、物理网络及正式交付继续。见[计划](开发计划与进度.md)和[当前索引](docs/current-validation.json)。\n\n')
        return (text[:start] + current + text[end:]).rstrip() + note

    update(root / 'README.md', readme_update)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(r100NativeCore={'sourceCommit': COMMIT, 'evidence': proof(core_path),
                                'runners': 4, 'coreTargetsEach': 23, 'fullProtocolPending': True},
                 r100WindowsPackage={'sourceCommit': COMMIT, 'evidence': proof(qualified_path),
                                     'passed': True, 'archiveSha256': windows['archiveSha256']})
    state['r100PreviewPackages'] = package_dispatch
    save(state_path, state)
    shutil.copyfile(Path(__file__), package_folder / 'result-record-driver.py')
    shutil.copyfile(root / '.cache/prepare-r100-windows-package-drivers.py', package_folder / 'package-driver-preparation.py')
    names = {'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/Windows独立预览包.md', 'docs/ci-verification-20261107-r100.json', 'docs/current-validation.json',
             'docs/validation/2026-11-06/github-api-push-r100-compilation-linux-launch-small64.json'}
    for folder in (core_folder, package_folder):
        names.update(path.relative_to(root).as_posix() for path in folder.rglob('*')
                     if path.is_file() and path.suffix not in ('.zip', '.gz'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    listing = root / '.cache/r100-core-windows-package-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r100-core-windows-package-stage.nul').write_bytes(b'\0'.join(name.encode('utf-8') for name in names) + b'\0')
    stage = (root / '.cache/stage-r100-compilation-launch.py').read_bytes().replace(b'r100-compilation-launch', b'r100-core-windows-package')
    (root / '.cache/stage-r100-core-windows-package.py').write_bytes(stage)
    print(json.dumps({'explicitFilesPrepared': len(names), 'sourceCommit': COMMIT,
                      'nativeCoreRunners': 4, 'coreTargetsEach': 23,
                      'windowsPackageQualified': True, 'fullProtocolQualified': False}), flush=True)


if __name__ == '__main__':
    main()
