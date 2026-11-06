"""日期：2026-11-07；实际查看双显示截图后发布R98 Linux包资格，R99 GUI及整体资格保持独立。"""
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import shutil


# 日期：2026-11-07；绑定未修改的收验原件和实际审阅截图，只提升已完成的包迁移子项。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    folder = root / 'docs/validation/2026-11-07/exit-state-r98-linux-package-terminal'
    original = folder / 'verified-summary.json'
    value = json.loads(original.read_text('utf-8'))
    assert value['passed'] and value['run']['conclusion'] == 'success'
    assert value['sourceCommit'] == 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    assert value['core']['coreTargets'] == 23 and value['package']['applicationSourceFiles'] == 333
    assert len(value['runtimeReports']) == 2 and all(row['businessReports'] == 3 for row in value['runtimeReports'])
    review = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': value['sourceCommit'],
              'screenshotsViewed': True, 'screenshotsReviewed': 2,
              'originalVerifiedSummary': helper['proof'](original),
              'screenshots': [helper['proof'](folder / 'build' / name) for name in ('package-x11.png', 'package-wayland.png')],
              'observation': 'Both actual package first-launch dialogs show Chinese text and controls without clipping; desktop interaction beyond these screenshots is not qualified.',
              'releaseQualified': False, 'deliveryComplete': False}
    review_path = folder / 'visual-review.json'
    assert not review_path.exists()
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    package = dict(value['package'], screenshotsViewed=True, screenshotsReviewed=2,
                   visualReview=helper['proof'](review_path))
    qualification = {'sourceCommit': value['sourceCommit'], 'run': value['run'], 'package': package,
                     'originalVerifiedSummary': helper['proof'](original), 'visualReview': helper['proof'](review_path),
                     'passed': True, 'cleanSystemQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    path = folder / 'qualified-receipt.json'
    assert not path.exists()
    path.write_text(json.dumps(qualification, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), folder / 'qualification-driver.py')
    receipt_path = root / 'docs/ci-verification-20261107-r98.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    receipt.update(linuxNewPackagePending=False, linuxNewPackageRun=value['run'],
                   linuxNewPackageOriginalsVerified=True, linuxNewPackageScreenshotsViewed=2,
                   linuxNewPackageEvidence=helper['proof'](path))
    receipt.setdefault('runs', {})['linuxPackage'] = value['run']
    helper['save'](receipt_path, receipt)
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    previous = [row for row in index['packages'] if 'linux' in row.get('archive', '').lower()]
    index.setdefault('previousPackages', []).extend(previous)
    index['packages'] = [row for row in index['packages'] if 'linux' not in row.get('archive', '').lower()] + [package]
    index['packageRuntime']['linux'] = {'sourceCommit': value['sourceCommit'], 'runUrl': value['run']['html_url'],
                                       'bothDisplaysVerified': True, 'evidence': helper['proof'](path)}
    index['linuxPreviewR98'] = qualification
    index['nativeRegressionGuardR98'] = receipt
    index['observedUtc'] = review['observedUtc']
    helper['save'](index_path, index)
    introduction = '''# Linux 独立预览包

更新日期：2026-11-07。当前包源码为`b2e4659b347c65eef24c8e568e07e96a2d6ff2d7`（R98），包含GUI和可独立运行的CLI，采用C++14、Qt5和CMake。目标为Ubuntu24.04或更新的x86_64 glibc环境，要求glibc2.39起及系统CJK字体。

## 当前可下载包（2026-11-07）

[下载x86_64 glibc预览包](https://github.com/29583855/dukto-next/actions/runs/42266702018/artifacts/13532504491)（GitHub附件可能需要登录）。ZIP内含tar.gz、SHA及原始证据。内部tar.gz SHA-256：`3abe49bf08c653ab7c7c10fe66fd898d4fe95e060f500b4e061145dc6d80bd7e`。

333份应用源码全集逐字节匹配精确Git提交，708文件、2链接和132 ELF均已核验；23项核心测试、四种退出状态和原16组并行处置通过。实际Xvfb/X11、Weston/Wayland迁移各自通过16通道双向、1/4/16覆盖和4→8恢复，双显示各三份业务报告均已核验。两张包首次启动截图已查看，中文说明和控件正常。

[包资格回执](validation/2026-11-07/exit-state-r98-linux-package-terminal/qualified-receipt.json)绑定原始报告、截图和程序摘要。本机归档：`dist/linux-preview-20261107-r98-exit-state`。GUI需系统CJK字体，例如fonts-wqy-zenhei。

该包为R98，尚未包含R99发送文本预检及拒绝保留草稿修复。Xvfb/Weston迁移通过不替代物理桌面、干净系统、完整第三方源码或正式发布验收；完整项目继续未完成。

'''
    linux_path = root / 'docs/Linux独立预览包.md'
    helper['update'](linux_path, lambda text: introduction + text[text.index('## 构建依赖'):]
                     + '\n\n## R98替换前的下载入口（历史）\n\n'
                     + text[text.index('当前5857073'):text.index('## 构建依赖')])
    note = ('\n\n## R98 Linux部署包终态收验（2026-11-07）\n\n'
            '- [x] 原生打包42266702018终态success，333份源码逐字节匹配b2e4659；708文件、2链接和132 ELF已验。\n'
            '- [x] 23核心、四种退出状态及原16组通过；X11/Wayland实际迁移各三份传输业务报告已验，两张首次启动截图已查看。\n'
            '- [x] Linux下载入口更新为R98，原收验记录未覆盖；R99 GUI、独立Ubuntu干净构建、24h及完整交付仍按各自实际证据验收。\n')
    for name in ('开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md'):
        # 日期：2026-11-07；仅替换当前摘要中的Linux包状态，历史在途观察继续保留。
        def transform(text):
            if name == '开发计划与进度.md':
                text = text.replace('| Linux | R96 Ubuntu/Alpine各23核心及46协议；R97独立退出专项通过 | R98独立干净构建、Linux包42266702018/X11/Wayland；R99原生GUI及最新长期 |',
                                    '| Linux | R98部署包23核心、四状态/16组及X11/Wayland迁移各三业务通过；333源码/132 ELF已验、截图已查看 | R98独立干净构建；R99原生GUI及最新长期 |', 1)
                text = text.replace('旧Linux CI及独立构建继续', '独立Ubuntu构建继续，Linux R98包已收验', 1)
            return text + note
        helper['update'](root / name, transform)
    helper['update'](root / 'README.md', lambda text: text +
                     '\n\n2026-11-07：Linux独立预览包已更新为R98（b2e4659），23核心及X11/Wayland迁移和传输原件已验；下载与精确范围见[Linux预览包](docs/Linux独立预览包.md)。R99 GUI修复及完整项目继续验收。\n')
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state['r98LinuxPackage'] = dict(qualification, terminalPending=False, originalEvidencePending=False)
    helper['save'](state_path, state)
    print(json.dumps({'linuxPackageSource': value['sourceCommit'], 'screenshotsViewed': 2,
                      'downloadUpdated': True, 'fullDeliveryComplete': False}), flush=True)


if __name__ == '__main__':
    main()
