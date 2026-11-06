"""日期：2026-11-07；发布R100双Mac真实编译与Ubuntu长测启动证据，完整运行仍按终态验收。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
RUN = 42282812778


# 日期：2026-11-07；仅把精确已验子项写入文档和显式发布集合，原编码、BOM、换行及失败证据保持。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == COMMIT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    mac_path = root / 'docs/validation/2026-11-07/clipboard-r100-macos-compiled/receipt.json'
    mac = json.loads(mac_path.read_text('utf-8'))
    assert mac['sourceCommit'] == COMMIT and mac['bothArchitecturesCompiledAndVerified']
    assert {row['architecture'] for row in mac['packages']} == {'arm64', 'x86_64'}
    linux_path = root / 'docs/validation/2026-11-07/linux-r98-stability-launch/receipt.json'
    linux = json.loads(linux_path.read_text('utf-8'))
    assert linux['passed'] and linux['shortRoundsPassed'] == 20 and linux['allFrozenInputsUnchanged']
    assert linux['longObservedStatus'] == 'running' and not linux['longTestQualified']
    assert linux['frozenFilesVerified'] == 71 and linux['runtimeDependenciesVerified'] == 25
    ledger = json.loads((root / '.cache/r100-native-dispatch.json').read_text('utf-8'))
    assert ledger['sourceCommit'] == COMMIT and ledger['runId'] == RUN and ledger['reusedExistingRun']
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    assert request(base + '/git/ref/heads/main')['object']['sha'] == COMMIT
    run = request(base + '/actions/runs/' + str(RUN))
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    assert run['head_sha'] == COMMIT and len(jobs) == 4
    folder = root / 'docs/validation/2026-11-07/clipboard-r100-publication'
    folder.mkdir(exist_ok=False)
    for name in ('dispatch-r100-native.py', 'prepare-r100-native-collectors.py',
                 'collect-r100-native-terminal.py', 'dispatch-r100-preview-packages.py'):
        shutil.copyfile(root / '.cache' / name, folder / name)
    shutil.copyfile(root / '.cache/r100-native-dispatch.json', folder / 'native-dispatch.json')
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(),
                   'sourceCommit': COMMIT, 'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                   'jobs': [{k: row[k] for k in ('id', 'name', 'status', 'conclusion', 'steps')} for row in jobs],
                   'sourceUploadVerified': True, 'duplicateDispatchPerformed': False,
                   'fullNativeRegressionQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    (folder / 'native-observation.json').write_text(json.dumps(observation, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    report_path = root / 'docs/ci-verification-20261107-r100.json'
    report = json.loads(report_path.read_text('utf-8'))
    assert len(report['buildInputs']) == 210
    for row in report['buildInputs']:
        raw = subprocess.check_output(['git', 'show', COMMIT + ':' + row['path']], cwd=checkout)
        assert raw == (root / row['path']).read_bytes() and hashlib.sha256(raw).hexdigest() == row['sha256']
    report.update(observedUtc=observation['observedUtc'], sourceCommit=COMMIT,
                  nativeCIRequested=True, nativeCIPending=True, nativeRun=observation['run'],
                  nativeObservation=proof(folder / 'native-observation.json'),
                  nativeDispatch=proof(folder / 'native-dispatch.json'),
                  macosCompilation=proof(mac_path), fullNativeRegressionQualified=False)
    save(report_path, report)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index['previousProductionBeforeR100'] = {k: index[k] for k in ('productionCommit', 'testCommit')}
    index.update(observedUtc=observation['observedUtc'], productionCommit=COMMIT, testCommit=COMMIT,
                 currentSourceCommit=COMMIT, currentGuiSourceCommitPending=False,
                 currentSourceStage='R100 published; both macOS GUI/CLI compilation outputs verified; complete native regression pending; independent R98 Ubuntu soak started after 20 rounds',
                 macOSCompilationR100={'sourceCommit': COMMIT, 'packages': mac['packages'], 'evidence': proof(mac_path),
                                      'matchingQt5OpenSSLRequired': True, 'deployedPreviewSourceUnchanged': True},
                 currentLinuxLong={'sourceCommit': linux['sourceCommit'], 'binarySha256': linux['binarySha256'],
                                   'shortRoundsPassed': 20, 'durationRequestedSeconds': 86400,
                                   'terminalPending': True, 'evidence': proof(linux_path)},
                 releaseQualified=False, deliveryComplete=False)
    index['clipboardAvailabilityR100'].update(manifest=proof(report_path), sourceCommit=COMMIT,
                                             nativeCIPending=True, nativeRun=observation['run'])
    save(index_path, index)
    mac_section = '''## R100最新编译产物（2026-11-07）

精确源码`ed4f5cf08c96f04671e49e5138eda8ce1790ead3`已上传公开仓库；[四平台CI 42282812778](https://github.com/29583855/dukto-next/actions/runs/42282812778)已自动启动，Apple Silicon与Intel的实际编译、归档和附件上传步骤均成功。两份GUI/独立CLI归档的GitHub摘要、内部tar摘要、源码提交、Mach-O架构及执行权限已逐件核验。

| 架构 | 最新编译产物 |
| --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42282812778/artifacts/13535778206) |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42282812778/artifacts/13535669142) |

[R100编译原件回执](validation/2026-11-07/clipboard-r100-macos-compiled/receipt.json)绑定实际GUI和CLI摘要。这些归档需要匹配的Qt5/OpenSSL运行依赖；下方含依赖预览包保持已验R96。R100完整原生回归仍待终态和原件收验，编译成功不授予整轮测试或正式发布资格。

'''
    mac_doc = root / 'docs/macOS独立预览包.md'
    update(mac_doc, lambda text: text.replace('## R99最新编译产物（2026-11-07）', mac_section + '## R99编译记录（2026-11-07）', 1))
    note = '''

## R100公开上传、双Mac编译与Linux长测启动（2026-11-07）

- [x] 138份显式文件严格暂存/编码/换行核验后提交，`ed4f5cf08c96f04671e49e5138eda8ce1790ead3`整树及远端main逐SHA确认。复用自动触发的四平台运行42282812778，210构建输入与Git对象逐件一致，没有重复派发。
- [x] Apple Silicon和Intel实际GUI/独立CLI均编译成功；附件13535778206/13535669142下载后按ZIP摘要、内部tar摘要、源码提交、Mach-O架构和执行权限核验。最新下载见macOS文档；编译输出要求匹配Qt5/OpenSSL，含依赖部署包仍为R96。
- [x] 独立Ubuntu的冻结R98 CLI完成资源采样自检和20轮16通道双向原长测短验；71份冻结文件与25份实际系统动态依赖前后启动核验一致。已实际进入86400秒阶段，只公开不可变启动快照。
- [ ] R100完整四平台回归和新部署包、R99原完整运行终态、Windows/Linux真实24小时终态及资源趋势仍待收验。Linux本轮只绑定R98 CLI，不授予R100 GUI、任意增长或磁盘GC资格；完整R6/编辑器及系统剪贴板预算/物理LAN与3×3/各平台长期/第三方源码重建/正式发布继续。
'''
    plan = root / '开发计划与进度.md'
    def revise_plan(text):
        text = text.replace('当前阶段：R100剪贴板进度不重读双Windows通过，R98独立Ubuntu干净构建已验；最新原生及完整交付继续。',
                            '当前阶段：R100已公开上传且双Mac实际编译已验；双Windows剪贴板子项通过，Windows/Linux长测运行，完整原生及交付继续。', 1)
        text = text.replace('双Windows子项通过，R100原生Mac/Linux资格尚待实际回归。',
                            '双Windows子项通过；精确源码`ed4f5cf`的[四平台运行42282812778](https://github.com/29583855/dukto-next/actions/runs/42282812778)已自动启动，双Mac实际GUI/CLI编译产物已验，完整原生运行资格尚待终态回归。', 1)
        text = text.replace('| macOS ARM / Intel | R99实际GUI/CLI编译产物已验；R98各23核心/退出专项，R96完整协议与双部署包已验 | R99完整原运行终态、R100原生回归及新部署包、完整交互和正式分发 |',
                            '| macOS ARM / Intel | R100实际GUI/CLI编译产物和双架构已验；R98各23核心/退出专项，R96完整协议与双部署包已验 | R99原完整运行终态、R100完整原生回归及新部署包、完整交互和正式分发 |', 1)
        text = text.replace('| 运行中 | R98 Windows冻结CLI的86400秒测试真实运行；旧R99精确源码完整协议继续 | 必须取得真实终态后核验，不以轮数或新GUI修改转授长期资格 |',
                            '| 运行中 | R98 Windows冻结CLI的86400秒测试继续；独立Ubuntu采样/20轮通过后也实际进入86400秒阶段；R99/R100原生回归继续 | 必须取得真实终态后核验，不以轮数或新GUI修改转授长期资格 |', 1)
        return text.rstrip() + note + '\n'
    update(plan, revise_plan)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note + '\n')
    update(root / 'README.md', lambda text: text.rstrip() + note + '\n')
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state['r100MacCompiled'] = {'sourceCommit': COMMIT, 'evidence': proof(mac_path), 'packages': mac['packages']}
    state['r98LinuxLong'] = {'sourceCommit': linux['sourceCommit'], 'execSession': 67868,
                            'driver': '.cache/start-current-linux-r98-long.py',
                            'evidence': 'docs/validation/2026-11-07/current-linux-r98-long',
                            'publicEvidence': proof(linux_path), 'terminalPending': True,
                            'smokeRoundsPassed': 20, 'durationRequestedSeconds': 86400}
    save(state_path, state)
    shutil.copyfile(Path(__file__), folder / 'publication-preparation-driver.py')
    names = {'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/macOS独立预览包.md', 'docs/ci-verification-20261107-r100.json', 'docs/current-validation.json',
             'docs/validation/2026-11-06/github-api-push-r100-clipboard-source.json'}
    for directory in (folder, mac_path.parent, linux_path.parent):
        names.update(path.relative_to(root).as_posix() for path in directory.rglob('*') if path.is_file())
    names = sorted(names)
    for name in names:
        source, target = root / name, checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert source.read_bytes() == target.read_bytes()
    listing = root / '.cache/r100-compilation-launch-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r100-compilation-launch-stage.nul').write_bytes(b'\0'.join(name.encode('utf-8') for name in names) + b'\0')
    stage = (root / '.cache/stage-r100-clipboard.py').read_bytes().replace(b'r100-clipboard', b'r100-compilation-launch')
    stage = stage.replace(b'2026-11-06', b'2026-11-07').replace(b'R95', b'R100')
    (root / '.cache/stage-r100-compilation-launch.py').write_bytes(stage)
    print(json.dumps({'sourceCommit': COMMIT, 'explicitFilesPrepared': len(names),
                      'macArchitecturesVerified': 2, 'linuxShortRoundsPassed': 20,
                      'nativeWholeQualified': False, 'longTestsQualified': False}), flush=True)


if __name__ == '__main__':
    main()
