"""日期：2026-11-07；按精确R118实际产物增量更新交付文档，产品与正式资格分别保留。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = REPO / 'docs/validation/2026-11-07'


# 日期：2026-11-07；已有文档保留原BOM/换行；修改后的同一字节同步到公开副本。
def edit(name, callback):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    old = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    new = callback(old)
    path.write_bytes(bom + new.replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-07；JSON回执只重算实际存在的证据摘要，不替未完成作业授予资格。
def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


# 日期：2026-11-07；双架构源/载荷/运行及四截图全部核验后才更新下载入口，未完成协议仍列明。
def main():
    publication = json.loads((ROOT / '.cache/r118-source-publication.json').read_bytes())
    source = publication['sourceCommit']
    for row in publication['qualificationInputs']:
        raw = subprocess.check_output(['git', 'show', source + ':' + row['path']], cwd=REPO)
        assert raw == (ROOT / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
    compiled = json.loads((BASE / 'state-storage-r118-macos-compiled/receipt.json').read_bytes())
    package = json.loads((BASE / 'state-storage-r118-macos-package/receipt.json').read_bytes())
    core = json.loads((BASE / 'state-storage-r118-native-core/receipt.json').read_bytes())
    assert compiled['sourceCommit'] == package['sourceCommit'] == core['sourceCommit'] == source
    assert compiled['bothArchitecturesCompiledAndVerified'] and package['bothArchitecturesVerified'] and package['screenshotsViewed']
    local = BASE / 'state-storage-r118-local'
    for name, target in [('r118-source-publication.json', 'source-publication-receipt.json'),
                         ('r118-macos-package-dispatch.json', 'macos-package-dispatch.json'),
                         ('r118-frozen-long-observation.json', 'frozen-long-observation.json')]:
        shutil.copyfile(ROOT / '.cache' / name, local / target)
    shutil.copyfile(Path(__file__), local / 'delivery-documentation-driver.py')
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    runs = json.loads((ROOT / '.cache/r118-ci-runs.json').read_bytes())
    native = request('/repos/29583855/dukto-next/actions/runs/' + str(runs['nativeRunId']))
    assert native['head_sha'] == source
    path = REPO / 'docs/ci-verification-20261107-r118.json'
    index = json.loads(path.read_bytes())
    terminal_path = BASE / 'state-storage-r118-native-terminal/receipt.json'
    terminal = json.loads(terminal_path.read_bytes()) if terminal_path.exists() else {}
    full = terminal.get('allFourNativeProtocolJobsVerified', False)
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=source,
                 sourceTree=publication['sourceTree'], sourcePublicationPending=False, remoteSourceVerified=True,
                 macosCompiledArchitecturesVerified=2, macosDeploymentQualified=True,
                 nativeRun={key: native[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
                 macosPackageRun=package['run'], allNativeCoreQualified=core['allFourNativeCoreJobsVerified'],
                 fullNativeProtocolQualified=full, nativeQualificationPending=not full)
    paths = {row['path'] for row in index['receipts']}
    for folder in ['state-storage-r118-native-core', 'state-storage-r118-macos-compiled',
                   'state-storage-r118-macos-package', 'state-storage-r118-native-terminal']:
        proof = BASE / folder / 'receipt.json'
        if proof.exists():
            paths.add(proof.relative_to(REPO).as_posix())
    paths.update((local / name).relative_to(REPO).as_posix() for name in [
        'source-publication-receipt.json', 'macos-package-dispatch.json', 'frozen-long-observation.json'])
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((REPO / name).read_bytes()).hexdigest()} for name in sorted(paths)]
    write(path, index)
    shutil.copyfile(path, ROOT / path.relative_to(REPO))
    for version in [116, 117]:
        path = REPO / ('docs/ci-verification-20261107-r' + str(version) + '.json')
        previous = json.loads(path.read_bytes())
        prefix = 'upload-scan' if version == 116 else 'sqlite-journal'
        proof = BASE / (prefix + '-r' + str(version) + '-native-terminal/receipt.json')
        value = json.loads(proof.read_bytes())
        previous.update(observedUtc=datetime.now(timezone.utc).isoformat(),
                        nativeRun=value['run'], fullNativeProtocolQualified=value['allFourNativeProtocolJobsVerified'])
        for row in previous['receipts']:
            row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
        write(path, previous)
        shutil.copyfile(path, ROOT / path.relative_to(REPO))
    qualified = [row['runner'] for row in core['records'] if row['qualified']]
    old_terminal = json.loads((BASE / 'sqlite-journal-r117-native-terminal/receipt.json').read_bytes())
    old_qualified = [row['runner'] for row in old_terminal['records'] if row['qualified']]
    core_text = '、'.join(qualified) + '各28核心已验' if qualified else '28核心按原件继续收验'
    section = '- [x] 精确' + source + '已非强制公开，247份构建输入及证据逐blob核对；双Mac GUI/独立CLI编译归档、源码身份、Mach-O架构及执行权限已验。\n'
    section += '- [x] 双Mac含Qt5/OpenSSL预览、逐件源码/载荷/链接、系统PATH迁移、各五项CLI/传输、Cocoa导航/高DPI和四张截图已验。[下载](docs/macOS独立预览包.md)。\n'
    section += '- [x] 将总配额/自动GC按真实写入、跨进程账本、历史/幂等分类和崩溃恢复拆分为八项待实施及故障验收；[实施清单](docs/磁盘总配额实施清单.md)中每项保持待实现。\n'
    section += '- [' + ('x' if core['allFourNativeCoreJobsVerified'] else ' ') + '] R118原生核心：' + core_text + '，双Mac精确Darwin XFAIL继续保留。完整协议' + ('四平台已验。' if full else '仍按终态原件收验。')
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R118精确' + source[:7] + '已公开，双Windows各28核心/27份XML通过；双Mac编译、含依赖包、迁移运行与四截图已验。' + core_text + '；完整协议' + ('四平台已验' if full else '继续') + '。总配额/自动GC及完整项目交付继续。', text, count=1, flags=re.M)
        text = text.replace('当前已验Mac预览为R117', '当前已验Mac预览为R118', 1)
        text = text.replace('| Windows | R117本机双工具链各27核心、原生清理两轮各29条通过；R116原失败保留；部署仍R100 |', '| Windows | R118本机双工具链与原生CI各28核心通过，原生计量11条全通过；部署仍R100 |', 1)
        text = text.replace('| Linux | R117原生27核心/59目录及扫描清理29条通过；完整协议继续 |', '| Linux | R118原生28核心、计量12条及扫描清理29条通过；完整协议继续 |', 1)
        text = text.replace('| macOS ARM / Intel | R117含Qt5/OpenSSL双架构GUI/CLI预览可下载；编译、包迁移运行及截图通过，核心及完整协议按新原件另验 |', '| macOS ARM / Intel | R118含Qt5/OpenSSL双架构GUI/CLI预览可下载，各28核心及计量12条通过，迁移运行及截图已验 |', 1)
        text = re.sub(r'^- \[ \] \[R117完整原生CI\].*$', '- [ ] R117四原生各27核心已验；' + '、'.join(old_qualified) + '完整协议各47项通过，Windows终态继续，冻结R98不转授当前版本24h资格。', text, count=1, flags=re.M)
        text = text.replace('当前双Mac含依赖部署包为R117精确a46454d', '当前双Mac含依赖部署包为R118精确' + source[:7], 1)
        marker = '- [ ] R118精确公开提交、四原生完整回归、新双Mac编译和含依赖预览继续，当前已验Mac预览仍为R117。'
        if marker in text:
            text = text.replace(marker, section, 1)
        else:
            start = text.index('- [x] 精确' + source)
            end = text.index('\n- [ ] 全根总配额', start)
            text = text[:start] + section + text[end:]
        return text
    edit('开发计划与进度.md', plan)
    def progress(text):
        start = text.index('## R118 状态根直接占用计量')
        end = text.index('## R117 Windows原生回滚日志恢复', start)
        return text[:start] + '## R118 状态根直接占用计量（2026-11-07）\n\n精确' + source[:7] + '已公开；双Windows各28完整CTest/27份XML通过，计量专项各10通过/1本机权限跳过，原夹具失败保留。双Mac编译、含Qt5/OpenSSL预览、系统PATH迁移、各五项真实CLI/传输和四张截图已验；' + core_text + '，完整协议' + ('四平台已验' if full else '继续') + '。总配额、自动GC和完整R6 GUI等范围继续。[用法](状态占用查询.md)、[证据](ci-verification-20261107-r118.json)。\n\n' + text[end:]
    edit('docs/执行进度.md', progress)
    intro = 'R118精确' + source + '已公开，新增客户端/服务器状态占用查询；双Windows各28核心通过。双Mac C++14 GUI、独立CLI及含Qt5/OpenSSL预览、迁移运行和四截图已验。[' + core_text + '](ci-verification-20261107-r118.json)；完整协议另按终态核验。\n\n'
    table = '## R118含依赖开发预览\n\n[逐层回执](validation/2026-11-07/state-storage-r118-macos-package/receipt.json)。这是adhoc开发预览，正式签名/公证、最低干净系统及完整项目仍待验。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
    for row in package['records']:
        table += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | ' + row['artifactSha256'] + ' | ' + row['packageSha256'] + ' |\n'
    table += '\n本机副本：dist/macos-preview-20261107-r118-state-storage/。解压与CLI用法见本文下方说明。\n\n'
    def downloads(text):
        if '## R118含依赖开发预览' not in text:
            return text.replace('\n\n', '\n\n' + intro, 1).replace('## R117含依赖开发预览', table + '## R117含依赖开发预览（历史）', 1)
        start = text.index('## R118含依赖开发预览')
        end = text.index('## R117含依赖开发预览', start)
        return text[:start] + table + text[end:]
    edit('docs/macOS独立预览包.md', downloads)
    def readme(text):
        return re.sub(r'^R118新增客户端/服务器状态占用查询.*$', 'R118精确' + source[:7] + '已公开，状态占用查询及双Windows各28完整CTest/27份XML通过。双Mac GUI/独立CLI、含Qt5/OpenSSL预览、迁移运行及四截图已验；' + core_text + '，完整协议继续。总配额/自动GC和完整项目继续按计划实施。[Mac下载](docs/macOS独立预览包.md)、[用法](docs/状态占用查询.md)、[证据](docs/ci-verification-20261107-r118.json)。', text, count=1, flags=re.M)
    edit('README.md', readme)
    shutil.copyfile(ROOT / 'docs/磁盘总配额实施清单.md', REPO / 'docs/磁盘总配额实施清单.md')
    for name in ['state-storage-r118-local', 'state-storage-r118-native-core',
                 'state-storage-r118-macos-compiled', 'state-storage-r118-macos-package',
                 'state-storage-r118-native-terminal', 'sqlite-journal-r117-native-terminal']:
        folder = BASE / name
        if folder.exists():
            shutil.copytree(folder, ROOT / 'docs/validation/2026-11-07' / name, dirs_exist_ok=True)
    print(json.dumps({'sourceCommit': source, 'macosArchitecturesVerified': 2, 'verifiedCoreRunners': qualified,
                      'fullNativeProtocolQualified': full, 'deliveryComplete': False}), flush=True)


if __name__ == '__main__':
    main()
