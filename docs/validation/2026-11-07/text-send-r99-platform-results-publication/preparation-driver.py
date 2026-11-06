"""日期：2026-11-07；汇总已验Linux部署包及R99双Mac编译结果，原生协议和长期结果继续待验。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；只由真实回执更新当前入口，所有源码输入保持a316，历史观察和在途任务不覆盖。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    commit = 'a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == commit
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    mac_path = root / 'docs/validation/2026-11-07/text-send-r99-macos-compiled/receipt.json'
    mac = json.loads(mac_path.read_text('utf-8'))
    assert mac['sourceCommit'] == commit and mac['bothArchitecturesCompiledAndVerified']
    linux_path = root / 'docs/validation/2026-11-07/exit-state-r98-linux-package-terminal/qualified-receipt.json'
    linux = json.loads(linux_path.read_text('utf-8'))
    assert linux['passed'] and linux['package']['screenshotsViewed']
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    run = request('/repos/29583855/dukto-next/actions/runs/42276738981')
    assert run['head_sha'] == commit
    run_value = {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')}
    observed = datetime.now(timezone.utc).isoformat()
    report_path = root / 'docs/ci-verification-20261107-r99.json'
    report = json.loads(report_path.read_text('utf-8'))
    assert len(report['buildInputs']) == 210
    for row in report['buildInputs']:
        raw = subprocess.check_output(['git', 'show', commit + ':' + row['path']], cwd=checkout)
        assert raw == (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    report.update(observedUtc=observed, nativeRun=run_value,
                  macosCompilationVerified=True, macosCompilationEvidence=helper['proof'](mac_path),
                  nativeCIPending=True)
    helper['save'](report_path, report)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(textSendGuardR99=report, macOSCompilationR99=dict(mac, evidence=helper['proof'](mac_path)),
                 observedUtc=observed,
                 currentSourceStage='R99 dual Mac GUI/CLI compilation outputs verified; R98 Linux deployed package and both displays qualified; R99 full native regression and R98 independent Ubuntu tests pending',
                 deliveryComplete=False, releaseQualified=False)
    helper['save'](index_path, index)
    compiled = '''## R99最新编译产物（2026-11-07）

精确源码`a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38`已上传；[原生CI 42276738981](https://github.com/29583855/dukto-next/actions/runs/42276738981)的ARM64、Intel编译步骤均成功。两份实际归档、源码提交、Mach-O架构和执行权限已核验，包含GUI与独立CLI。

| 架构 | 编译产物附件 |
| --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42276738981/artifacts/13533422500) |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42276738981/artifacts/13534425181) |

[编译原件回执](validation/2026-11-07/text-send-r99-macos-compiled/receipt.json)绑定实际程序摘要。本节归档需要匹配的Qt5/OpenSSL运行依赖；下方独立预览包已经部署依赖，其源码保持R96。R99完整原生回归尚在运行，编译产物不授予整轮测试通过或正式发布资格。

'''
    helper['update'](root / 'docs/macOS独立预览包.md', lambda text: text.replace('## 下载与校验\n', compiled + '## 下载与校验\n', 1))
    helper['update'](root / 'docs/macOS构建与验收.md', lambda text: text.replace(
        text.split('\n\n', 2)[1],
        '更新日期：2026-11-07，计划v0.99。最新a316e4a的双Mac GUI/独立CLI编译及两份归档已核验；[编译附件与已有部署包](macOS独立预览包.md)分别记录来源。R98各23核心和退出专项、R96完整协议及双包已有独立证据；R99完整原生回归继续。完整交互、长期和正式交付尚未完成。', 1))
    helper['update'](root / 'docs/构建验证摘要.md', lambda text: text.replace(
        text.split('\n\n', 2)[1],
        '更新日期：2026-11-07，计划v0.99。最新a316e4a双Mac GUI/CLI编译归档已验；R98 Linux部署包23核心及X11/Wayland迁移通过，下载已更新。R99四平台完整回归、R98独立Ubuntu完整测试和Windows 24h继续；整体及正式发布未完成。', 1))
    note = ('\n\n## R99双Mac实际编译及平台结果公开（2026-11-07）\n\n'
            '- [x] a316e4a已公开，210份构建输入与精确Git对象逐字节一致。双Mac GUI/CLI编译产物已下载，归档SHA、源码提交、Mach-O架构与执行权限通过。ARM64附件13533422500、Intel附件13534425181，入口见macOS预览包文档。\n'
            '- [x] R98 Linux包42266702018已收验并更新下载；333源码、708文件、132 ELF和双显示实际迁移/业务、截图均已核验。\n'
            '- [ ] R99四平台完整原生运行42276738981尚未收验终态；独立R98 Ubuntu完成186步干净编译、完整测试仍在运行。Windows真实86400秒长测继续，不用轮数代替完整时长。\n'
            '- [ ] 当前只有文档及证据更新，生产/测试210输入未变；文档提交使用[skip ci]避免重复启动相同源码矩阵。源码原运行与长期任务继续，完整交付/正式发布保持false。\n')
    for name in ('开发计划与进度.md', 'docs/执行进度.md'):
        # 日期：2026-11-07；更新当前摘要，已公开启动补记的历史语境保持，不将尚待收验的任务勾选。
        def transform(text):
            if name == '开发计划与进度.md':
                text = text.replace('当前阶段：R99发送文本转换前检查及草稿拒绝重试双Windows通过；原生R99、长期及完整交付继续。',
                                    '当前阶段：R99双Mac GUI/CLI实际编译已验、R98 Linux部署包已更新；R99完整回归、独立Ubuntu及长期/完整交付继续。', 1)
                text = text.replace('R99原生Mac/Linux尚未授予通过。', 'R99双Mac实际编译归档已验；完整原生测试结论尚待原件收验。', 1)
                text = text.replace('| macOS ARM / Intel | R98各23核心/四状态/16组及重复监听退出通过；R96各46协议和双包各五业务已验 |',
                                    '| macOS ARM / Intel | R99实际GUI/CLI编译归档已验；R98各23核心/退出专项、R96各46协议及部署包已验 |', 1)
            return text + note
        helper['update'](root / name, transform)
    helper['update'](root / 'README.md', lambda text: text +
                     '\n\n2026-11-07 R99：最新a316e4a的Apple Silicon/Intel GUI及独立CLI编译产物均已核验，附件见[macOS构建与下载](docs/macOS独立预览包.md)。完整原生测试及长期验证继续，整体未完成。\n')
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(r99TextSendGuard=report, r99MacCompiled=dict(mac, evidence=helper['proof'](mac_path)),
                 workingSourceStage=index['currentSourceStage'], goalStatus='active',
                 deliveryComplete=False, releaseQualified=False)
    helper['save'](state_path, state)
    names = ['docs/ci-verification-20261107-r98.json', 'docs/ci-verification-20261107-r99.json',
             'docs/current-validation.json', '开发计划与进度.md', 'docs/执行进度.md',
             'docs/构建验证摘要.md', 'docs/Linux独立预览包.md', 'docs/macOS构建与验收.md',
             'docs/macOS独立预览包.md', 'README.md',
             'docs/validation/2026-11-06/github-api-push-r99-text-send.json']
    for relative in ('docs/validation/2026-11-07/exit-state-r98-linux-package-terminal',
                     'docs/validation/2026-11-07/text-send-r99-public-source-launch',
                     'docs/validation/2026-11-07/text-send-r99-macos-compiled'):
        names.extend(path.relative_to(root).as_posix() for path in (root / relative).rglob('*')
                     if path.is_file() and path.suffix != '.zip')
    publication_folder = root / 'docs/validation/2026-11-07/text-send-r99-platform-results-publication'
    publication_folder.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), publication_folder / 'preparation-driver.py')
    names.append((publication_folder / 'preparation-driver.py').relative_to(root).as_posix())
    names = sorted(set(names))
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / '.cache/r99-platform-results-publish-files.json').write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r99-platform-results-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    stage = (root / '.cache/stage-r99-text-send.py').read_text('utf-8-sig')
    stage = stage.replace('r99-text-send-publish-files.json', 'r99-platform-results-publish-files.json').replace('r99-text-send-stage.nul', 'r99-platform-results-stage.nul')
    (root / '.cache/stage-r99-platform-results.py').write_text(stage, 'utf-8')
    print(json.dumps({'publishFiles': len(names), 'unchangedBuildInputs': 210,
                      'macArchitecturesCompiled': 2, 'linuxPackageQualified': True}), flush=True)


if __name__ == '__main__':
    main()
