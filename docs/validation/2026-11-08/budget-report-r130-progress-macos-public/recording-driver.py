"""日期：2026-11-08；增量冻结本轮精确原件、原失败和未完成作业，再更新可复核进度。"""
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


# 日期：2026-11-08；所有collector先结束，再调用此脚本，避免回执变化后仍沿用旧摘要。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--attempt', required=True)
    args = parser.parse_args()
    assert re.fullmatch('[a-z0-9-]+', args.attempt)
    target = ROOT / ('.cache/r130-progress-' + args.attempt + '-prepared.json')
    assert not target.exists()
    helper = runpy.run_path('.cache/prepare-r130-source.py')
    copy = helper['copy']
    old_folders, explicit, counts = helper['previous']()
    runs = json.loads((ROOT / '.cache/r130-ci-runs.json').read_bytes())
    source = runs['sourceCommit']
    index_name = 'docs/ci-verification-20261108-r130.json'
    index = json.loads((ROOT / index_name).read_bytes())
    git_helper = runpy.run_path('.cache/publish-r120-native-delivery.py')
    git, tree, blob = git_helper['git'], git_helper['tree'], git_helper['blob']
    source_tree = tree(source)
    for row in index['qualificationInputs']:
        raw = (ROOT / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert raw == (REPO / row['path']).read_bytes() and blob(raw) == source_tree[row['path']]
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    observed = []
    for key in ['nativeRunId', 'packageRunId']:
        value = request('/repos/29583855/dukto-next/actions/runs/' + str(runs[key]))
        assert value['head_sha'] == source and value['run_attempt'] == 1
        observed.append({key: value[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']})
    folder = BASE + 'budget-report-r130-progress-' + args.attempt
    output = ROOT / folder
    output.mkdir(exist_ok=False)
    for name in ['r130-ci-runs.json', 'r130-source-publication.json', 'r130-dispatch-build.yml.json', 'r130-dispatch-macos-package.yml.json']:
        shutil.copyfile(ROOT / '.cache' / name, output / name)
    folders = old_folders + [folder]
    current = {}
    for suffix in ['full-native-core', 'native-terminal', 'macos-compiled', 'macos-package']:
        name = BASE + 'budget-report-r130-' + suffix
        path = REPO / name / 'receipt.json'
        if path.exists():
            receipt = json.loads(path.read_bytes())
            assert receipt['sourceCommit'] == source
            current[suffix] = receipt
            copy(REPO / name, ROOT / name)
            folders.append(name)
    glibc_path = ROOT / '.cache/r130-glibc/receipt.json'
    glibc = json.loads(glibc_path.read_bytes()) if glibc_path.exists() else None
    if glibc is not None:
        assert glibc['passed'] and glibc['methodsPassed'] == 4 and glibc['qualificationInputsUnchanged'] == 295
        actual = json.loads((ROOT / '.cache/r130-glibc/installed-source.json').read_bytes())
        for row in index['qualificationInputs']:
            assert actual['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}
        name = BASE + 'budget-report-r130-glibc'
        copy(ROOT / '.cache/r130-glibc', ROOT / name)
        shutil.copyfile(ROOT / '.cache/validate-r130-glibc.py', ROOT / name / 'verification-driver.py')
        folders.append(name)
    core = sum(row['qualified'] for row in current.get('full-native-core', {}).get('records', []))
    protocol = sum(row['qualified'] for row in current.get('native-terminal', {}).get('records', []))
    package = sum(row['qualified'] for row in current.get('macos-package', {}).get('records', []))
    compiled = current.get('macos-compiled', {}).get('bothArchitecturesCompiledAndVerified', False)
    public = False
    preview_path = ROOT / '.cache/r130-public-preview.json'
    if preview_path.exists():
        preview = json.loads(preview_path.read_bytes())
        downloads = json.loads((ROOT / '.cache/r130-public-download-verification.json').read_bytes())
        assert preview['sourceCommit'] == downloads['sourceCommit'] == source
        assert preview['allAssetsMatchVerifiedPackages'] and downloads['anonymousDownloadsVerified']
        assert downloads['allDownloadedBytesMatchVerifiedPackages']
        public = True
        for name in ['r130-public-preview.json', 'r130-public-download-verification.json']:
            shutil.copyfile(ROOT / '.cache' / name, output / name)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'parentCommit': git('rev-parse', 'HEAD').decode().strip(), 'runs': observed,
             'nativeCoreJobsVerified': core, 'nativeProtocolJobsVerified': protocol,
             'bothMacosCompiled': compiled, 'macosPackageArchitecturesVerified': package,
             'independentGlibcReportQualified': glibc is not None, 'publicPreviewVerified': public,
             'previousProtocolJobsVerified': counts, 'globalQuotaEnforced': False,
             'wholeDomainAccounted': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'recording-driver.py')
    index.update(sourceCommit=source, nativeRun=observed[0], macosPackageRun=observed[1],
                 nativeCoreJobsVerified=core, nativeTerminalJobsVerified=protocol,
                 nativeQualificationPending=core != 4 or protocol != 4,
                 fullNativeProtocolQualified=protocol == 4,
                 bothMacosCompiled=compiled, macosPackageArchitecturesVerified=package,
                 independentGlibcReportQualified=glibc is not None,
                 observedUtc=value['observedUtc'])
    if public:
        index.update(publicPreviewUrl=preview['releaseUrl'], anonymousPublicDownloadsVerified=True)
    references = {row['path'] for row in index['receipts']} | {name + '/receipt.json' for name in folders}
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in sorted(references)]
    (ROOT / index_name).write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    summary = (f'R130精确{source[:8]}已公开；双Windows各35核心、25条账本和11条面板已验；四原生核心{core}/4、完整协议{protocol}/4，双Mac依赖包{package}/2。'
               + ('独立Ubuntu报告专项4条通过。' if glibc is not None else '独立Ubuntu专项继续。')
               + f'R129完整协议已验{counts[129]}/4，R128已验{counts[128]}/4；'
               + ('双Mac R130预览已公开并匿名下载核对。' if public else '当前Mac公开下载仍R129。')
               + '生产写前额度、自动GC与完整项目继续。')
    status = (f'- [x] 精确`{source}`已非强制公开；[四原生构建与核心/协议]({observed[0]["html_url"]})及'
              f'[双Mac依赖包]({observed[1]["html_url"]})已实际派发，核心已验{core}/4、完整协议{protocol}/4、依赖包{package}/2；逐项按原件核验。'
              + ('双Mac R130预览已公开并匿名下载核对。' if public else '') + '\n')
    remaining = '- [ ] R130其余原生构建/核心、完整协议和双Mac交付继续按精确原作业收验；当前可下载Mac预览仍R129。'
    update = runpy.run_path('.cache/publish-r121-source.py')['update_document']
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：' + summary, text, count=1, flags=re.M)
        text = re.sub(r'^- \[x\] 精确`' + source + r'`已非强制公开；.*\n', '', text, flags=re.M)
        anchor = '- [ ] 本轮精确源码公开、四原生完整核心/协议和双Mac含依赖包继续；当前可下载Mac预览仍R129。'
        chosen = anchor if anchor in text else remaining
        assert chosen in text
        text = text.replace(chosen, status + remaining, 1)
        if public:
            text = text.replace(remaining, '- [ ] R130其余完整协议终态继续按精确原作业收验；普通历史迁移、生产写前额度、自动GC和完整项目验收继续。', 1)
        if glibc is not None:
            text = text.replace('- [ ] 独立Ubuntu报告专项继续原新目录作业，尚未授予通过。',
                                '- [x] 独立Ubuntu新目录实际编译，两项报告及初始化/清理共4条通过；安装源码、295输入、C++14及程序前后保持。仅授予报告专项。[原件](docs/validation/2026-11-08/budget-report-r130-glibc/receipt.json)。', 1)
        text = re.sub(r'核心已验4/4、完整协议\d/4、依赖包2/2。双Mac R129', f'核心已验4/4、完整协议{counts[129]}/4、依赖包2/2。双Mac R129', text, count=1)
        text = re.sub(r'完整协议已按原件核验\d/4，其余继续原作业；R126/R127', f'完整协议已按原件核验{counts[128]}/4，其余继续原作业；R126/R127', text, count=1)
        return text
    update('开发计划与进度.md', plan)
    update('docs/执行进度.md', lambda text: plan(text).replace('](docs/', ']('))
    update('README.md', lambda text: re.sub(r'^R130[^\n]*\n', summary + ' [本轮证据](docs/ci-verification-20261108-r130.json)。\n', text, count=1, flags=re.M))
    explicit.update(['README.md', '开发计划与进度.md', 'docs/执行进度.md', index_name])
    if public:
        package_receipt = current['macos-package']
        assert package_receipt['bothArchitecturesVerified'] and package_receipt['screenshotsViewed']
        rows = []
        for row in package_receipt['records']:
            asset, = [asset for asset in preview['assets'] if asset['name'] == row['archive']]
            rows.append('| ' + row['architecture'] + ' | [下载tar.gz](' + asset['downloadUrl'] + ') | `' + row['packageSha256'] + '` |')
        section = ('## R130含依赖开发预览\n\n精确源码`' + source + '`；[公开下载与四份附件]('
                   + preview['releaseUrl'] + ')。两架构GUI、独立CLI、Qt5/OpenSSL、Cocoa/高DPI、中文空格目录搬迁与各五项包内实际业务已验；四张截图已查看。本轮新增状态预算查询，生产总配额/自动回收仍未启用。开发adhoc签名，正式签名、公证和最低干净系统继续。\n\n'
                   + '| 架构 | 下载 | tar.gz SHA-256 |\n| --- | --- | --- |\n' + '\n'.join(rows)
                   + '\n\n本机副本：dist/macos-preview-20261108-r130-budget-report/。命令行入口：`"Dukto Next.app/Contents/MacOS/dukto-cli" --help`。\n\n')
        # 日期：2026-11-08；同一轮后续收验替换已有章节，不重复prepend本轮发布内容。
        def macos(text):
            text = re.sub(r'## R130含依赖开发预览\n.*?(?=## |\Z)', '', text, flags=re.S)
            return text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + section, 1)
        update('docs/macOS独立预览包.md', macos)
        explicit.add('docs/macOS独立预览包.md')
    for name in explicit:
        shutil.copyfile(ROOT / name, REPO / name)
    for name in folders:
        copy(ROOT / name, REPO / name)
    value.update(explicitFiles=sorted(explicit), evidenceFolders=folders)
    target.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({'core': core, 'protocol': protocol, 'packages': package, 'compiled': compiled, 'glibc': glibc is not None, 'previous': counts}), flush=True)


if __name__ == '__main__':
    main()
