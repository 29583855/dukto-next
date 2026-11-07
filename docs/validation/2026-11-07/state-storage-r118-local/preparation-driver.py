"""日期：2026-11-07；按真实双Windows结果冻结R118计量输入，保留历史失败与既有文件编码。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = REPO / 'docs/validation/2026-11-07'
CHANGED = ['CMakeLists.txt', 'src/core/nativecommit.h', 'src/core/privatestore.h',
           'src/cli/main.cpp', 'src/cli/servicecommands.cpp']
ADDED = ['src/core/stateinventory.cpp', 'tests/state_storage_tests.cpp']


# 日期：2026-11-07；仅写新JSON；已有文本通过edit保持BOM和换行，日志原件按字节复制。
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


# 日期：2026-11-07；文档补充真实结果，不将计量基础标作总配额或自动回收完成。
def edit(name, callback):
    path = ROOT / name
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    old = raw[len(bom):].decode('utf-8').replace('\r\n', '\n')
    new = callback(old)
    assert new != old, name
    path.write_bytes(bom + new.replace('\n', newline).encode('utf-8'))
    shutil.copyfile(path, REPO / name)


# 日期：2026-11-07；先核对28个完整CTest/27份XML及精确跳过，随后更新明确的本轮进度。
def main():
    local = BASE / 'state-storage-r118-local'
    assert not local.exists()
    rows = []
    for tag in ['msvc', 'ucrt']:
        original = ROOT / ('.cache/r118-' + tag)
        value = json.loads((original / 'receipt.json').read_bytes())
        assert value['passed'] and value['buildExitCode'] == value['ctestExitCode'] == 0
        assert value['inputs'] == value['inputsAfter']
        assert value['binariesBefore'] == value['binariesAfter']
        assert re.search(r'100% tests passed(?:, 0 tests failed)? out of 28', (original / 'ctest.log').read_text('utf-8-sig'))
        xmls = sorted((original / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 27, len(xmls)
        for xml in xmls:
            tree = ET.fromstring(xml.read_bytes(), ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
            assert tree.get('failures') == '0' and not tree.findall('.//failure') and not tree.findall('.//error')
            comments = [node.text for node in tree.iter() if node.tag is ET.Comment]
            assert int(tree.get('errors', '0')) == len(comments)
            for comment in comments:
                if 'type="skip"' in comment:
                    assert xml.name in ['upload-scan-cleanup-tests.xml', 'state-storage-tests.xml']
                    assert 'message="Windows account cannot create a native symbolic link"' in comment
                    if xml.name == 'upload-scan-cleanup-tests.xml':
                        assert 'tag="symbolic&#x002D;link"' in comment or 'tag="symbolic-link"' in comment
                elif 'type="qinfo"' in comment:
                    assert xml.name == 'file-exchange-tests.xml' and 'terminal fixture ' in comment
                else:
                    assert 'type="qwarn"' in comment and xml.name == 'avatars-tests.xml'
                    assert 'QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once.' in comment
            for case in tree.findall('testcase'):
                assert case.get('result') == 'pass' or (
                    xml.name == 'state-storage-tests.xml' and
                    case.get('name') == 'nativeSymbolicLinkIsExcluded' and
                    case.get('result') is None and len(list(case)) == 1 and
                    list(case)[0].tag is ET.Comment and 'type="skip"' in list(case)[0].text), (xml, case.attrib)
        text = (original / 'Testing/QtTest/state-storage-tests.log').read_text('utf-8-sig')
        assert 'Totals: 10 passed, 0 failed, 1 skipped' in text
        assert 'Windows account cannot create a native symbolic link' in text
        assert 'PASS   : StateStorageTests::realCli(client)' in text
        assert 'PASS   : StateStorageTests::realCli(serve)' in text
        shutil.copytree(original, local / tag)
        rows.append({'toolchain': tag, 'completeCoreCtestsPassed': 28, 'qtXmlOriginalsVerified': 27,
                     'storageRowsPassed': 10, 'storageRowsSkipped': 1,
                     'nativeSymbolicLinkQualified': False})
    shutil.copytree(ROOT / '.cache/r118-first-failure', local / 'first-fixture-failure')
    for name in ['r118-source-audit.json', 'validate-r118-windows.py']:
        shutil.copyfile(ROOT / '.cache' / name, local / name)
    shutil.copyfile(Path(__file__), local / 'preparation-driver.py')
    audit = json.loads((ROOT / '.cache/r118-source-audit.json').read_bytes())
    assert len(audit['files']) == 221 and not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
    previous = json.loads((REPO / 'docs/ci-verification-20261107-r117.json').read_bytes())
    frozen, changed = [], []
    for row in previous['qualificationInputs']:
        name = row['path']
        raw = (ROOT / name).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row['sha256']:
            changed.append(name)
        if name in CHANGED:
            before = (ROOT / '.cache/r118-before' / name).read_bytes()
            assert raw.startswith(b'\xef\xbb\xbf') == before.startswith(b'\xef\xbb\xbf'), name
            assert (b'\r\n' in raw) == (b'\r\n' in before), name
            shutil.copyfile(ROOT / name, REPO / name)
        assert (REPO / name).read_bytes() == raw, name
        frozen.append({'path': name, 'bytes': len(raw), 'sha256': digest})
    assert set(changed) == set(CHANGED)
    for name in ADDED:
        raw = (ROOT / name).read_bytes()
        shutil.copyfile(ROOT / name, REPO / name)
        frozen.append({'path': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    assert len(frozen) == 247
    write(local / 'receipt.json', {'observedUtc': datetime.now(timezone.utc).isoformat(), 'records': rows,
          'qualificationInputs': frozen, 'changedInputs': CHANGED + ADDED,
          'inputCount': len(frozen), 'firstFixtureFailureOriginalsPreserved': True,
          'allExistingEncodingBomNewlinePreserved': True,
          'globalQuotaEnforced': False, 'automaticGcImplemented': False,
          'passed': True, 'deliveryComplete': False, 'releaseQualified': False})
    index = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'planVersion': 'v0.118',
             'baselineSourceCommit': previous['sourceCommit'],
             'qualificationInputs': frozen, 'inputCount': len(frozen), 'changedInputs': CHANGED + ADDED,
             'receipts': [{'path': (local / name).relative_to(REPO).as_posix(),
                           'sha256': hashlib.sha256((local / name).read_bytes()).hexdigest()}
                          for name in ['receipt.json', 'r118-source-audit.json']],
             'localWindowsAllCoreQualified': True, 'sourcePublicationPending': True,
             'nativeQualificationPending': True, 'globalQuotaEnforced': False,
             'automaticGcImplemented': False, 'deliveryComplete': False, 'releaseQualified': False}
    write(REPO / 'docs/ci-verification-20261107-r118.json', index)
    for version, prefix in [(116, 'upload-scan'), (117, 'sqlite-journal')]:
        path = REPO / ('docs/ci-verification-20261107-r' + str(version) + '.json')
        old = json.loads(path.read_bytes())
        terminal = BASE / (prefix + '-r' + str(version) + '-native-terminal/receipt.json')
        if terminal.exists():
            result = json.loads(terminal.read_bytes())
            old['nativeRun'] = result['run']
            old['fullNativeProtocolQualified'] = result['allFourNativeProtocolJobsVerified']
            receipt = terminal.relative_to(REPO).as_posix()
            if not any(row['path'] == receipt for row in old['receipts']):
                old['receipts'].append({'path': receipt})
        if version == 117:
            core = json.loads((BASE / 'sqlite-journal-r117-native-core/receipt.json').read_bytes())
            assert core['allFourNativeCoreJobsVerified']
            old['allNativeCoreQualified'] = True
        for row in old['receipts']:
            row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
        old['observedUtc'] = datetime.now(timezone.utc).isoformat()
        write(path, old)
        shutil.copyfile(path, ROOT / path.relative_to(REPO))
    section = """## R118 状态根直接占用计量（2026-11-07）

