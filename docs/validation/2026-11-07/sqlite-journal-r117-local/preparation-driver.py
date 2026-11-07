"""日期：2026-11-07；冻结R117四项候选及真实双Windows/原生证据，逐项更新文档并保持原编码。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = REPO / 'docs/validation/2026-11-07'
CHANGED = ['src/core/privatestore.cpp', 'src/core/privatestore.h',
           'src/core/uploadmanifest.cpp', 'tests/upload_scan_cleanup_tests.cpp']


# 日期：2026-11-07；JSON新建使用UTF-8/LF，已有文档保持其原BOM和换行，不加工日志原件。
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


# 日期：2026-11-07；文档内容按真实资格更新，历史结果和待办范围保留。
def edit(name, callback):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    path.write_bytes(bom + callback(text).replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-07；先验证真实结果与全部输入，再建立发布清单；代码通过不替代全功能交付。
def main():
    local = BASE / 'sqlite-journal-r117-local'
    assert not local.exists()
    local.mkdir()
    verify = runpy.run_path('.cache/collect-r117-windows-native.py')['verify_scan']
    rows = []
    for tag in ['msvc', 'ucrt']:
        original = ROOT / ('.cache/r117-' + tag)
        receipt = json.loads((original / 'receipt.json').read_bytes())
        assert receipt['passed'] and receipt['buildExitCode'] == receipt['ctestExitCode'] == 0
        assert receipt['inputs'] == receipt['inputsAfter']
        assert receipt['binariesBefore'] == receipt['binariesAfter']
        assert re.search(r'100% tests passed(?:, 0 tests failed)? out of 27', (original / 'ctest.log').read_text('utf-8-sig'))
        xmls = list((original / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 26
        for xml in xmls:
            tree = ET.fromstring(xml.read_bytes())
            assert tree.get('failures') == '0' and not tree.findall('.//failure') and not tree.findall('.//error')
            for case in tree.findall('testcase'):
                assert case.get('result') == 'pass' or (xml.name == 'upload-scan-cleanup-tests.xml' and case.get('name') in ['unsafeObjects', 'unsafeJournalLinks'] and case.get('result') == 'skip')
        scan = verify(original / 'Testing/QtTest')
        assert scan['rowsPassed'] == 27 and scan['rowsSkipped'] == 2
        shutil.copytree(original, local / tag)
        rows.append({'toolchain': tag, 'completeCoreCtestsPassed': 27, 'qtXmlOriginalsVerified': 26, 'scan': scan})
    audit = json.loads((ROOT / '.cache/r117-source-audit.json').read_bytes())
    assert len(audit['files']) == 219 and not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
    shutil.copyfile(ROOT / '.cache/r117-source-audit.json', local / 'source-audit.json')
    shutil.copyfile(ROOT / '.cache/validate-r117-windows.py', local / 'validation-driver.py')
    shutil.copyfile(ROOT / '.cache/r117-frozen-long-observation.json', local / 'frozen-long-observation.json')
    prior = json.loads((REPO / 'docs/ci-verification-20261107-r116.json').read_bytes())
    frozen = []
    changes = []
    for row in prior['qualificationInputs']:
        name = row['path']
        raw = (ROOT / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row['sha256']:
            changes.append(name)
        if name in CHANGED:
            before = (ROOT / '.cache/r117-before' / name).read_bytes()
            assert raw.startswith(b'\xef\xbb\xbf') == before.startswith(b'\xef\xbb\xbf')
            assert (b'\r\n' in raw) == (b'\r\n' in before)
            shutil.copyfile(ROOT / name, REPO / name)
        assert (REPO / name).read_bytes() == raw
        frozen.append({'path': name, 'bytes': len(raw), 'sha256': digest})
    assert len(frozen) == 245 and set(changes) == set(CHANGED)
    native = json.loads((BASE / 'sqlite-journal-r117-windows-native/receipt.json').read_bytes())
    assert native['passed'] and all(row['rowsPassed'] == 29 and row['rowsSkipped'] == 0 for row in native['rounds'])
    owner = json.loads((BASE / 'upload-scan-r116-windows-owner-diagnostic/receipt.json').read_bytes())
    owner_rows = [row for row in owner['originalDiagnosticMessages'] if row.startswith('journal-owner')]
    assert owner_rows == ['journal-owner user=0 token-default=1 builtin-admins=1 elevated=1 other-allowed=0'] * 2
    write(local / 'receipt.json', {'observedUtc': datetime.now(timezone.utc).isoformat(), 'records': rows,
          'qualificationInputs': frozen, 'changedInputs': changes, 'inputCount': len(frozen),
          'nativeWindowsTwoRoundsQualified': True, 'allExistingEncodingBomNewlinePreserved': True,
          'originalNativeOwnerFailurePreserved': True, 'passed': True, 'deliveryComplete': False, 'releaseQualified': False})
    paths = [local / 'receipt.json', local / 'source-audit.json', local / 'frozen-long-observation.json',
             BASE / 'sqlite-journal-r117-windows-native/receipt.json', BASE / 'upload-scan-r116-windows-owner-diagnostic/receipt.json']
    index = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'planVersion': 'v0.117',
             'baselineSourceCommit': '9700e05a5b147912ae4192ea82b805dd3e6198ce',
             'qualificationInputs': frozen, 'inputCount': len(frozen), 'changedInputs': changes,
             'receipts': [{'path': p.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths],
             'localWindowsAllCoreQualified': True, 'nativeWindowsTwoScanRoundsQualified': True,
             'sourcePublicationPending': True, 'nativeQualificationPending': True,
             'deliveryComplete': False, 'releaseQualified': False}
    write(REPO / 'docs/ci-verification-20261107-r117.json', index)
    terminal = BASE / 'upload-scan-r116-native-terminal/receipt.json'
    if not any(row['path'] == terminal.relative_to(REPO).as_posix() for row in prior['receipts']):
        prior['receipts'].append({'path': terminal.relative_to(REPO).as_posix()})
    for row in prior['receipts']:
        row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
    prior['observedUtc'] = datetime.now(timezone.utc).isoformat()
    write(REPO / 'docs/ci-verification-20261107-r116.json', prior)
    section = '''## R117 Windows 原生 SQLite 日志恢复（2026-11-07）

- [x] 两轮原生补充诊断证明热journal采用提升进程默认Administrators所有者，DACL仍仅当前用户；原4/identity失败保留。[诊断原件](docs/validation/2026-11-07/upload-scan-r116-windows-owner-diagnostic/receipt.json)。
- [x] 专门日志校验只供独占维护及规范.sqlite-journal；默认管理员所有者须同时匹配当前提升令牌，DACL仍仅当前用户。普通库/根/凭据规则保持，日志另拒绝多硬链接。[设计边界](docs/decisions/0030-Windows原生SQLite回滚日志所有者.md)。
- [x] MSVC/UCRT各27完整CTest及26份Qt原件通过；清理专项各27条通过/2条本机符号链接权限跳过。新增键/维护边界、宽权限拒绝和真实硬链接拒绝通过，拒绝后库/日志/凭据原字节不变。[本机原件](docs/validation/2026-11-07/sqlite-journal-r117-local/receipt.json)。
- [x] GitHub Windows相同应用/测试输入两轮各29条全通过，包括真实符号链接、热日志恢复、实际CLI及缓存耗尽重试；执行前后二进制保持。收验器首次CTest摘要格式假设失败另行保留，不修改生产测试门槛。[原生专项](docs/validation/2026-11-07/sqlite-journal-r117-windows-native/receipt.json)。
- [x] 219份维护文件零TODO/占位标记、C++14、全量C++格式及原编码/BOM/换行通过；R116 Ubuntu/Apple Silicon完整协议各47项原件已验，其余作业继续单独收验。
- [ ] R117公开提交、四原生完整回归及新双Mac编译/含依赖预览按精确输入继续；当前可下载Mac包仍为R116。冻结R98长测继续运行，最近Windows230轮/69519秒、Ubuntu197轮/64596秒，不转授当前版本24h资格。
- [ ] 未知身份临时项、全局自动GC/磁盘预算、完整R6 GUI、物理LAN/3×3、各平台当前版本24h、最低干净系统、依赖源码重建及正式分发未完成；deliveryComplete=false、releaseQualified=false。

'''
    def plan(text):
        text = text.replace('文档版本：v0.116', '文档版本：v0.117', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R117已修复Windows原生SQLite热journal默认管理员所有者误拒绝；本机双工具链各27核心及原生Windows两轮各29条通过，准备公开及新双Mac编译/预览。当前可下载双Mac包仍为R116；R116 Ubuntu/Apple Silicon完整协议各47项已验，其余终态继续。整体与正式发布未完成。', text, count=1, flags=re.M)
        text = text.replace('v0.116 / 源扫描清理与资源失败恢复', 'v0.117 / Windows原生回滚日志恢复', 1)
        assert '## R117 ' not in text
        return text.replace('## R116 未发布源扫描清理', section + '## R116 未发布源扫描清理', 1)
    edit('开发计划与进度.md', plan)
    edit('docs/执行进度.md', lambda text: text.replace('## R116未发布源扫描清理',
         '## R117 Windows原生回滚日志恢复（2026-11-07）\n\n两轮原生诊断确认默认管理员所有者；专门journal接口仅限独占维护、提升令牌默认所有者且私有DACL，普通文件规则保持。双Windows各27核心通过，GitHub Windows两轮专项各29条全通过；宽权限与真实链接拒绝、原件保持已验。新Mac编译/包及完整原生回归继续。[设计](decisions/0030-Windows原生SQLite回滚日志所有者.md)、[输入及证据](ci-verification-20261107-r117.json)。\n\n## R116未发布源扫描清理', 1))
    edit('docs/decisions/0030-Windows原生SQLite回滚日志所有者.md', lambda text: text.replace('修复已实现，原生复验中', '修复、本机双Windows完整核心及GitHub Windows两轮专项通过；其他原生回归另验', 1))
    for name in ['docs/ci-verification-20261107-r116.json', 'docs/ci-verification-20261107-r117.json']:
        shutil.copyfile(REPO / name, ROOT / name)
    for name in ['sqlite-journal-r117-local', 'sqlite-journal-r117-windows-native',
                 'upload-scan-r116-windows-owner-diagnostic', 'upload-scan-r116-native-terminal']:
        shutil.copytree(BASE / name, ROOT / 'docs/validation/2026-11-07' / name, dirs_exist_ok=True)
    shutil.copyfile(Path(__file__), local / 'preparation-driver.py')
    print(json.dumps({'inputs': len(frozen), 'changedInputs': changes, 'windowsCorePassedEach': 27,
                      'nativeScanPassedEachRound': 29, 'publicationPending': True}), flush=True)


if __name__ == '__main__':
    main()
