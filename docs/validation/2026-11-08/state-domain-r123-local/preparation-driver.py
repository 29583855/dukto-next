"""日期：2026-11-08；只根据实际双Windows结果更新持久域子项，补收R122和原Ubuntu长测边界。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；仅复制明确有界原件，既有文件不同则拒绝，不覆盖原失败记录。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.xml', '.log', '.txt', '.py', '.sha256', '.csv']:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                assert destination.read_bytes() == path.read_bytes(), destination
            else:
                shutil.copyfile(path, destination)


# 日期：2026-11-08；原32核心、原XML和独立12条收验同时核对，不以新增脚本要求重复执行已通过核心。
def main():
    local = ROOT / (BASE + 'state-domain-r123-local')
    local.mkdir(exist_ok=False)
    previous = json.loads((ROOT / 'docs/ci-verification-20261108-r122.json').read_bytes())
    old = {row['path']: row['sha256'] for row in previous['qualificationInputs']}
    check = runpy.run_path(str(ROOT / '.cache/collect-r122-full-native-core.py'))['qt']
    inputs = None
    records = []
    for tag in ['msvc', 'ucrt']:
        folder = ROOT / ('.cache/r123-first-' + tag)
        focused = ROOT / ('.cache/r123-focused-' + tag)
        value = json.loads((folder / 'receipt.json').read_bytes())
        extra = json.loads((focused / 'receipt.json').read_bytes())
        assert value['passed'] and value['buildExitCode'] == value['ctestExitCode'] == 0
        assert value['inputs'] == value['inputsAfter'] and len(value['inputs']) == 277
        assert value['binariesBefore'] == value['binariesAfter']
        assert extra['passed'] and extra['rowsPassed'] == 12 and len(extra['inputs']) == 279
        assert extra['inputs'] == extra['inputsAfter']
        assert extra['binaryBefore'] == extra['binaryAfter'] == value['binariesBefore']['state-domain-tests.exe']
        assert all(extra['inputs'][name] == sha for name, sha in value['inputs'].items())
        assert inputs is None or inputs == extra['inputs']
        inputs = extra['inputs']
        for name, sha in inputs.items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
        assert re.search(r'100% tests passed(?:, 0 tests failed)? out of 32', (folder / 'ctest.log').read_text('utf-8-sig'))
        xmls = sorted((folder / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 31
        verified = [check(path, 'windows-2022') for path in xmls]
        domain = ET.fromstring((folder / 'Testing/QtTest/state-domain-tests.xml').read_bytes())
        assert domain.get('tests') == '12' and domain.get('errors') == domain.get('failures') == '0'
        runpy.run_path(str(ROOT / 'scripts/ci_state_domain.py'))['verify_xml'](focused / 'state-domain-tests.xml')
        copy(folder, local / tag)
        copy(focused, local / (tag + '-focused'))
        records.append({'toolchain': tag, 'ctestTargetsPassed': 32, 'qtXmlReportsVerified': 31,
                        'domainMethodsPassed': 12, 'domainWarnings': 0, 'domainSkipped': 0,
                        'coreInputsUnchanged': 277, 'focusedInputsUnchanged': 279,
                        'allExecutedBinariesUnchanged': True, 'verifiedQtReports': verified})
    before = json.loads((ROOT / '.cache/r123-start/inputs.json').read_bytes())
    for row in before:
        raw = (ROOT / row['path']).read_bytes()
        assert raw.startswith(b'\xef\xbb\xbf') == row['bom'] and (b'\r\n' in raw) == row['crlf']
    audit = json.loads((ROOT / '.cache/r123-source-audit.json').read_bytes())
    assert audit['sourceMarkersPassed'] and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    shutil.copyfile(ROOT / '.cache/r123-source-audit.json', local / 'source-audit.json')
    shutil.copyfile(ROOT / '.cache/r123-start/inputs.json', local / 'encoding-before.json')
    for name in ['validate-r123-windows.py', 'validate-r123-domain.py']:
        shutil.copyfile(ROOT / '.cache' / name, local / name)
    shutil.copyfile(Path(__file__), local / 'preparation-driver.py')
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'records': records,
               'bothWindowsCoreQualified': True, 'rootBindingFoundationQualifiedLocally': True,
               'maintenanceFilesAudited': len(audit['files']), 'encodingBomAndNewlinesPreserved': True,
               'productionRootsIntegrated': False, 'globalQuotaEnforced': False,
               'automaticGcImplemented': False, 'deliveryComplete': False, 'releaseQualified': False}
    (local / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    glibc = json.loads((ROOT / '.cache/r122-glibc/receipt.json').read_bytes())
    installed = json.loads((ROOT / '.cache/r122-glibc/installed-source.json').read_bytes())
    assert glibc['passed'] and glibc['rowsPassed'] == 23 and glibc['allInstalledSourceInputsUnchanged']
    for row in previous['qualificationInputs']:
        assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}
    glibc_folder = ROOT / (BASE + 'state-budget-r122-glibc')
    glibc_folder.mkdir(exist_ok=False)
    copy(ROOT / '.cache/r122-glibc', glibc_folder)
    shutil.copyfile(ROOT / '.cache/validate-r122-glibc.py', glibc_folder / 'verification-driver.py')
    terminal_name = BASE + 'state-budget-r122-native-terminal'
    terminal = json.loads((REPO / terminal_name / 'receipt.json').read_bytes())
    assert terminal['sourceCommit'] == '15bd1d0c5e0a484a28da9a1596af726b512d5b8a'
    copy(REPO / terminal_name, ROOT / terminal_name)
    count = sum(row['qualified'] for row in terminal['records'])
    previous.update(observedUtc=receipt['observedUtc'], independentGlibcQualified=True,
                    independentGlibcQualificationPending=False, nativeTerminalJobsVerified=count,
                    fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'])
    refs = {row['path'] for row in previous['receipts']} | {glibc_folder.relative_to(ROOT).as_posix() + '/receipt.json', terminal_name + '/receipt.json'}
    for name in sorted(refs):
        path = ROOT / name
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO / name, path)
    previous['receipts'] = [{'path': name, 'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in sorted(refs)]
    (ROOT / 'docs/ci-verification-20261108-r122.json').write_text(json.dumps(previous, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    summary = ('R123持久预算域/多根关联底层和双Windows各32核心/31份Qt XML、12条专项通过；'
               'R122独立Ubuntu23条通过。新四原生/双Mac源码验证继续，当前可下载含依赖包为已验R122。'
               '生产全根/SQLite/正文预算、自动GC与完整交付仍未完成。')
    section = f'''## R123持久预算域与多根关联（2026-11-08）

- [x] 新增持久域发现、协调根/成员根生命周期及原生身份绑定；成员显式独占登记，共享使用只核对。相同路径别名/重复登记不重复计量，跨域、复制、损坏/截断、中央失效及旧登记拒绝。[接口和中断边界](docs/持久预算域与根关联.md)。
- [x] 固定256字节标记在创建前持久计入Metadata；真实进程在预扣后、写标记前直接退出仍保留额度。缺失标记的新显式登记使用新代数并再次计量，旧登记继续保留；没有按PID退款或覆盖未知残片。
- [x] 双Windows完整构建、各32核心/31份Qt XML通过；新增12条专项、真实进程维护占用/强退重开和四线程共用域均通过。原核心277输入及全部执行程序前后不变，另以同一程序核对原始XML/CI收验器和279输入；没有重复执行完整核心。[原件](docs/validation/2026-11-08/state-domain-r123-local/receipt.json)。
- [x] 240份维护文件零TODO/占位/简化标记，C++14/格式与四个原修改文件编码/BOM/换行保持；原版参考目录未修改。
- [x] R122独立Ubuntu新目录真实编译及23条账本专项通过，425安装源码、274资格输入、C++14及程序前后摘要核对；完整原生协议按原作业当前已验{count}/4，不转授R123。[Ubuntu原件](docs/validation/2026-11-08/state-budget-r122-glibc/receipt.json)。
- [x] R98 Ubuntu旧冻结长测完成86400.021秒、262轮/16通道，业务和资源子项通过；glib系统依赖漂移导致原驱动最终passed=false，完整长期资格不授予。原始失败和全部262行保留，不修改原driver断言。收验器首次误比包装脚本摘要，纠正为原核心脚本并核对七输入，未重跑产品。[终态边界](docs/validation/2026-11-08/r98-ubuntu-long-terminal/receipt.json)。
- [ ] R123独立Ubuntu新目录、四原生完整核心/协议及双Mac编译/部署须按精确源码继续收验。生产入口尚未自动接入；实际物理占用/跨卷准入、业务归属/SQLite/正文总预算和自动GC、完整R6/原生选择器、物理LAN/3×3、当前三平台24h、依赖源码重建、最低干净系统与正式发布继续，整体active。

'''
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace('文档版本：v0.122', '文档版本：v0.123', 1).replace('## R122四原生账本与双Mac交付', section + '## R122四原生账本与双Mac交付', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace('## R122四原生账本与双Mac交付', section.replace('](docs/', '](') + '## R122四原生账本与双Mac交付', 1))
    update('README.md', lambda text: text.replace('R122精确15bd1d0c的', summary + ' [本轮证据](docs/ci-verification-20261108-r123.json)。\n\nR122精确15bd1d0c的', 1)
           .replace('独立Ubuntu仍在新目录构建。', '独立Ubuntu新目录23条账本专项通过。'))
    update('docs/状态存储归属清单.md', lambda text: text + '\nR123已实现显式协调根/成员根的持久关联底层，见[域与根关联](持久预算域与根关联.md)。生产入口映射、业务文件归属、未知项计量与退出恢复仍未接入，不标Q01整体完成。\n')
    update('docs/磁盘总配额实施清单.md', lambda text: text + '\nR123实现并本机验证持久预算域和多根关联底层，固定标记先计量再创建，跨文件中断保留占用；[契约](持久预算域与根关联.md)。生产GUI/CLI/服务入口、实际分配量、SQLite/原子替换/正文及未知项仍须统一接入，Q01/Q03整体继续。\n')
    changed = [name for name, sha in inputs.items() if old.get(name) != sha]
    assert len(changed) == 9, changed
    extra_docs = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/状态存储归属清单.md',
                  'docs/磁盘总配额实施清单.md', 'docs/持久预算域与根关联.md', 'docs/ci-verification-20261108-r122.json']
    folders = [local.relative_to(ROOT).as_posix(), glibc_folder.relative_to(ROOT).as_posix(),
               terminal_name, BASE + 'r98-ubuntu-long-terminal']
    for name in changed + extra_docs:
        (REPO / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, REPO / name)
    for folder in folders:
        copy(ROOT / folder, REPO / folder)
    value = {'observedUtc': receipt['observedUtc'], 'qualificationInputs': [
                 {'path': name, 'bytes': (ROOT / name).stat().st_size, 'sha256': sha} for name, sha in sorted(inputs.items())],
             'inputCount': len(inputs), 'changedInputs': changed,
             'localWindowsAllCoreQualified': True, 'localCtestTargetsEach': 32, 'localQtXmlEach': 31,
             'localDomainMethodsEach': 12, 'rootBindingFoundationQualifiedLocally': True,
             'nativeQualificationPending': True, 'independentGlibcQualificationPending': True,
             'productionRootsIntegrated': False, 'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'receipts': [{'path': folder + '/receipt.json', 'sha256': hashlib.sha256((ROOT / folder / 'receipt.json').read_bytes()).hexdigest()} for folder in folders],
             'deliveryComplete': False, 'releaseQualified': False}
    path = ROOT / 'docs/ci-verification-20261108-r123.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(path, REPO / path.relative_to(ROOT))
    prepared = {'evidenceFolders': folders, 'explicitFiles': sorted(set(changed + extra_docs + [path.relative_to(ROOT).as_posix()])),
                'inputCount': len(inputs), 'allLocalQualified': True}
    (ROOT / '.cache/r123-source-prepared.json').write_text(json.dumps(prepared, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'inputs': len(inputs), 'changedInputs': changed, 'ctestEach': 32, 'methodsEach': 12,
                      'r122FullProtocolJobs': count, 'releaseQualified': False}))


if __name__ == '__main__':
    main()
