"""日期：2026-11-07；只按精确R117源码和真实Mac回执更新下载及进度，完整项目仍保留待验。"""
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


# 日期：2026-11-07；保留已有文档编码和换行，新文档仅更新明确的本轮事实。
def edit(name, callback):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    path.write_bytes(bom + callback(text).replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-07；已查看四张真实截图才允许交付入口更新，不以运行报告代替视觉核对。
def main():
    publication = json.loads((ROOT / '.cache/r117-source-publication.json').read_bytes())
    runs = json.loads((ROOT / '.cache/r117-ci-runs.json').read_bytes())
    source = publication['sourceCommit']
    compiled = json.loads((BASE / 'sqlite-journal-r117-macos-compiled/receipt.json').read_bytes())
    package = json.loads((BASE / 'sqlite-journal-r117-macos-package/receipt.json').read_bytes())
    core = json.loads((BASE / 'sqlite-journal-r117-native-core/receipt.json').read_bytes())
    assert compiled['sourceCommit'] == package['sourceCommit'] == core['sourceCommit'] == source
    assert compiled['bothArchitecturesCompiledAndVerified'] and package['bothArchitecturesVerified'] and package['screenshotsViewed']
    for row in publication['qualificationInputs']:
        raw = subprocess.check_output(['git', 'show', source + ':' + row['path']], cwd=REPO)
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert raw == (ROOT / row['path']).read_bytes()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    native = request('/repos/29583855/dukto-next/actions/runs/' + str(runs['nativeRunId']))
    assert native['head_sha'] == source
    local = BASE / 'sqlite-journal-r117-local'
    shutil.copyfile(ROOT / '.cache/r117-source-publication.json', local / 'source-publication-receipt.json')
    shutil.copyfile(ROOT / '.cache/r117-macos-package-dispatch.json', local / 'macos-package-dispatch.json')
    index = json.loads((REPO / 'docs/ci-verification-20261107-r117.json').read_bytes())
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourceCommit=source,
                 sourceTree=publication['sourceTree'], sourcePublicationPending=False, remoteSourceVerified=True,
                 macosCompiledArchitecturesVerified=2, macosDeploymentQualified=True,
                 nativeRun={key: native[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
                 macosPackageRun=package['run'], allNativeCoreQualified=core['allFourNativeCoreJobsVerified'],
                 fullNativeProtocolQualified=False, nativeQualificationPending=True)
    paths = {row['path'] for row in index['receipts']}
    paths.update(path.relative_to(REPO).as_posix() for path in [local / 'source-publication-receipt.json',
                 local / 'macos-package-dispatch.json', BASE / 'sqlite-journal-r117-macos-compiled/receipt.json',
                 BASE / 'sqlite-journal-r117-macos-package/receipt.json', BASE / 'sqlite-journal-r117-native-core/receipt.json'])
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((REPO / name).read_bytes()).hexdigest()} for name in sorted(paths)]
    path = REPO / 'docs/ci-verification-20261107-r117.json'
    path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(path, ROOT / path.relative_to(REPO))
    prior_path = REPO / 'docs/ci-verification-20261107-r116.json'
    prior = json.loads(prior_path.read_bytes())
    for row in prior['receipts']:
        row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
    prior['observedUtc'] = datetime.now(timezone.utc).isoformat()
    prior_path.write_text(json.dumps(prior, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(prior_path, ROOT / prior_path.relative_to(REPO))
    qualified = [row['runner'] for row in core['records'] if row['qualified']]
    core_text = '、'.join(qualified) + '各27核心已验' if qualified else '27项核心仍按原件收验'
    native_url = native['html_url']
    package_url = package['run']['html_url']
    additions = '- [x] 精确`' + source + '`已非强制上传，245份资格输入及公开Git树逐blob核对；Apple Silicon/Intel原生GUI及独立CLI编译归档、Mach-O架构、执行权限和许可通过。[索引](docs/ci-verification-20261107-r117.json)。\n'
    additions += '- [x] 双Mac含Qt5/OpenSSL预览、对应应用源码、逐件载荷及框架链接、系统PATH迁移、各五项真实CLI/传输、Cocoa导航/高DPI及四张截图已验。[下载](docs/macOS独立预览包.md)。\n'
    additions += '- [ ] [R117完整原生CI](' + native_url + ')仍按各job终态收验；' + core_text + '，两条精确Darwin XFAIL继续披露。冻结R98长测仍不能授予当前版本24h资格。'
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R117精确' + source[:7] + '已公开，Windows日志恢复修正完成双工具链各27核心及原生两轮各29条；双Mac编译/含依赖预览、迁移运行与截图已验。' + core_text + '，完整协议终态继续。整体与正式发布未完成。', text, count=1, flags=re.M)
        text = text.replace('当前已验Mac预览为R116', '当前已验Mac预览为R117', 1)
        text = text.replace('| Windows | R116本机双工具链通过；原生CI26/27，新清理热journal异常原件保留，专项诊断中；部署仍R100 |', '| Windows | R117本机双工具链各27核心、原生清理两轮各29条通过；R116原失败保留；部署仍R100 |', 1)
        if 'ubuntu-22.04' in qualified:
            text = text.replace('| Linux | R116原生27核心/59目录及扫描清理25条通过；完整协议继续 |', '| Linux | R117原生27核心/59目录及扫描清理29条通过；完整协议继续 |', 1)
        text = text.replace('| macOS ARM / Intel | R116含Qt5/OpenSSL双架构GUI/CLI预览可下载；两架构各27核心、扫描清理25条及迁移运行/截图通过 |', '| macOS ARM / Intel | R117含Qt5/OpenSSL双架构GUI/CLI预览可下载；编译、包迁移运行及截图通过，核心及完整协议按新原件另验 |', 1)
        text = text.replace('当前双Mac含依赖部署包为R116精确0a60da9', '当前双Mac含依赖部署包为R117精确' + source[:7], 1)
        text = text.replace('R116 Ubuntu/Apple Silicon完整协议各47项原件已验，其余作业继续单独收验。', 'R116 Ubuntu/双Mac完整协议各47项原件已验，Windows终态继续单独收验。', 1)
        text = re.sub(r'^- \[ \] R117公开提交、四原生完整回归.*$', additions, text, count=1, flags=re.M)
        return text
    edit('开发计划与进度.md', plan)
    edit('docs/执行进度.md', lambda text: text.replace('新Mac编译/包及完整原生回归继续。', '精确' + source[:7] + '已公开，双Mac编译、含Qt5/OpenSSL包、迁移运行及四张截图已验；' + core_text + '，完整原生协议继续。', 1))
    intro = 'R117精确`' + source + '`已公开，修复Windows提升进程创建SQLite热日志时的默认所有者误拒绝，保留私有ACL及普通文件严格规则。双Windows各27核心及GitHub Windows两轮专项各29条通过。Apple Silicon/Intel C++14 GUI、独立CLI及含Qt5/OpenSSL预览均已核验；迁移运行、各五项CLI/传输、Cocoa导航/高DPI和四张截图通过。[完整CI](' + native_url + ')继续按终态收验，[打包](' + package_url + ')双架构终态success。\n\n'
    table = '## R117含依赖开发预览\n\n[逐层回执](validation/2026-11-07/sqlite-journal-r117-macos-package/receipt.json)。这是adhoc开发预览，正式签名/公证、最低干净系统及完整项目仍待验。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
    for row in package['records']:
        table += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['artifactSha256'] + '` | `' + row['packageSha256'] + '` |\n'
    table += '\n本机副本：`dist/macos-preview-20261107-r117-upload-scan/`。解压与CLI用法见本文下方说明。\n\n'
    edit('docs/macOS独立预览包.md', lambda text: text.replace('\n\n', '\n\n' + intro, 1).replace('## R116含依赖开发预览', table + '## R116含依赖开发预览（历史）', 1))
    edit('README.md', lambda text: text.replace('R116精确`0a60da9', 'R117精确`' + source + '`已公开；Windows原生日志恢复通过双工具链各27核心及云端两轮各29条，双Mac含依赖GUI/CLI预览、迁移运行及截图已验。[Mac下载](docs/macOS独立预览包.md)、[本轮证据](docs/ci-verification-20261107-r117.json)。完整项目继续按计划验收。\n\nR116精确`0a60da9', 1))
    shutil.copyfile(Path(__file__), local / 'delivery-documentation-driver.py')
    for folder in ['sqlite-journal-r117-local', 'sqlite-journal-r117-native-core',
                   'sqlite-journal-r117-macos-compiled', 'sqlite-journal-r117-macos-package',
                   'upload-scan-r116-native-terminal']:
        shutil.copytree(BASE / folder, ROOT / 'docs/validation/2026-11-07' / folder, dirs_exist_ok=True)
    print(json.dumps({'sourceCommit': source, 'macosArchitecturesVerified': 2, 'verifiedCoreRunners': qualified,
                      'fullNativeProtocolQualified': False, 'deliveryComplete': False}), flush=True)


if __name__ == '__main__':
    main()
