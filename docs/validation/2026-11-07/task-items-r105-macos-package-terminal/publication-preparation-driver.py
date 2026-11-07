"""日期：2026-11-07；双Mac部署与视觉核验完成后更新下载及进度，保留原失败和其余平台旧包身份。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

SOURCE = '4652f4dce23b014e18f2db56c6a75e81e76deafa'
LABEL = 'r105-delivery-evidence'


# 日期：2026-11-07；所有资格依赖真实原件，先验后改；发布步骤另有退出及远端整树屏障。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == SOURCE
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    compiled_path = base / 'task-items-r105-macos-compiled/receipt.json'
    package_path = base / 'task-items-r105-macos-package-terminal/qualified-receipt.json'
    glibc_path = base / 'state-use-r104-glibc-recheck/receipt.json'
    arm_path = base / 'state-use-r104-macos-arm-terminal/subset-verification.json'
    compiled = json.loads(compiled_path.read_text('utf-8'))
    package = json.loads(package_path.read_text('utf-8'))
    glibc = json.loads(glibc_path.read_text('utf-8'))
    arm = json.loads(arm_path.read_text('utf-8'))
    assert compiled['sourceCommit'] == package['sourceCommit'] == SOURCE
    assert compiled['bothArchitecturesCompiledAndVerified'] and package['bothArchitecturesVerified']
    assert package['screenshotsViewed'] and package['screenshotsReviewed'] == 4
    assert all(row['applicationSourceFiles'] == 348 and len(row['runtimeReports']) == 5 for row in package['packages'])
    assert glibc['passed'] and glibc['sourceCommit'] == arm['sourceCommit'] == '9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6'
    assert glibc['verifiedCoreTargets'] == 23 and glibc['verifiedOriginalQtXml'] == 22 and glibc['verifiedFrozenBuildInputs'] == 213
    assert arm['verificationPassedWithinExplicitSubset'] and len(arm['verifiedPassedProtocolReports']) == 46
    for origin, name in [('.cache/r105-task-items-published-tree-verification.json', 'source-publication-verification.json'),
                         ('.cache/r105-macos-package-dispatch.json', 'package-dispatch.json'),
                         ('.cache/r105-inflight-long-observation.json', 'inflight-long-observation.json')]:
        target = package_path.parent / name
        assert not target.exists()
        shutil.copyfile(root / origin, target)
    manifest_path = root / 'docs/ci-verification-20261107-r105.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    assert len(manifest['buildInputs']) == 213
    for row in manifest['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    core_path = base / 'task-items-r105-native-core/receipt.json'
    core = json.loads(core_path.read_text('utf-8')) if core_path.exists() else None
    if core:
        assert core['passed'] and core['sourceCommit'] == SOURCE and core['coreTargetsEach'] == 23
    manifest.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=SOURCE,
                    sourceCommitPending=False, macOSCompilationEvidence=proof(compiled_path),
                    macOSPackageEvidence=proof(package_path), macOSDeployedPackagesVerified=True,
                    r104IndependentUbuntuEvidence=proof(glibc_path), r104ArmFailureSubsetEvidence=proof(arm_path),
                    sourcePublicationEvidence=proof(package_path.parent / 'source-publication-verification.json'),
                    nativeCoreQualified=bool(core), nativeCIPending=True,
                    fullNativeRegressionQualified=False, releaseQualified=False, deliveryComplete=False)
    after_core_failure = base / 'task-items-r105-glibc-after-core/failure-verification.json'
    after_core_value = json.loads(after_core_failure.read_text('utf-8'))
    assert after_core_value['actualDriverExitCode'] == 1 and after_core_value['binaryUnchanged']
    assert after_core_value['coreAlreadyTerminated'] and not after_core_value['causeEstablished']
    manifest['independentUbuntuAfterCoreTimeoutEvidence'] = proof(after_core_failure)
    if core:
        manifest['nativeCoreEvidence'] = proof(core_path)
    save(manifest_path, manifest)
    packages = {row['architecture']: row for row in package['packages']}
    assert set(packages) == {'arm64', 'x86_64'}
    page = '# macOS独立开发预览包\n\n更新日期：2026-11-07。当前含依赖开发预览为R105，精确源码`' + SOURCE + '`；使用C++14、Qt5及CMake，两种架构均含GUI、独立CLI和Qt5/OpenSSL运行依赖。\n\n'
    page += '## 当前R105含依赖部署包\n\n[双架构原生部署及迁移工作流](' + package['run']['html_url'] + ')终态success。ZIP含tar.gz、SHA-256和运行原件，附件下载可能需要登录GitHub。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for architecture in ('arm64', 'x86_64'):
        row = packages[architecture]
        page += '| ' + architecture + ' | [下载](' + row['artifactUrl'] + ') | `' + row['sha256'] + '` |\n'
    page += '\n每包348份应用源码全集逐字节匹配精确Git提交；全部载荷、各71个框架链接、Mach-O架构和执行位已核验。包在中文空格新目录、仅系统PATH下实际运行，CLI不加载GUI框架；每包五份业务原报告通过：独立CLI、16通道双向、1/4/16覆盖、覆盖恢复及4→8恢复。Cocoa及150%/200%导航通过，四张实际启动/导航截图已查看。[原件与视觉收验](validation/2026-11-07/task-items-r105-macos-package-terminal/qualified-receipt.json)。\n\n'
    page += '先解压ZIP，再用tar保留框架链接和执行权限。Apple Silicon示例（Intel将arm64替换为x86_64）：\n\n```sh\nshasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256\ntar -xzf DuktoNext-macos-arm64-preview.tar.gz\ncd DuktoNext-macos-arm64-preview\nopen "Dukto Next.app"\n./dukto-cli --help\n```\n\n保留整个目录，CLI启动器与.app相邻；CLI独立运行不要求GUI启动。当前为adhoc签名开发预览，Developer ID、公证、最低/干净系统、完整GUI及选择器、各平台长期与正式发布继续验收。\n\n'
    page += '## R105原生编译归档\n\n以下是同提交的原始编译输出，仍需匹配运行依赖；直接运行优先使用上方含依赖包。\n\n| 架构 | 编译归档 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        page += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['sha256'] + '` |\n'
    page += '\n[编译回执](validation/2026-11-07/task-items-r105-macos-compiled/receipt.json)。完整原生协议仍按其自身终态收验；R104 Ubuntu及Apple Silicon原失败均保留，各47项中46项通过、task-items旧夹具失败。R105仅修正夹具，未声称修复生产传输缺陷或完成整体稳定性验收。\n\n'

    # 日期：2026-11-07；旧包及失败保留在历史区，当前下载入口只指向本轮实际验收包。
    def mac_page(text):
        assert text.startswith('# macOS独立开发预览包')
        old = text[text.index('## 当前R100含依赖部署包'):]
        return page + '## 历史版本与原始记录\n\n' + old

    update(root / 'docs/macOS独立预览包.md', mac_page)
    core_note = 'R105四runner各23核心/88份Qt及48行取消原件已核验；两条精确Darwin XFAIL保留。' if core else 'R105完整原生核心及协议仍按新运行原件收验，R104已通过的核心不代替新提交资格。'
    note = '''

## R105双Mac部署及独立Ubuntu核心终态（2026-11-07）

- [x] 精确4652f4d已上传且远端main/整树/213构建输入独立一致。双Mac GUI/独立CLI编译归档与官方/内部摘要、源码、Mach-O架构、执行位和许可通过。[最新下载](docs/macOS独立预览包.md)。
- [x] 双Mac含Qt5/OpenSSL部署包终态success，全部载荷、每包348份应用源码及71框架链接逐项核对；中文空格路径/系统PATH迁移、CLI不加载GUI、每包五项真实传输/恢复业务通过。Cocoa及150%/200%导航、中文覆盖通过，四张启动/导航原图已查看；当前macOS含依赖包更新到R105，Windows/Linux部署包继续保持R100。
- [x] R104独立Ubuntu完整复验真实exit0：实际构建、23核心/22XML、新维护互斥方法、真实八进程与POSIX权限/硬链接/符号链接拒绝，以及12项诊断/两项链接拒绝和服务通过。213份冻结构建输入匹配9c1e941；首次编译失败保留。[原件回执](docs/validation/2026-11-07/state-use-r104-glibc-recheck/receipt.json)。
- [x] R104 Apple Silicon终态failure已取原官方附件及job.log，47项协议中46份通过报告摘要一致，唯一task-items失败同为原空目录假设。该失败与Ubuntu原失败及R105独立Ubuntu90秒上传超时均保留；完整核心结束后的再次定向复查推进到16通道下载仍90秒超时，原因未定，两次均不能被核心通过覆盖。[Apple Silicon失败子集](docs/validation/2026-11-07/state-use-r104-macos-arm-terminal/subset-verification.json)、[再次超时](docs/validation/2026-11-07/task-items-r105-glibc-after-core/failure-verification.json)。
- [ ] CORE_NOTE 完整协议和独立Ubuntu逐项专项仍单独收验；正在运行的冻结86400秒不能按轮数授予长期资格。安全GC/磁盘配额、全部资源/公平性、完整R6/GUI与选择器、物理LAN/3×3、各平台长期、依赖源码重建、最低干净系统和正式签名分发继续。deliveryComplete=false、releaseQualified=false。
'''.replace('CORE_NOTE', core_note)

    # 日期：2026-11-07；当前表只替换已验证范围，R105包和R104核心使用各自精确身份。
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R105双Mac GUI/CLI编译与含依赖迁移包已验；R104独立Ubuntu23核心及POSIX专项通过，原协议失败/上传超时保留，完整交付继续。', text, count=1, flags=re.M)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R105精确4652f4d的双Mac GUI/CLI编译、含Qt5/OpenSSL部署及每包五项迁移业务已验，348份包内应用源码和全部载荷匹配Git。R104独立Ubuntu23核心/22XML及八进程POSIX专项通过；其Ubuntu/Apple Silicon完整协议原失败、R105独立Ubuntu上传超时保留。213份构建输入及原件见[当前清单](docs/ci-verification-20261107-r105.json)。新完整协议继续，Windows/Linux含依赖包仍为R100，整体未完成。' + text[end:]
        text = text.replace('R104双架构GUI/CLI编译、各23核心/维护互斥通过；R100部署/APFS另验', 'R105双架构GUI/CLI编译、部署/迁移各五业务、全部源码/载荷与四截图通过；完整协议另验', 1)
        text = text.replace('R104原生23核心及POSIX八进程维护互斥通过；完整协议作业failure，46项通过/1项夹具失败', 'R104原生及独立Ubuntu各23核心、POSIX八进程/诊断/服务通过；原完整协议作业failure保留', 1)
        text = text.replace('当前Windows、双Mac和Linux含依赖部署包仍为R100精确源码ed4f5cf', '当前双Mac含依赖部署包为R105精确4652f4d，Windows和Linux仍为R100精确ed4f5cf', 1)
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    for name in ['docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/macOS构建与验收.md']:
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: re.sub(r'^公开仓库为.*$', '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。最新R105精确4652f4d的[macOS Apple Silicon/Intel GUI与独立CLI](docs/macOS独立预览包.md)已原生编译、部署Qt5/OpenSSL并通过中文空格路径迁移及每包五项业务；包内348份应用源码及全部载荷核验一致，四张实际截图已查看。Windows/Linux含依赖预览仍为R100。R104独立Ubuntu23核心/22XML及POSIX八进程/诊断/服务通过；原协议夹具失败和独立Ubuntu上传超时均保留。完整GUI、协议、各平台长期与正式分发继续，见[计划](开发计划与进度.md)和[当前索引](docs/current-validation.json)。', text, count=1, flags=re.M))
    path = root / 'docs/current-validation.json'
    index = json.loads(path.read_text('utf-8'))
    index['previousMacOSPreviewBeforeR105'] = index['macOSPreview']
    index['previousMacPackagesBeforeR105'] = [row for row in index['packages'] if 'macos' in row.get('archive', '').lower()]
    index['packages'] = [row for row in index['packages'] if 'macos' not in row.get('archive', '').lower()] + package['packages']
    index['packageRuntime']['macOS'] = {'sourceCommit': SOURCE, 'runUrl': package['run']['html_url'],
                                     'bothArchitecturesVerified': True, 'evidence': proof(package_path)}
    index['macOSPreview'] = {'sourceCommit': SOURCE, 'runUrl': package['run']['html_url'],
                           'workflowConclusion': 'success', 'runtimeReportsEach': 5,
                           'bothArchitecturesVerified': True, 'screenshotsViewed': True,
                           'evidence': proof(package_path), 'adhocSigned': True,
                           'developerIdSigned': False, 'notarized': False, 'releaseQualified': False}
    index['macOSPreviewPending'] = {'sourceCommit': SOURCE, 'runId': package['run']['id'],
                                  'status': 'completed', 'workflowConclusion': 'success', 'originalEvidenceVerified': True}
    index['taskItemsFixtureR105'].update(manifest=proof(manifest_path), macOSPackageEvidence=proof(package_path),
                                      macOSCompilationEvidence=proof(compiled_path), nativeCoreQualified=bool(core),
                                      independentUbuntuAfterCoreTimeoutEvidence=proof(after_core_failure))
    index['stateUseR104'].update(independentUbuntuEvidence=proof(glibc_path), independentUbuntuCoreQualified=True,
                                originalArmJobConclusion='failure', armTerminalEvidence=proof(arm_path))
    index.update(observedUtc=manifest['observedUtc'], currentGuiSourceCommit=SOURCE, currentGuiSourceCommitPending=False,
                 currentSourceStage='R105 dual Mac deployed previews verified; R104 independent Ubuntu core and POSIX checks passed; original protocol failures and Ubuntu timeout retained; full qualification pending',
                 releaseQualified=False, deliveryComplete=False)
    save(path, index)
    path = root / '.cache/execution-current.json'
    state = json.loads(path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == SOURCE
    state.update(taskItemsFixtureR105=manifest, workingSourceStage=index['currentSourceStage'],
                 macOSDeliveryR105=proof(package_path), goalStatus='active', releaseQualified=False, deliveryComplete=False)
    save(path, state)
    shutil.copyfile(Path(__file__), package_path.parent / 'publication-preparation-driver.py')
    names = {'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/macOS构建与验收.md', 'docs/macOS独立预览包.md', 'docs/current-validation.json',
             'docs/ci-verification-20261107-r105.json', 'docs/validation/2026-11-06/github-api-push-r105-task-items.json'}
    folders = ['task-items-r105-macos-compiled', 'task-items-r105-macos-package-terminal',
               'state-use-r104-glibc-recheck', 'state-use-r104-macos-arm-terminal']
    if core:
        folders.append('task-items-r105-native-core')
    for folder in folders:
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*') if path.is_file()
                     and path.suffix in ('.json', '.xml', '.log', '.txt', '.sha256', '.py', '.png'))
    after_core = base / 'task-items-r105-glibc-after-core'
    if (after_core / 'driver-result.json').exists():
        names.update(path.relative_to(root).as_posix() for path in after_core.rglob('*') if path.is_file()
                     and path.suffix in ('.json', '.log', '.py'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    template = (root / '.cache/stage-r104-current-index.py').read_bytes()
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes(template.replace(b'r104-current-index', LABEL.encode()))
    print(json.dumps({'sourceCommit': SOURCE, 'verifiedMacPackages': 2, 'explicitFiles': len(names),
                      'nativeCoreQualified': bool(core), 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
