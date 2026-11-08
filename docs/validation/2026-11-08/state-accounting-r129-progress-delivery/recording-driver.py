"""日期：2026-11-08；按已收原件更新R129进度，保留待完成及旧失败。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；截图只能在实际查看后进入回执，复制不改变原始字节。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.csv', '.exit', '.png']:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


# 日期：2026-11-08；所有计数来自各自回执，编译、核心、协议、包内业务和公开下载分别记录。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.attempt)
    prepared = ROOT / ('.cache/r129-progress-' + args.attempt + '-prepared.json')
    assert not prepared.exists()
    runs = json.loads((ROOT / '.cache/r129-ci-runs.json').read_bytes())
    source = runs['sourceCommit']
    parent = runpy.run_path(str(ROOT / '.cache/publish-r120-native-delivery.py'))['git']('rev-parse', 'HEAD').decode().strip()
    index_name = 'docs/ci-verification-20261108-r129.json'
    index = json.loads((ROOT / index_name).read_bytes())
    for row in index['qualificationInputs']:
        raw = (ROOT / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256'] and (REPO / row['path']).read_bytes() == raw
    request = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))['request']
    observed = []
    for key in ['nativeRunId', 'packageRunId']:
        value = request('/repos/29583855/dukto-next/actions/runs/' + str(runs[key]))
        assert value['head_sha'] == source and value['run_attempt'] == 1
        observed.append({key: value[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']})
    folder = BASE + 'state-accounting-r129-progress-' + args.attempt
    output = ROOT / folder
    output.mkdir(exist_ok=False)
    for name in ['r129-ci-runs.json', 'r129-dispatch-build.yml.json', 'r129-dispatch-macos-package.yml.json']:
        shutil.copyfile(ROOT / '.cache' / name, output / name)
    shutil.copyfile(ROOT / '.cache/r129-bounded-source-review.json', output / 'bounded-source-review.json')
    folders = [folder]
    current = {}
    for suffix in ['full-native-core', 'macos-compiled', 'macos-package', 'native-terminal']:
        name = BASE + 'state-accounting-r129-' + suffix
        path = REPO / name / 'receipt.json'
        if path.exists():
            value = json.loads(path.read_bytes())
            assert value['sourceCommit'] == source
            current[suffix] = value
            copy(REPO / name, ROOT / name)
            folders.append(name)
    glibc_path = ROOT / '.cache/r129-glibc/receipt.json'
    glibc = json.loads(glibc_path.read_bytes()) if glibc_path.exists() else None
    if glibc is not None:
        assert glibc['passed'] and glibc['methodsPassed'] == 14 and glibc['qualificationInputsUnchanged'] == 295
        installed = json.loads((ROOT / '.cache/r129-glibc/installed-source.json').read_bytes())
        for row in index['qualificationInputs']:
            assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}
        runpy.run_path(str(ROOT / '.cache/prepare-r129-source.py'))['accounting'](ROOT / '.cache/r129-glibc/results/state-accounting-tests.xml')
        name = BASE + 'state-accounting-r129-glibc'
        copy(ROOT / '.cache/r129-glibc', ROOT / name)
        shutil.copyfile(ROOT / '.cache/validate-r129-glibc.py', ROOT / name / 'verification-driver.py')
        folders.append(name)
    core_count = sum(row['qualified'] for row in current.get('full-native-core', {}).get('records', []))
    package_count = sum(row['qualified'] for row in current.get('macos-package', {}).get('records', []))
    protocol_count = sum(row['qualified'] for row in current.get('native-terminal', {}).get('records', []))
    compiled = current.get('macos-compiled', {}).get('bothArchitecturesCompiledAndVerified', False)
    preview_path = ROOT / '.cache/r129-public-preview.json'
    public = False
    if preview_path.exists():
        preview = json.loads(preview_path.read_bytes())
        downloads = json.loads((ROOT / '.cache/r129-public-download-verification.json').read_bytes())
        assert preview['sourceCommit'] == downloads['sourceCommit'] == source
        assert preview['allAssetsMatchVerifiedPackages'] and downloads['anonymousDownloadsVerified']
        assert downloads['allDownloadedBytesMatchVerifiedPackages']
        public = True
        for name in ['r129-public-preview.json', 'r129-public-download-verification.json']:
            shutil.copyfile(ROOT / '.cache' / name, output / name)
    old_folders = [BASE + name for name in ['cli-state-session-r126-native-terminal',
                   'gui-state-session-r127-native-terminal', 'state-fixture-r128-native-terminal']]
    old_counts = {}
    explicit = {index_name, 'README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/已有状态占用计量.md', 'docs/预算域管理与配置.md'}
    for revision, name in zip([126, 127, 128], old_folders):
        copy(REPO / name, ROOT / name)
        terminal = json.loads((ROOT / name / 'receipt.json').read_bytes())
        old_counts[revision] = sum(row['qualified'] for row in terminal['records'])
        old_name = 'docs/ci-verification-20261108-r' + str(revision) + '.json'
        old = json.loads((ROOT / old_name).read_bytes())
        assert old['sourceCommit'] == terminal['sourceCommit']
        old.update(nativeRun=terminal['run'], nativeCoreRun=terminal['run'],
                   nativeTerminalJobsVerified=old_counts[revision],
                   nativeTerminalJobsCompleted=sum(row.get('status') == 'completed' for row in terminal['records']),
                   fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'])
        for row in old['receipts']:
            row['sha256'] = hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest()
        (ROOT / old_name).write_text(json.dumps(old, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        explicit.add(old_name)
    folders += old_folders
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source, 'parentCommit': parent,
              'runs': observed, 'nativeCoreJobsVerified': core_count, 'nativeProtocolJobsVerified': protocol_count,
              'bothMacosCompiled': compiled, 'macosPackageArchitecturesVerified': package_count,
              'independentGlibcAccountingQualified': glibc is not None,
              'publicPreviewVerified': public, 'previousProtocolJobsVerified': old_counts,
              'globalQuotaEnforced': False, 'automaticGcImplemented': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'recording-driver.py')
    index.update(sourceCommit=source, nativeRun=observed[0], macosPackageRun=observed[1],
                 nativeCoreJobsVerified=core_count, nativeTerminalJobsVerified=protocol_count,
                 nativeQualificationPending=core_count != 4 or protocol_count != 4,
                 fullNativeProtocolQualified=protocol_count == 4,
                 bothMacosCompiled=compiled, macosPackageArchitecturesVerified=package_count,
                 independentGlibcAccountingQualified=glibc is not None,
                 independentGlibcAccountingRows=14 if glibc is not None else 0,
                 independentGlibcQualificationPending=glibc is None,
                 observedUtc=result['observedUtc'])
    if public:
        index.update(publicPreviewUrl=preview['releaseUrl'], anonymousPublicDownloadsVerified=True)
        explicit.add('docs/macOS独立预览包.md')
    refs = {row['path'] for row in index['receipts']} | {name + '/receipt.json' for name in folders}
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in sorted(refs)]
    (ROOT / index_name).write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    preview_text = ('双Mac R129含依赖预览已公开并匿名下载核对。' if public else
                    'R129双Mac依赖包已验' + str(package_count) + '/2，现有公开下载仍R127。')
    summary = (f'R129精确{source[:8]}已公开，双Windows各35核心及14条计量已验，四原生核心已验{core_count}/4，'
               f'完整协议已验{protocol_count}/4；' + ('独立Ubuntu14条及POSIX分支通过。' if glibc is not None else '独立Ubuntu重建继续。')
               + preview_text + f'R128完整协议已验{old_counts[128]}/4；历史迁移、实际写前额度、自动GC与完整项目继续。')
    status = (f'- [x] 精确`{source}`已非强制公开；[四原生GUI/CLI及核心/协议]({observed[0]["html_url"]})和'
              f'[双Mac含依赖包]({observed[1]["html_url"]})已实际派发，核心已验{core_count}/4、完整协议{protocol_count}/4、依赖包{package_count}/2。'
              + preview_text + '\n')
    anchor = '- [ ] 精确R129公开提交的四原生GUI/CLI构建、35核心及完整协议和双Mac依赖包继续，现有可下载Mac预览仍为R127。'
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    # 日期：2026-11-08；只更新当前R129状态行，源始终固定，不把后来的结果改写成先前已完成。
    def plans(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：' + summary, text, count=1, flags=re.M)
        text = re.sub(r'^- \[x\] 精确`' + source + r'`已非强制公开；.*\n', '', text, flags=re.M)
        remaining = '- [ ] R129其余完整协议终态继续按精确原作业收验；普通历史迁移、写前额度、自动GC和完整项目验收继续。'
        selected = anchor if anchor in text else remaining
        assert selected in text
        text = text.replace(selected, status + (remaining if public else selected), 1)
        if glibc is not None:
            text = re.sub(r'^- \[ \] 独立Ubuntu已安装冻结源码并在新目录构建.*$',
                          '- [x] 独立Ubuntu新目录真实构建后14条计量全部通过，POSIX符号链接/FIFO及硬链接分支执行；安装源、295资格输入和程序前后保持。[Linux原件](docs/validation/2026-11-08/state-accounting-r129-glibc/receipt.json)。',
                          text, count=1, flags=re.M)
        text = re.sub(r'^- \[x\] 精确de0750fc已公开；四平台两项专项4/4、完整核心4/4。.*$',
                      f'- [x] 精确de0750fc已公开；四平台两项专项4/4、完整核心4/4。完整协议已按原件核验{old_counts[128]}/4，其余继续原作业；R126/R127旧夹具失败原件保持。',
                      text, count=1, flags=re.M)
        return text
    update('开发计划与进度.md', plans)
    update('docs/执行进度.md', lambda text: plans(text).replace('](docs/', ']('))
    update('README.md', lambda text: re.sub(r'^R129[^\n]*\n', summary + ' [本轮证据](docs/ci-verification-20261108-r129.json)。\n', text, count=1, flags=re.M))
    update('docs/已有状态占用计量.md', lambda text: text + '\n精确源码`' + source + '`：四原生核心已验'
           + str(core_count) + '/4，完整协议已验' + str(protocol_count) + '/4；[原生构建](' + observed[0]['html_url'] + ')、[Mac打包](' + observed[1]['html_url'] + ')。\n')
    update('docs/预算域管理与配置.md', lambda text: text if '[已有状态占用计量](已有状态占用计量.md)' in text else
           text + '\nR129新增`state root account`，对已绑定根的直接普通文件登记Unknown持久高水位；用法、取消/退出保持及单根范围见[已有状态占用计量](已有状态占用计量.md)。这不表示生产写前限制已生效。\n')
    review_line = ('- [x] 已复核本轮计量及若干增长容器的源代码上限；原生文件多选仍一次物化全部路径，完整选择器和任意规模选择的内存资格未授予。'
                   '[审查原件](docs/' + folder.split('docs/', 1)[1] + '/bounded-source-review.json)。\n')
    update('开发计划与进度.md', lambda text: text.replace('## R129已有状态持久计量（2026-11-08）\n',
           '## R129已有状态持久计量（2026-11-08）\n\n' + review_line, 1) if '已复核本轮计量及若干增长容器' not in text else text)
    update('docs/执行进度.md', lambda text: text.replace('## R129已有状态持久计量（2026-11-08）\n',
           '## R129已有状态持久计量（2026-11-08）\n\n' + review_line.replace('](docs/', ']('), 1) if '已复核本轮计量及若干增长容器' not in text else text)
    if public:
        rows = []
        packages = current['macos-package']
        assert packages['bothArchitecturesVerified'] and packages['screenshotsViewed']
        for row in packages['records']:
            archive, = [asset for asset in preview['assets'] if asset['name'] == row['archive']]
            rows.append('| ' + row['architecture'] + ' | [下载tar.gz](' + archive['downloadUrl'] + ') | `' + row['packageSha256'] + '` |')
        section = ('## R129含依赖开发预览\n\n精确源码`' + source + '`；[公开下载与四份附件]('
                   + preview['releaseUrl'] + ')。两架构包含GUI、独立CLI、Qt5/OpenSSL，Cocoa/高DPI、中文空格目录搬迁与各五项包内业务已验；四张截图已查看。开发adhoc签名，正式签名、公证与最低干净系统继续。\n\n'
                   + '| 架构 | 下载 | tar.gz SHA-256 |\n| --- | --- | --- |\n' + '\n'.join(rows)
                   + '\n\n本机副本：dist/macos-preview-20261108-r129-state-accounting/。命令行入口：`"Dukto Next.app/Contents/MacOS/dukto-cli" --help`。\n\n')
        update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n',
               '# macOS独立开发预览包\n\n' + section, 1).replace('## R127含依赖开发预览\n', '## R127含依赖开发预览（历史）\n', 1))
    for name in explicit:
        shutil.copyfile(ROOT / name, REPO / name)
    for name in folders:
        copy(ROOT / name, REPO / name)
    result.update(explicitFiles=sorted(explicit), evidenceFolders=folders)
    prepared.write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
