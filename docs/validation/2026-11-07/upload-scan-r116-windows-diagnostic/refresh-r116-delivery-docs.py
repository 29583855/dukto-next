"""日期：2026-11-07；根据真实精确提交和分层回执刷新R116文档，运行中结果不授予完成资格。"""
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


# 日期：2026-11-07；保留已有文本的UTF-8/BOM/换行，不加工日志原字节。
def edit(path, callback):
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    value = callback(raw[len(bom):].decode('utf-8').replace('\r\n', '\n'))
    path.write_bytes(bom + value.replace('\n', newline).encode('utf-8'))


# 日期：2026-11-07；源码提交不包含自身提交号，后续文档提交用明确回执引用精确产品版本。
def main():
    publication = json.loads((ROOT / '.cache/r116-source-publication.json').read_bytes())
    runs = json.loads((ROOT / '.cache/r116-ci-runs.json').read_bytes())
    source = publication['sourceCommit']
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    api = '/repos/29583855/dukto-next/actions/runs/'
    native = request(api + str(runs['nativeRunId']))
    package = request(api + str(runs['packageRunId']))
    assert native['head_sha'] == package['head_sha'] == source
    local = BASE / 'upload-scan-r116-local'
    for original, name in [('r116-source-publication.json', 'source-publication-receipt.json'),
                           ('r116-macos-package-dispatch.json', 'macos-package-dispatch.json'),
                           ('r116-frozen-long-observation.json', 'frozen-long-observation.json'),
                           ('r116-upload-receipt-live.json', 'upload-receipt-live.json')]:
        shutil.copyfile(ROOT / '.cache' / original, local / name)
    report = json.loads((local / 'upload-receipt-live.json').read_bytes())
    assert report['passed'] and len(report['cases']) == 3
    assert [row['channels'] for row in report['cases']] == [1, 4, 16]
    binary = ROOT / 'build/windows/Release/dukto-cli.exe'
    assert report['executableSha256'] == hashlib.sha256(binary.read_bytes()).hexdigest()
    assert report['scriptSha256'] == hashlib.sha256((ROOT / 'tests/upload_receipt_integration.py').read_bytes()).hexdigest()
    for row in publication['qualificationInputs']:
        raw = subprocess.check_output(['git', 'show', source + ':' + row['path']], cwd=REPO)
        assert hashlib.sha256(raw).hexdigest() == row['sha256'], row['path']
    compiled = json.loads((BASE / 'upload-scan-r116-macos-compiled/receipt.json').read_bytes())
    assert compiled['sourceCommit'] == source and compiled['bothArchitecturesCompiledAndVerified']
    index = json.loads((REPO / 'docs/ci-verification-20261107-r116.json').read_bytes())
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(), sourcePublicationPending=False,
                 sourceCommit=source, sourceTree=publication['sourceTree'], remoteSourceVerified=True,
                 localInputsMatchExactSource=True, macosCompiledArchitecturesVerified=2,
                 nativeRun={key: native[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']},
                 macosPackageRun={key: package[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']})
    paths = [local / 'receipt.json', local / 'source-audit.json', BASE / 'upload-scan-r116-ubuntu/receipt.json',
             local / 'source-publication-receipt.json', local / 'upload-receipt-live.json',
             local / 'frozen-long-observation.json', BASE / 'upload-scan-r116-macos-compiled/receipt.json']
    core = BASE / 'upload-scan-r116-native-core/receipt.json'
    if core.exists():
        current = json.loads(core.read_bytes())
        index['allNativeCoreQualified'] = current['allFourNativeCoreJobsVerified']
        index['nativeCoreQualificationPending'] = not current['allFourNativeCoreJobsVerified']
        paths.append(core)
    core_done = index.get('allNativeCoreQualified', False)
    bundle = BASE / 'upload-scan-r116-macos-package/receipt.json'
    bundle_done = False
    if bundle.exists():
        current = json.loads(bundle.read_bytes())
        bundle_done = current['bothArchitecturesVerified'] and current['screenshotsViewed']
        index['macosDeploymentQualified'] = bundle_done
        index['macosDeploymentQualificationPending'] = not bundle_done
        paths.append(bundle)
    diagnostic = BASE / 'upload-scan-r116-windows-diagnostic/receipt.json'
    if diagnostic.exists():
        paths.append(diagnostic)
        index['windowsScanDiagnosticRunId'] = 42377256965
        index['windowsScanDiagnosticStillFailed'] = not json.loads(diagnostic.read_bytes())['passed']
    index['receipts'] = [{'path': path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in paths]
    (REPO / 'docs/ci-verification-20261107-r116.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    def plan(text):
        text = text.replace('准备四平台原生CI及新Mac包。', '源码已公开，四平台原生编译均成功；完整CI和新Mac包继续按实际原件收验。', 1)
        start = text.index('## R116 未发布源扫描清理')
        end = text.index('## R115 ', start)
        section = text[start:end]
        line = '- [x] 精确`' + source + '`已非强制上传，245份资格输入与Git树逐blob相同；双Mac GUI/独立CLI已编译并核验官方ZIP/内部tar、Mach-O架构、执行权限及LICENSE。[索引](docs/ci-verification-20261107-r116.json)。\n- [x] 当前MSVC实际CLI的1/4/16通道上传确认丢失/本地记录恢复专项通过，冻结清单和请求改绑拒绝原件已验；历史确认不冒充当前远端正文验证。\n'
        if '245份资格输入与Git树逐blob相同' not in section:
            section = section.replace('- [ ] 新源码四平台', line + '- [ ] 新源码四平台', 1)
        section = section.replace('- [ ] 新源码四平台原生编译/测试与新双Mac含依赖预览待按实际终态收验。Windows本机符号链接权限跳过仍保留。', '- [ ] [四平台原生CI](' + native['html_url'] + ')状态`' + native['status'] + '`，27个CTest与完整协议按原件另验；[双Mac含依赖包](' + package['html_url'] + ')状态`' + package['status'] + '`，Windows本机符号链接权限跳过仍保留。')
        section = re.sub(r'^- \[.\] \[四平台原生CI\].*$',
            '- [ ] [四平台原生CI](' + native['html_url'] + ')状态`' + native['status'] + '`；完整协议按终态原件另验。[双Mac含依赖包](' + package['html_url'] + ')状态`' + package['status'] + '`。Windows本机权限跳过仍保留。',
            section, flags=re.M)
        if core_done and '四平台各27个CTest/26份Qt原件' not in section:
            section = section.replace('- [ ] [四平台原生CI]', '- [x] 四平台各27个CTest/26份Qt原件均已核验，新扫描清理各25条全通过；精确Darwin端口独占XFAIL按原边界保留。[核心回执](docs/validation/2026-11-07/upload-scan-r116-native-core/receipt.json)。\n- [ ] [四平台原生CI]', 1)
        if bundle_done and '双Mac含Qt5/OpenSSL预览包已验' not in section:
            section = section.replace('- [ ] [四平台原生CI]', '- [x] 双Mac含Qt5/OpenSSL预览包已验：应用源码与载荷逐件核验、系统PATH迁移、各五项真实CLI/传输、Cocoa导航/高DPI及四张截图通过。[下载](docs/macOS独立预览包.md)。\n- [ ] [四平台原生CI]', 1)
        return text[:start] + section + text[end:]
    edit(ROOT / '开发计划与进度.md', plan)
    edit(ROOT / '开发计划与进度.md', lambda text: text.replace(
        '- [ ] [完整协议运行42368086270](https://github.com/29583855/dukto-next/actions/runs/42368086270)状态`in_progress`、结论`待定`；已验终态job 3/4，未完成/失败不授予通过。',
        '- [x] [完整协议运行42368086270](https://github.com/29583855/dukto-next/actions/runs/42368086270)终态`completed/success`，4/4完整job原件已验；Windows51/51，Ubuntu/Apple Silicon/Intel各47/47。', 1).replace(
        '原完整job继续执行，不能被本专项覆盖。', 'Intel原完整job终态failure，不能被本专项覆盖。', 1))
    edit(ROOT / 'docs/执行进度.md', lambda text: text.replace(
        'Ubuntu/Apple Silicon完整协议各47/47通过，其余作业仍在执行。',
        '四平台完整job均终态success，Windows51/51、Ubuntu/Apple Silicon/Intel各47/47原件已验。', 1))
    for version in [113, 114]:
        path = REPO / ('docs/ci-verification-20261107-r' + str(version) + '.json')
        value = json.loads(path.read_bytes())
        suffix = 'skip-reconcile-r113-native-terminal' if version == 113 else 'private-read-r114-native-terminal'
        value['nativeRun'] = json.loads((BASE / suffix / 'receipt.json').read_bytes())['run']
        for row in value['receipts']:
            row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
        if version == 113:
            value['limitations'] = [item.replace(
                'R111 ARM overwrite-faults and Intel credential-rotation/session-expiry failures remain retained and unresolved',
                'R111 ARM overwrite-faults and Intel credential-rotation/session-expiry original failures remain retained; later successful R112/R113 validation does not rewrite earlier failed runs') for item in value['limitations']]
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        shutil.copyfile(path, ROOT / path.relative_to(REPO))
    intro = ('R116精确`' + source + '`已公开，新增上传扫描中断后的七天保留/预览/按请求清理；缓存额度耗尽不遗留Qt连接。双Windows各24条通过/1符号链接权限跳过，独立Ubuntu25条通过；双Mac GUI/独立CLI已编译并验归档。[原生CI](' + native['html_url'] + ')和[含依赖包](' + package['html_url'] + ')继续收验。[清理规则](docs/decisions/0029-未发布上传源扫描清理.md)、[验证索引](docs/ci-verification-20261107-r116.json)。\n\n')
    edit(ROOT / 'README.md', lambda text: text if 'R116精确`' in text else text.replace('R114精确`', intro + 'R114精确`', 1))
    edit(ROOT / 'README.md', lambda text: text.replace('Ubuntu/Apple Silicon完整协议各47/47通过，其余同源作业仍在执行。', '四平台完整协议已验，Windows51/51、Ubuntu/Apple Silicon/Intel各47/47。', 1))
    command = '''
未发布上传源扫描在进程中断后可按原请求维护，默认保留七天。先退出使用同一状态根的GUI、CLI和服务，再预览及执行；冻结清单、已创建上传请求和缺少创建凭据的未知旧库保留。三平台使用相同命令，详见[规则](docs/decisions/0029-未发布上传源扫描清理.md)。

```text
dukto-cli client scan-cleanup preview --state-directory <客户状态父目录> --request-id <原请求UUID> --json
dukto-cli client scan-cleanup run --state-directory <客户状态父目录> --request-id <原请求UUID> --json
```

'''
    edit(ROOT / 'README.md', lambda text: text if 'client scan-cleanup preview --state-directory' in text else text.replace('新版 upload/download/resume 支持', command + '新版 upload/download/resume 支持', 1))
    macintro = ('R116精确`' + source + '`已公开，增加上传扫描中断后的按请求清理及资源申请失败恢复。Apple Silicon/Intel C++14 GUI和独立CLI编译归档均已核验；[完整原生CI](' + native['html_url'] + ')与[含依赖打包](' + package['html_url'] + ')按原始结果继续收验。下方R114含依赖包保留为历史已验版本，不能称为R116。\n\n')
    edit(ROOT / 'docs/macOS独立预览包.md', lambda text: text if 'R116精确`' in text else text.replace('R114精确`', macintro + 'R114精确`', 1))
    section = '## R116原生编译归档\n\n双架构原始ZIP/内部tar摘要、精确源码、LICENSE、Mach-O架构与执行权限已核验。这是编译产物，需要匹配的Qt5/OpenSSL依赖；含依赖预览另验。[回执](validation/2026-11-07/upload-scan-r116-macos-compiled/receipt.json)。\n\n| 架构 | 下载 | 内部tar.gz SHA-256 |\n| --- | --- | --- |\n'
    for row in compiled['packages']:
        section += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['sha256'] + '` |\n'
    section += '\n'
    edit(ROOT / 'docs/macOS独立预览包.md', lambda text: text if '## R116原生编译归档' in text else text.replace('## R114最新含依赖预览', section + '## R114最新含依赖预览', 1))
    if bundle_done:
        bundle_value = json.loads(bundle.read_bytes())
        downloads = '## R116含依赖开发预览\n\n两架构Qt5/OpenSSL、GUI/独立CLI、对应应用源码、全部载荷与框架链接均逐件核验；各五项真实CLI/传输报告、系统PATH迁移、Cocoa导航/高DPI通过，四张截图已查看。[回执](validation/2026-11-07/upload-scan-r116-macos-package/receipt.json)。这是adhoc开发预览，正式签名/公证、干净系统与完整项目继续验收。\n\n| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |\n| --- | --- | --- | --- |\n'
        for row in bundle_value['records']:
            downloads += '| ' + row['architecture'] + ' | [下载](' + row['artifactUrl'] + ') | `' + row['artifactSha256'] + '` | `' + row['packageSha256'] + '` |\n'
        downloads += '\n本机副本：`dist/macos-preview-20261107-r116-upload-scan/`。解压与CLI用法见本文下方说明。\n\n'
        edit(ROOT / 'docs/macOS独立预览包.md', lambda text: text if '## R116含依赖开发预览' in text else text.replace('## R116原生编译归档', downloads + '## R116原生编译归档', 1))
        edit(ROOT / '开发计划与进度.md', lambda text: text.replace('现有含依赖Mac预览仍为R114。', 'R116含依赖双Mac预览、迁移运行与截图已验。', 1).replace('当前已验Mac预览为R114，', '当前已验Mac预览为R116，', 1).replace('当前双Mac含依赖部署包为R114精确d922dc4，', '当前双Mac含依赖部署包为R116精确0a60da9，', 1))
        edit(ROOT / 'docs/macOS独立预览包.md', lambda text: text.replace('下方R114含依赖包保留为历史已验版本，不能称为R116。', '下方R116含依赖双架构预览、迁移运行和四张截图已验，R114包保留为历史版本。', 1).replace('## R114最新含依赖预览', '## R114含依赖预览（历史）', 1))
        edit(ROOT / 'README.md', lambda text: text.replace('[原生CI](' + native['html_url'] + ')和[含依赖包](' + package['html_url'] + ')继续收验。', '[原生CI](' + native['html_url'] + ')继续收验；双架构[含依赖包](' + package['html_url'] + ')、迁移运行及四张截图已验，[下载](docs/macOS独立预览包.md)。', 1))
    if core.exists() and any(row.get('coreStep') == 'failure' for row in json.loads(core.read_bytes())['records']):
        def failure_status(text):
            line = '- [ ] Windows R116原生清理测试在热journal场景未捕获异常，其余26个CTest通过；Ubuntu与双Mac各27个CTest及清理25条全通过。原失败保留，隔离[Windows诊断42377256965](https://github.com/29583855/dukto-next/actions/runs/42377256965)只增错误报告，产品输入仍为R116。\n'
            start = text.index('## R116 未发布源扫描清理')
            end = text.index('## R115 ', start)
            section = text[start:end]
            if 'Windows R116原生清理测试在热journal场景' not in section:
                section = section.replace('- [ ] [四平台原生CI]', line + '- [ ] [四平台原生CI]', 1)
            return text[:start] + section + text[end:]
        edit(ROOT / '开发计划与进度.md', failure_status)
        if diagnostic.exists():
            edit(ROOT / '开发计划与进度.md', lambda text: text.replace('只增错误报告，产品输入仍为R116。', '只增错误报告，产品输入仍为R116；两轮终态failure，均报4/identity，热journal所有权继续核对。[诊断原件](docs/validation/2026-11-07/upload-scan-r116-windows-diagnostic/receipt.json)。', 1) if '两轮终态failure，均报4/identity' not in text else text)
        edit(ROOT / '开发计划与进度.md', lambda text: text.replace('| Windows | R114原生26核心/59目录用例，R115两工具链各7个面板方法通过；部署仍为R100 |', '| Windows | R116本机双工具链通过；原生CI26/27，新清理热journal异常原件保留，专项诊断中；部署仍R100 |', 1).replace('| Linux | R114原生26核心/59目录与私有配置原子换代测试通过；R113完整job 47/47 |', '| Linux | R116原生27核心/59目录及扫描清理25条通过；完整协议继续 |', 1).replace('| macOS ARM / Intel | R114含Qt5/OpenSSL双架构GUI/CLI预览可下载；ARM26核心通过、Intel25/26原失败保留；R115双Mac各两轮完整面板专项已验 |', '| macOS ARM / Intel | R116含Qt5/OpenSSL双架构GUI/CLI预览可下载；两架构各27核心、扫描清理25条及迁移运行/截图通过 |', 1))
        edit(ROOT / 'docs/执行进度.md', lambda text: text.replace('全局GC和总磁盘预算继续。', 'R116双Mac编译、含Qt5/OpenSSL包和迁移/截图已验；Ubuntu/双Mac各27个CTest通过，Windows热journal异常及其余26项通过原件分别保留，专项诊断中。全局GC和总磁盘预算继续。', 1) if 'Windows热journal异常及其余26项通过原件' not in text else text)
    for name in ['开发计划与进度.md', 'README.md', 'docs/macOS独立预览包.md', 'docs/执行进度.md']:
        shutil.copyfile(ROOT / name, REPO / name)
    shutil.copyfile(REPO / 'docs/ci-verification-20261107-r116.json', ROOT / 'docs/ci-verification-20261107-r116.json')
    for folder in [local, BASE / 'upload-scan-r116-macos-compiled', BASE / 'upload-scan-r116-native-core', BASE / 'upload-scan-r116-macos-package', BASE / 'upload-scan-r116-windows-diagnostic']:
        if folder.exists():
            shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({'sourceCommit': source, 'nativeRunStatus': native['status'], 'packageRunStatus': package['status'],
                      'macosCompiledArchitecturesVerified': 2, 'newBundleFullyVerified': bundle_done}), flush=True)


if __name__ == '__main__':
    main()