- [x] 新增三平台共用client storage和serve storage命令，分别查询transfers/service已存在状态根；独占维护、常量空间枚举、逐项取消、64位溢出拒绝及七类固定JSON/人类输出。[用法与边界](docs/状态占用查询.md)。
- [x] SQLite主库及三种旁路、未知普通文件均计量；原生不跟随链接，不递归子目录、不打开FIFO正文或SQLite连接；硬链接按名称保守计量并报告。计量不授予删除资格，也不冒充任意外部写入下的原子快照。
- [x] MSVC/UCRT各28完整CTest、27份Qt XML通过；计量各10通过/1本机符号链接权限跳过，实际CLI双入口、热日志原字节保持、超4GiB稀疏逻辑探针及4096项重复查询通过。首轮测试夹具QJsonValueRef悬空引用造成比较失败/崩溃，已改保存实际值，原件保留。[本机证据](docs/validation/2026-11-07/state-storage-r118-local/receipt.json)。
- [x] 221份维护文件零TODO/占位标记、C++14、全量C++格式及原文件编码/BOM/换行通过；247份资格输入已冻结。[索引](docs/ci-verification-20261107-r118.json)。
- [x] R117四原生各27核心已全部收验；R116原生终态failure（Windows热journal原失败保留），三个POSIX完整协议各47项通过。
- [ ] R118精确公开提交、四原生完整回归、新双Mac编译和含依赖预览继续，当前已验Mac预览仍为R117。
- [ ] 全根总配额/活动与历史分类/自动GC尚未完成；其他状态根及传输正文预算、有效幂等保留、完整R6 GUI、物理LAN/3×3、当前版本各平台24h、最低干净系统、依赖源码重建与正式分发继续。整体与正式发布保持false。

