"""日期：2026-11-08；按真实双Windows核心/底层专项原件准备R122进度与公开源码，保留原失败。"""
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


# 日期：2026-11-08；仅允许这一个新测试的六条精确握手信息，其余完整核心沿用既有严格检查。
def budget_junit(path, windows=True):
    tree = ET.fromstring(path.read_bytes(), ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    assert tree.get('failures') == '0' and tree.get('errors') == '6' and tree.get('tests') == '19'
    assert not tree.findall('.//failure') and not tree.findall('.//error')
    expected = {'processesCompeteForLastCredit': 2, 'processesCompeteForSameObject': 2,
                'exitRetainsCreditAndMaintenanceReconciles': 1, 'nativeLockTimeoutAndCancellation': 1}
    cases = tree.findall('testcase')
    assert len(cases) == 19 and all(case.get('result') == 'pass' for case in cases)
    for case in cases:
        comments = [node.text for node in case.iter() if node.tag is ET.Comment]
        assert len(comments) == expected.get(case.get('name'), 0)
        line = '72656164790d0a' if windows else '72656164790a'
        assert all(comment == ' message="Child readiness bytes: ' + line + '" type="qinfo" ' for comment in comments)
    return {'xml': path.name, 'methods': 19, 'rowsPassedFromOriginalTextAndRawXml': 23,
            'diagnostics': {'qinfo': 6}, 'expectedDarwinFailures': []}


# 日期：2026-11-08；证据复制只接受明确原件扩展；私有缓存/执行程序不加入公开目录。
def copy_evidence(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.log', '.xml', '.txt', '.sha256', '.py', '.png']:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                assert destination.read_bytes() == path.read_bytes(), destination
            else:
                shutil.copyfile(path, destination)


# 日期：2026-11-08；完整核心、精确23行和源码身份同时通过后才更新当前完成子项；生产预算仍未接入。
def main():
    local = ROOT / (BASE + 'state-budget-r122-local')
    local.mkdir(exist_ok=False)
    verify = runpy.run_path(str(ROOT / '.cache/collect-r120-full-native-core.py'))['qt']
    records = []
    inputs = None
    for tag in ['msvc', 'ucrt']:
        folder = ROOT / ('.cache/r122-final-' + tag)
        value = json.loads((folder / 'receipt.json').read_bytes())
        assert value['passed'] and value['buildExitCode'] == value['ctestExitCode'] == 0
        assert value['inputs'] == value['inputsAfter'] and value['binariesBefore'] == value['binariesAfter']
        assert re.search(r'100% tests passed(?:, 0 tests failed)? out of 31', (folder / 'ctest.log').read_text('utf-8-sig'))
        assert inputs is None or inputs == value['inputs']
        inputs = value['inputs']
        for name, sha in inputs.items():
            assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha, name
        xmls = sorted((folder / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 30
        verified = [budget_junit(path) if path.name == 'state-budget-tests.xml' else verify(path, 'windows-2022') for path in xmls]
        focused = ROOT / ('.cache/r122-focused-' + tag)
        focused_receipt = json.loads((focused / 'receipt.json').read_bytes())
        assert focused_receipt['passed'] and focused_receipt['rowsPassed'] == 23
        assert focused_receipt['inputs'] == inputs == focused_receipt['inputsAfter']
        assert focused_receipt['binaryBefore'] == focused_receipt['binaryAfter'] == value['binariesBefore']['state-budget-tests.exe']
        copy_evidence(folder, local / tag)
        copy_evidence(focused, local / (tag + '-focused'))
        records.append({'toolchain': tag, 'completeCtestTargetsPassed': 31, 'qtXmlReportsVerified': 30,
                        'budgetRowsPassed': 23, 'budgetSkipped': 0, 'budgetWarnings': 0,
                        'allExecutedTestBinariesAndInputsUnchanged': True, 'verifiedQtReports': verified})
    for name in ['r122-first-msvc', 'r122-second-msvc', 'r122-qualified-ucrt']:
        copy_evidence(ROOT / '.cache' / name, local / name)
    audit = json.loads((ROOT / '.cache/r122-final-source-audit.json').read_bytes())
    assert audit['sourceMarkersPassed'] and not audit['findings'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    shutil.copyfile(ROOT / '.cache/r122-final-source-audit.json', local / 'source-audit.json')
    for name in ['validate-r122-final-windows.py', 'validate-r122-first-budget.py', 'validate-r122-second-budget.py']:
        shutil.copyfile(ROOT / '.cache' / name, local / name)
    shutil.copyfile(Path(__file__), local / 'preparation-driver.py')
    before = json.loads((ROOT / '.cache/r122-start/inputs.json').read_bytes())
    for row in before:
        raw = (ROOT / row['path']).read_bytes()
        assert raw.startswith(b'\xef\xbb\xbf') == row['bom'] and (b'\r\n' in raw) == row['crlf']
    shutil.copyfile(ROOT / '.cache/r122-start/inputs.json', local / 'encoding-before.json')
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'records': records,
              'bothWindowsCompleteCoreQualified': True, 'durableBudgetFoundationQualifiedLocally': True,
              'budgetFixedBytes': 1056768, 'budgetSlots': 4096, 'sourceMarkersPassed': True,
              'maintenanceSourceFilesAudited': len(audit['files']), 'encodingBomAndLineEndingsPreserved': True,
              'runtimeOwnershipRegistryImplemented': False, 'globalQuotaEnforced': False,
              'automaticGcImplemented': False, 'deliveryComplete': False, 'releaseQualified': False}
    (local / 'receipt.json').write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    terminal_name = BASE + 'state-inventory-r121-native-terminal'
    terminal = json.loads((REPO / terminal_name / 'receipt.json').read_bytes())
    count = sum(row['qualified'] for row in terminal['records'])
    shutil.copyfile(REPO / terminal_name / 'receipt.json', ROOT / terminal_name / 'receipt.json')
    copy_evidence(REPO / terminal_name, ROOT / terminal_name)
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    section = """## R122持久预算账本底层（2026-11-08）

- [x] 新增受保护永久账本、同实例线程互斥和原生跨进程锁。四类别/总额、4096固定槽、1,056,768字节固定文件，账本自身计入Metadata；格式、域/根身份、私有权限及单链接核对。
- [x] 登记代数/修订协调、持久预留、最近完成幂等、超预期占用透支、维护核对/退役及ABA拒绝已实现。异常退出不退款，未知/损坏意图保留；完整合法意图只向前重放。[格式及调用契约](docs/持久预算账本底层.md)。
- [x] 双Windows最终各31完整核心/30份Qt XML通过，底层专项各23行、零跳过/警告；实际两进程最后额度/同对象竞争、直接退出重开、四线程、五种恢复布局、旧/撕裂意图、溢出和固定槽耗尽均核验。全部274份资格输入和CLI/GUI/全部测试程序前后摘要一致。[严格原件](docs/validation/2026-11-08/state-budget-r122-local/receipt.json)。
- [x] 首轮MSVC握手只接受LF而实际为CRLF导致夹具异常，原件保留；修正精确行尾、分段等待和子进程回收。UCRT首轮QUuid空赋值重载歧义保留，改显式构造后完成最终回归。236维护文件零TODO/占位/简化标记，C++14/格式及原编码/BOM/换行通过。
- [ ] 独立Ubuntu和新四原生底层专项/完整回归/双Mac包须按真实原件收验；当前Mac含依赖包保持已验R121。该底层尚未接入生产写入，不标Q03整体或总预算完成；全根归属、实际分配对账、SQLite/原子替换/正文接入、自动GC及全部交付继续。

"""
    summary = ('R122持久预算底层及双Windows各31完整核心/30份Qt XML、账本23行专项已验；'
               '生产预算接入和新原生验证继续。双Mac可用含依赖包保持已验R121；'
               'R121完整协议终态已验' + str(count) + '/4。跨状态根总预算、自动GC和完整交付未完成。')
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace('文档版本：v0.121', '文档版本：v0.122', 1).replace('## 全状态入口核对', section + '## 全状态入口核对', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace('## 全状态入口核对', section.replace('](docs/', '](') + '## 全状态入口核对', 1))
    update('README.md', lambda text: text.replace('R121应用源d924ba5c、', summary + ' [本轮证据](docs/ci-verification-20261108-r122.json)。\n\nR121应用源d924ba5c、', 1))
    for name in ['开发计划与进度.md', 'docs/执行进度.md', 'README.md', 'docs/macOS独立预览包.md']:
        update(name, lambda text: re.sub(r'(R121完整协议按独立终态已验|完整协议终态已验)2/4', r'\g<1>' + str(count) + '/4', text))
    update('docs/磁盘总配额实施清单.md', lambda text: text.replace('Q02整体及其他项尚未完成。',
           'R122实现并本机验证Q03的固定持久账本底层，生产写入尚未接入；Q02/Q03整体及其他项继续。', 1)
           .replace('活动写入不能只靠启动前的一次扫描 | 待实现 |', '活动写入不能只靠启动前的一次扫描 | 固定账本/原生锁及双Windows23行底层专项已验；全根归属、实际I/O对账及生产接入待完成 |', 1)
           + '\nR122固定格式、调用契约、已验子项与拒绝恢复边界见[持久预算账本底层](持久预算账本底层.md)。Q03整体、生产预算及自动GC仍未完成。\n')
    update('docs/跨进程磁盘预算设计.md', lambda text: text + '\nR122已实现固定账本与原生互斥底层，格式/调用契约与实际验证见[持久预算账本底层](持久预算账本底层.md)。以上业务接入顺序仍继续；构建接口不等于生产写入已受限。\n')
    old_index_path = REPO / 'docs/ci-verification-20261108-r121.json'
    old_index = json.loads(old_index_path.read_bytes())
    old_index.update(observedUtc=record['observedUtc'], nativeRun=terminal['run'], nativeTerminalJobsVerified=count,
                     fullNativeProtocolQualified=terminal['allFourNativeProtocolJobsVerified'], nativeQualificationPending=count != 4)
    for row in old_index['receipts']:
        row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
    old_index_path.write_text(json.dumps(old_index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(old_index_path, ROOT / old_index_path.relative_to(REPO))
    old = {row['path']: row['sha256'] for row in old_index['ciQualificationInputs']}
    changed = [name for name, sha in sorted(inputs.items()) if old.get(name) != sha]
    assert len(changed) == 9 and len(inputs) == 274, (changed, len(inputs))
    for name in changed + ['docs/持久预算账本底层.md']:
        (REPO / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, REPO / name)
    copy_evidence(local, REPO / local.relative_to(ROOT))
    value = {'observedUtc': record['observedUtc'], 'qualificationInputs': [
                 {'path': name, 'bytes': (ROOT / name).stat().st_size, 'sha256': sha} for name, sha in sorted(inputs.items())],
             'inputCount': len(inputs), 'changedInputs': changed, 'localWindowsAllCoreQualified': True,
             'localCtestTargetsEach': 31, 'localQtXmlEach': 30, 'localBudgetRowsEach': 23,
             'nativeQualificationPending': True, 'independentGlibcQualificationPending': True,
             'runtimeOwnershipRegistryImplemented': False, 'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'receipts': [{'path': (local / name).relative_to(ROOT).as_posix(), 'sha256': hashlib.sha256((local / name).read_bytes()).hexdigest()}
                          for name in ['receipt.json', 'source-audit.json']],
             'deliveryComplete': False, 'releaseQualified': False}
    path = ROOT / 'docs/ci-verification-20261108-r122.json'
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(path, REPO / path.relative_to(ROOT))
    print(json.dumps({'inputCount': len(inputs), 'changedInputs': changed, 'coreEach': 31,
                      'budgetRowsEach': 23, 'r121NativeTerminalJobsVerified': count}), flush=True)


if __name__ == '__main__':
    main()
