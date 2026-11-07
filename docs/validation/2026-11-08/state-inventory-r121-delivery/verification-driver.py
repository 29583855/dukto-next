"""日期：2026-11-08；发布已验双Mac包和真实终态进度，保留尚在运行的独立资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；只将已收验的原件与进度同步到工作区，所有新增证据限定公开格式。
def main():
    target = ROOT / '.cache/r121-macos-delivery-prepared.json'
    assert not target.exists()
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    package = json.loads((REPO / (BASE + 'state-inventory-r121-macos-package/receipt.json')).read_bytes())
    compiled = json.loads((REPO / (BASE + 'state-inventory-r121-macos-compiled/receipt.json')).read_bytes())
    terminal = json.loads((REPO / (BASE + 'state-inventory-r121-native-terminal/receipt.json')).read_bytes())
    r120_terminal = json.loads((REPO / (BASE + 'sqlite-file-info-r120-native-terminal/receipt.json')).read_bytes())
    source = json.loads((ROOT / '.cache/r121-source-publication.json').read_bytes())['sourceCommit']
    ci = json.loads((ROOT / '.cache/r121-ci-source-publication.json').read_bytes())['sourceCommit']
    assert package['bothArchitecturesVerified'] and package['screenshotsViewed']
    assert package['run']['conclusion'] == 'success' and compiled['bothArchitecturesCompiledAndVerified']
    assert all(value['sourceCommit'] == ci for value in [package, compiled, terminal])
    assert r120_terminal['allFourNativeProtocolJobsVerified'] and r120_terminal['run']['conclusion'] == 'success'
    count = sum(row['qualified'] for row in terminal['records'])
    glibc_path = ROOT / '.cache/r121-glibc-qualified/receipt.json'
    glibc = json.loads(glibc_path.read_bytes()) if glibc_path.exists() else None
    summary = (f'R121应用源{source[:8]}、CI源{ci[:8]}的四原生状态专项和各30完整核心已验；'
               f'双Mac GUI/独立CLI、含Qt5/OpenSSL包、迁移运行及四张截图已验，下载已更新。完整协议终态已验{count}/4；'
               + ('独立Ubuntu15条专项已验。' if glibc and glibc.get('stateInventoryQualified') else '独立Ubuntu干净构建仍在执行。')
               + 'R120四原生完整协议全部终态通过。跨进程总预算、自动GC及完整交付仍未完成。')
    record = f'''## R121双Mac包交付与原生验收进度（2026-11-08）

- [x] 应用源{source}与CI计数修正源{ci}的产品输入相同；四原生状态专项及四平台各30完整核心已验。Windows14条、三个POSIX各15条，均无权限跳过；两Mac精确Darwin端口XFAIL保留。
- [x] [双Mac含依赖包]({package['run']['html_url']})全部终态success。各架构GUI/独立CLI、Qt5/OpenSSL部署、精确源码/许可、载荷/链接/架构/执行位、系统PATH搬迁、五项实际业务、Cocoa导航/高DPI及四张截图已核验。[下载及摘要](docs/macOS独立预览包.md)已更新至R121；adhoc开发签名，正式签名公证和最低干净系统继续验收。
- [x] 双Mac原生编译归档的官方ZIP与内部tar摘要、源码、Mach-O架构、执行位与许可均已核对。编译归档与含依赖包分别提供，不将编译成功等同部署通过。
- [{'x' if count == 4 else ' '}] R121完整协议按独立终态已验{count}/4；{'四个平台全部终态通过。' if count == 4 else '其余原作业仍运行，不重启、不预记为成功。'}[终态回执](docs/validation/2026-11-08/state-inventory-r121-native-terminal/receipt.json)。
- [x] R120原完整运行已全部终态success：Windows51条、Ubuntu/双Mac各47条协议通过。环境修正专项四平台各30完整核心同样已验，原环境缺失失败继续保留。
- [x] 冻结R98 Windows原长测真实运行86400.047秒、285轮16通道双向传输并通过，556份冻结输入重新核对不变；原CSV/报告/驱动退出和暖机后资源门槛已验。[独立终态](docs/validation/2026-11-08/r98-windows-long-terminal/receipt.json)。它只授予该冻结版本/有界任务范围，不能转授R121、任意增长或自动GC资格；Ubuntu冻结长测仍按原进程继续。
- [ ] 全根/临时对象归属、跨进程持久预算、自动GC、完整R6/原生选择器、物理LAN/3×3、当前各平台24h、依赖源码独立重建、最低干净系统及正式分发仍待完成；整体保持active。

'''
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary, text, count=1, flags=re.M).replace('## R121精确公开与四原生专项', record + '## R121精确公开与四原生专项', 1))
    update('docs/执行进度.md', lambda text: text.replace('## R121精确公开与四原生专项', record.replace('](docs/', '](') + '## R121精确公开与四原生专项', 1))
    update('README.md', lambda text: text.replace('R121应用源d924ba5c已公开', summary + ' [Mac下载](docs/macOS独立预览包.md)。\n\nR121应用源d924ba5c已公开', 1))
    preview = ('## R121含依赖开发预览\n\n'
               f'应用源`{source}`；实际构建/打包源`{ci}`只修正CI计数器，产品输入相同。'
               '[逐层回执](validation/2026-11-08/state-inventory-r121-macos-package/receipt.json)。'
               '双架构GUI/独立CLI、Qt5/OpenSSL、迁移运行、五项业务及四张截图均已验。adhoc开发签名，正式签名/公证及最低干净系统继续验收。\n\n'
               '| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n')
    for row in package['records']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['artifactSha256']} | {row['packageSha256']} |\n"
    preview += '\n本机副本：dist/macos-preview-20261108-r121-state-inventory/。解压和独立CLI用法见下文。\n\n## R121原生编译归档\n\n'
    preview += '[回执](validation/2026-11-08/state-inventory-r121-macos-compiled/receipt.json)。仅编译归档需要匹配运行库；上方预览已部署依赖。\n\n'
    preview += '| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        preview += f"| {row['architecture']} | [下载]({row['artifactUrl']}) | {row['sha256']} |\n"
    preview += '\n'
    update('docs/macOS独立预览包.md', lambda text: text.replace('# macOS独立开发预览包\n\n', '# macOS独立开发预览包\n\n' + summary + '\n\n', 1).replace('## R120含依赖开发预览', preview + '## R120含依赖开发预览（历史）', 1))
    update('docs/状态文件原生观察.md', lambda text: text + '\nR121双Mac含依赖包、迁移运行及四截图已验；四原生完整核心已验，完整协议按独立终态持续收验。状态根原生观察仍不代表全根归属或预算执行。\n')
    folders = [BASE + name for name in ['state-inventory-r121-macos-package', 'state-inventory-r121-macos-compiled',
                                       'state-inventory-r121-native-terminal', 'sqlite-file-info-r120-native-terminal']]
    long_folder = BASE + 'r98-windows-long-terminal'
    for path in (ROOT / long_folder).rglob('*'):
        if path.is_file():
            destination = REPO / path.relative_to(ROOT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)
    folders.append(long_folder)
    execution = REPO / (BASE + 'state-inventory-r121-delivery')
    execution.mkdir(exist_ok=False)
    (execution / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    if glibc and glibc.get('stateInventoryQualified'):
        for path in glibc_path.parent.rglob('*'):
            if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.sha256']:
                destination = execution / 'glibc-qualified' / path.relative_to(glibc_path.parent)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    delivery = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source, 'ciSourceCommit': ci,
                'bothMacosCompiled': True, 'bothMacosPackagesQualified': True, 'screenshotsViewed': True,
                'completeNativeProtocolJobsVerified': count, 'allR120NativeProtocolQualified': True,
                'independentGlibcQualified': bool(glibc and glibc.get('stateInventoryQualified')),
                'frozenR98Windows24hPassed': True, 'currentR121LongQualified': False,
                'globalQuotaEnforced': False, 'automaticGcImplemented': False,
                'deliveryComplete': False, 'releaseQualified': False}
    (execution / 'receipt.json').write_text(json.dumps(delivery, indent=2) + '\n', 'utf-8')
    folders.append(execution.relative_to(REPO).as_posix())
    index_path = REPO / 'docs/ci-verification-20261108-r121.json'
    index = json.loads(index_path.read_bytes())
    index.update(observedUtc=delivery['observedUtc'], nativeRun=terminal['run'], macosPackageRun=package['run'],
                 macosPackageQualificationPending=False, bothMacosCompiled=True, bothMacosPackagesQualified=True,
                 macosScreenshotsViewed=True, nativeTerminalJobsVerified=count,
                 fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'],
                 nativeQualificationPending=count != 4, independentGlibcQualified=delivery['independentGlibcQualified'],
                 frozenR98Windows24hPassed=True, currentR121LongQualified=False,
                 globalQuotaEnforced=False, automaticGcImplemented=False, deliveryComplete=False, releaseQualified=False)
    names = {row['path'] for row in index['receipts']} | {folder + '/receipt.json' for folder in folders}
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((REPO / name).read_bytes()).hexdigest()} for name in sorted(names)]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    r120_path = REPO / 'docs/ci-verification-20261108-r120.json'
    r120 = json.loads(r120_path.read_bytes())
    r120.update(observedUtc=delivery['observedUtc'], nativeRun=r120_terminal['run'], nativeTerminalJobsVerified=4,
                fullNativeProtocolQualified=True, nativeQualificationPending=False)
    for row in r120['receipts']:
        row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
    r120_path.write_text(json.dumps(r120, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    for path in [index_path, r120_path]:
        shutil.copyfile(path, ROOT / path.relative_to(REPO))
    for folder in folders:
        for path in (REPO / folder).rglob('*'):
            if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.sha256', '.png', '.py', '.csv']:
                destination = ROOT / path.relative_to(REPO)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, destination)
    delivery['evidenceFolders'] = folders
    target.write_text(json.dumps(delivery, indent=2) + '\n', 'utf-8')
    print(json.dumps(delivery), flush=True)


if __name__ == '__main__':
    main()