"""
    def plan(text):
        assert '## R118 ' not in text
        text = text.replace('文档版本：v0.117', '文档版本：v0.118', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R118已实现状态根直接逻辑占用查询，双Windows各28核心/27份XML通过，247份输入冻结；准备公开和新原生/Mac构建。R117四原生各27核心已验，当前已验Mac包为R117。总配额/自动GC及完整项目交付继续。', text, count=1, flags=re.M)
        text = text.replace('v0.117 / Windows原生回滚日志恢复', 'v0.118 / 状态根直接占用计量', 1)
        text = text.replace('ubuntu-22.04、macos-15、macos-15-intel各27核心已验', 'Windows、Ubuntu、Apple Silicon、Intel四原生各27核心已验')
        text = re.sub(r'^- \[ \] \[四平台原生CI\]\(https://github.com/29583855/dukto-next/actions/runs/42375666807\).*$', '- [x] R116四平台原生CI终态failure：Windows热journal核心失败原件保留，Ubuntu/双Mac完整job及协议各47项通过；R117专门修正按精确提交另验。', text, count=1, flags=re.M)
        return text.replace('## R117 Windows 原生 SQLite 日志恢复', section + '## R117 Windows 原生 SQLite 日志恢复', 1)
    edit('开发计划与进度.md', plan)
    edit('docs/执行进度.md', lambda text: text.replace('## R117 Windows原生回滚日志恢复',
         '## R118 状态根直接占用计量（2026-11-07）\n\n双Windows各28完整CTest及27份Qt原件通过，计量专项各10通过/1权限跳过，首轮测试夹具引用错误原件保留；固定七类、热journal不恢复、未知普通文件及硬链接保守计量、链接/特殊项排除和两类真实CLI已验。221份维护源码审计通过。新原生构建继续，总配额和自动GC仍待完成。[用法](状态占用查询.md)、[证据](ci-verification-20261107-r118.json)。R117四原生各27核心已验；R116终态failure，三个POSIX完整协议各47项通过。\n\n## R117 Windows原生回滚日志恢复', 1).replace('ubuntu-22.04、macos-15、macos-15-intel各27核心已验', '四原生各27核心已验'))
    edit('docs/过期任务临时文件清理.md', lambda text: text.replace(chr(96) + '\text\n', chr(96) * 3 + 'text\n', 1).replace('\n' + chr(96) + '\n\n完整语义', '\n' + chr(96) * 3 + '\n\n完整语义', 1) + '\n\nR118另提供[状态占用查询](状态占用查询.md)，观察直接普通文件逻辑长度，不触发SQLite恢复、不自动删除数据；总配额和自动GC继续实施。\n')
    edit('docs/状态目录维护保护.md', lambda text: text + '\n\nR118的[状态占用查询](状态占用查询.md)也要求独占维护。它逐项读取原生属性，覆盖直接普通文件及SQLite旁路，不打开数据库或删除数据；目录外部原地写入不受本锁保证。\n')
    edit('README.md', lambda text: text.replace('\n\nR117精确', '\n\nR118新增客户端/服务器状态占用查询，双Windows各28完整CTest及27份Qt XML通过；保留热SQLite日志、链接及特殊项边界。新原生构建继续，总配额/自动GC和整体交付仍按计划推进。[用法](docs/状态占用查询.md)、[证据](docs/ci-verification-20261107-r118.json)。\n\nR117精确', 1))
    shutil.copyfile(ROOT / 'docs/状态占用查询.md', REPO / 'docs/状态占用查询.md')
    shutil.copyfile(REPO / 'docs/ci-verification-20261107-r118.json', ROOT / 'docs/ci-verification-20261107-r118.json')
    for name in ['state-storage-r118-local', 'sqlite-journal-r117-native-core',
                 'sqlite-journal-r117-native-terminal', 'upload-scan-r116-native-terminal']:
        shutil.copytree(BASE / name, ROOT / 'docs/validation/2026-11-07' / name, dirs_exist_ok=True)
    print(json.dumps({'inputCount': len(frozen), 'changedInputs': CHANGED + ADDED,
                      'completeWindowsCorePassedEach': 28, 'publicationPending': True}), flush=True)


if __name__ == '__main__':
    main()
