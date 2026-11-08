"""日期：2026-11-08；冻结已实际验证的预算查询源码与旧原生终态，不替未完成项授予资格。"""
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
BASE = 'docs/validation/2026-11-08/'
SUFFIXES = {'.json', '.xml', '.log', '.txt', '.py', '.sha256', '.csv', '.exit', '.png'}


# 日期：2026-11-08；只镜像明确的有界原件扩展，不复制执行文件、凭据或私有任务目录。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in SUFFIXES:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


# 日期：2026-11-08；旧资格按对应Git源码批量核对，不拿已改动的本轮工作树冒充旧冻结输入。
def previous():
    helper = runpy.run_path('.cache/publish-r120-native-delivery.py')
    git, tree = helper['git'], helper['tree']
    indexes, required = {}, {}
    for revision in [126, 127, 128, 129]:
        name = 'docs/ci-verification-20261108-r' + str(revision) + '.json'
        value = json.loads((ROOT / name).read_bytes())
        objects = tree(value['sourceCommit'])
        for row in value['qualificationInputs']:
            sha = objects[row['path']]
            if sha in required:
                assert required[sha] == row['sha256']
            required[sha] = row['sha256']
        indexes[revision] = (name, value)
    names = sorted(required)
    process = subprocess.run(['git', 'cat-file', '--batch'], input=('\n'.join(names) + '\n').encode(),
                             cwd=REPO, capture_output=True, check=True)
    raw = process.stdout
    offset = 0
    for name in names:
        end = raw.index(b'\n', offset)
        sha, kind, size = raw[offset:end].split()
        assert sha.decode() == name and kind == b'blob'
        offset = end + 1
        content = raw[offset:offset + int(size)]
        assert hashlib.sha256(content).hexdigest() == required[name]
        offset += int(size)
        assert raw[offset:offset + 1] == b'\n'
        offset += 1
    assert offset == len(raw)
    counts, folders, explicit = {}, [], set()
    for revision, label in [(126, 'cli-state-session'), (127, 'gui-state-session'), (128, 'state-fixture'), (129, 'state-accounting')]:
        folder = BASE + label + '-r' + str(revision) + '-native-terminal'
        copy(REPO / folder, ROOT / folder)
        receipt = json.loads((ROOT / folder / 'receipt.json').read_bytes())
        name, value = indexes[revision]
        assert value['sourceCommit'] == receipt['sourceCommit']
        counts[revision] = sum(row['qualified'] for row in receipt['records'])
        value.update(nativeRun=receipt['run'], nativeTerminalJobsVerified=counts[revision],
                     nativeTerminalJobsCompleted=sum(row.get('status') == 'completed' for row in receipt['records']),
                     fullNativeProtocolQualified=receipt['allFourNativeProtocolJobsVerified'])
        for row in value['receipts']:
            row['sha256'] = hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest()
        (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
        folders.append(folder)
        explicit.add(name)
    return folders, explicit, counts


# 日期：2026-11-08；两套完整CTest、34份XML、新报告方法、源码/程序及四张实际查看截图全部成立才勾选。
def main():
    target = ROOT / '.cache/r130-source-prepared.json'
    assert not target.exists()
    qt = runpy.run_path('.cache/verify-r130-results.py')['qt']
    inputs, records = None, []
    name = BASE + 'budget-report-r130-local'
    output = ROOT / name
    output.mkdir(exist_ok=False)
    for tag in ['msvc', 'ucrt']:
        folder = ROOT / ('.cache/r130-first-' + tag)
        receipt = json.loads((folder / 'receipt.json').read_bytes())
        assert receipt['passed'] and receipt['buildExitCode'] == receipt['ctestExitCode'] == 0
        assert len(receipt['inputs']) == 295 and receipt['inputs'] == receipt['inputsAfter']
        assert receipt['binariesBefore'] == receipt['binariesAfter'] and len(receipt['binariesBefore']) == 36
        assert inputs is None or inputs == receipt['inputs']
        inputs = receipt['inputs']
        assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 35$', (folder / 'ctest.log').read_text('utf-8-sig'), re.M)
        xmls = sorted((folder / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 34
        verified = [qt(path, 'windows-2022') for path in xmls]
        pictures = []
        for size in ['360x560', '430x700']:
            path = folder / ('Testing/QtTest/budget-report-' + size + '.png')
            assert path.exists()
            pictures.append({'path': path.relative_to(folder).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'viewed': True})
        copy(folder, output / tag)
        records.append({'toolchain': tag, 'ctestTargetsPassed': 35, 'qtXmlReportsVerified': 34,
                        'budgetRowsPassed': 25, 'serverPanelRowsPassed': 11,
                        'newRealQmlSizesPassed': ['360x560', '430x700'], 'screenshots': pictures,
                        'sourceInputsUnchanged': 295, 'binariesUnchanged': 36, 'verifiedQtReports': verified})
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha for name, sha in inputs.items())
    encodings = []
    changed = []
    for row in json.loads((ROOT / '.cache/r130-start/originals.json').read_bytes()):
        raw = (ROOT / row['path']).read_bytes()
        original = (ROOT / '.cache/r130-start/original' / row['path']).read_bytes()
        assert hashlib.sha256(original).hexdigest() == row['sha256']
        assert raw.startswith(b'\xef\xbb\xbf') == row['bom']
        assert (b'\r\n' in raw) == (row['lineEnding'] == 'CRLF')
        raw.decode('utf-8-sig')
        encodings.append(dict(row, preserved=True))
        if raw != original:
            changed.append(row['path'])
    audit = json.loads((ROOT / '.cache/r130-source-audit.json').read_bytes())
    assert not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
    snapshot = json.loads((ROOT / '.cache/r130-source-snapshot-test.json').read_bytes())
    assert snapshot['passed'] and len(snapshot['checks']) == 13
    local = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'records': records,
             'allLocalQualified': True, 'screenshotsViewed': True, 'encodingPreserved': encodings,
             'globalQuotaEnforced': False, 'wholeDomainAccounted': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(local, indent=2) + '\n', 'utf-8')
    for source, destination in [('.cache/r130-source-audit.json', 'source-audit.json'),
                                ('.cache/r130-source-snapshot-test.json', 'source-snapshot.json'),
                                ('.cache/validate-r130-local.py', 'local-driver.py'),
                                ('.cache/verify-r130-results.py', 'test-verifier.py')]:
        shutil.copyfile(ROOT / source, output / destination)
    shutil.copyfile(Path(__file__), output / 'recording-driver.py')
    folders, explicit, counts = previous()
    folders.append(name)
    explicit.update(changed)
    explicit.update(['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/状态预算查询与界面.md',
                     'docs/磁盘总配额实施清单.md', 'docs/ci-verification-20261108-r130.json'])
    glibc_path = ROOT / '.cache/r130-glibc/receipt.json'
    glibc = json.loads(glibc_path.read_bytes()) if glibc_path.exists() else None
    if glibc is not None:
        assert glibc['passed'] and glibc['methodsPassed'] == 4 and glibc['qualificationInputsUnchanged'] == 295
        installed = json.loads((ROOT / '.cache/r130-glibc/installed-source.json').read_bytes())
        assert all(installed['files'][path]['sha256'] == sha for path, sha in inputs.items())
        folder = BASE + 'budget-report-r130-glibc'
        copy(ROOT / '.cache/r130-glibc', ROOT / folder)
        shutil.copyfile(ROOT / '.cache/validate-r130-glibc.py', ROOT / folder / 'verification-driver.py')
        folders.append(folder)
    index = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': None,
             'parentCommit': runpy.run_path('.cache/publish-r120-native-delivery.py')['git']('rev-parse', 'HEAD').decode().strip(),
             'qualificationInputs': [{'path': name, 'bytes': (ROOT / name).stat().st_size, 'sha256': sha} for name, sha in sorted(inputs.items())],
             'receipts': [{'path': folder + '/receipt.json', 'sha256': hashlib.sha256((ROOT / folder / 'receipt.json').read_bytes()).hexdigest()} for folder in folders],
             'allLocalQualified': True, 'nativeCoreJobsVerified': 0, 'nativeTerminalJobsVerified': 0,
             'nativeQualificationPending': True, 'bothMacosCompiled': False, 'macosPackageArchitecturesVerified': 0,
             'independentGlibcReportQualified': glibc is not None,
             'previousProtocolJobsVerified': counts, 'globalQuotaEnforced': False,
             'wholeDomainAccounted': False, 'automaticGcImplemented': False, 'deliveryComplete': False, 'releaseQualified': False}
    (ROOT / 'docs/ci-verification-20261108-r130.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    update = runpy.run_path('.cache/publish-r121-source.py')['update_document']
    section = ('## R130状态预算查询与界面（2026-11-08）\n\n'
               '- [x] GUI“本机共享”新增折叠预算查询，CLI/GUI共用四类别报告；总额/类别的已登记占用、未决预留、剩余额度、超额与原因均为十进制字符串。可回收量明确未知，生产写前限制仍未启用。[用法](docs/状态预算查询与界面.md)。\n'
               '- [x] 查询只打开已有协调根，不初始化目录或业务根；共享占用可查询，失败清空旧快照；不读取身份秘密或逐项路径。健康账本原字节保持，有效写前意图仍按原契约向前恢复。\n'
               '- [x] 双Windows各35完整CTest/34份Qt XML通过；账本25条、服务器面板11条通过，包括大于2^53金额、64位上限、类别/总额透支、GUI/CLI一致、缺失不创建和损坏清屏；两种宽度真实QML按钮及四张截图已验。295输入/36程序前后稳定，原编码/BOM/换行、C++14/格式及252维护文件审计、快照13项通过。[本机原件](docs/' + name.split('docs/', 1)[1] + '/receipt.json)。\n'
               + ('- [x] 独立Ubuntu新目录实际编译、两项报告方法及初始化/清理共4条通过；安装源码、295输入、C++14和程序前后保持。仅授予报告专项。[Linux原件](docs/validation/2026-11-08/budget-report-r130-glibc/receipt.json)。\n' if glibc is not None else '- [ ] 独立Ubuntu报告专项继续原新目录作业，尚未授予通过。\n')
               + '- [ ] 本轮精确源码公开、四原生完整核心/协议和双Mac含依赖包继续；当前可下载Mac预览仍R129。\n'
               '- [ ] Q08仅完成已有账本的公开查询子项；实际生产准入/全部根归属、物理分配/跨卷与回收量、自动GC及完整项目仍未完成。\n\n')
    summary = ('R130预算查询已接入GUI/CLI，双Windows各35核心、25条账本和11条面板通过；'
               + ('独立Ubuntu报告专项4条已验。' if glibc is not None else '独立Ubuntu专项继续。')
               + f'R129完整协议已验{counts[129]}/4，R128已验{counts[128]}/4；双Mac公开下载仍R129。实际写前额度、自动GC与完整项目继续。')
    def plan(text):
        text = text.replace('文档版本：v0.129', '文档版本：v0.130', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：' + summary, text, count=1, flags=re.M)
        text = text.replace('## R129已有状态持久计量', section + '## R129已有状态持久计量', 1)
        text = text.replace('核心已验4/4、完整协议0/4、依赖包2/2。', f'核心已验4/4、完整协议{counts[129]}/4、依赖包2/2。', 1)
        text = re.sub(r'完整协议已按原件核验2/4，其余继续原作业；R126/R127', f'完整协议已按原件核验{counts[128]}/4，其余继续原作业；R126/R127', text, count=1)
        return text
    update('开发计划与进度.md', plan)
    update('docs/执行进度.md', lambda text: plan(text).replace('](docs/', ']('))
    update('README.md', lambda text: re.sub(r'^R129[^\n]*\n', summary + ' [本轮证据](docs/ci-verification-20261108-r130.json)。\n', text, count=1, flags=re.M))
    update('docs/磁盘总配额实施清单.md', lambda text: text.replace('| Q08 | 将实际占用、保留额、可回收量及拒绝原因接入CLI和GUI；数值为64位十进制，报告不暴露令牌/正文。对逻辑长度、物理分配量和保守预留分别说明 | 待实现 |',
           '| Q08 | 将实际占用、保留额、可回收量及拒绝原因接入CLI和GUI；数值为64位十进制，报告不暴露令牌/正文。对逻辑长度、物理分配量和保守预留分别说明 | R130完成已登记账本的GUI/CLI同源查询；实际全部占用/物理分配/跨卷、生产拒绝与可回收量仍待完成 |')
           + '\nR130将已登记预算接入GUI和CLI共同报告，保留范围标识、查询失败清屏和未知可回收量；[契约与验证](状态预算查询与界面.md)。Q08整体不因此完成。\n')
    for name in explicit:
        destination = REPO / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    for folder in folders:
        copy(ROOT / folder, REPO / folder)
    value = {'parentCommit': index['parentCommit'], 'explicitFiles': sorted(explicit), 'evidenceFolders': folders,
             'allLocalQualified': True, 'inputCount': len(inputs), 'independentGlibcReportQualified': glibc is not None,
             'changedProductFiles': changed, 'previousProtocolJobsVerified': counts,
             'deliveryComplete': False, 'releaseQualified': False}
    target.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({'localQualified': True, 'inputCount': len(inputs), 'changedProductFiles': changed, 'previousProtocols': counts}), flush=True)


if __name__ == '__main__':
    main()
