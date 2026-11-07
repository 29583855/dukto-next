"""日期：2026-11-07；逐项核验最终R116源码与本机/独立Ubuntu原件，再更新计划和发布副本。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = REPO / 'docs/validation/2026-11-07'
LOCAL = BASE / 'upload-scan-r116-local'
LINUX = BASE / 'upload-scan-r116-ubuntu'


# 日期：2026-11-07；不修改原件编码与换行，文本变化保持原UTF-8的BOM及行结束方式。
def edit(path, callback):
    raw = path.read_bytes()
    bom = b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b''
    newline = '\r\n' if b'\r\n' in raw else '\n'
    value = callback(raw[len(bom):].decode('utf-8').replace('\r\n', '\n'))
    path.write_bytes(bom + value.replace('\n', newline).encode('utf-8'))


# 日期：2026-11-07；JSON证据保持明确层级，单项通过不能变成完整交付。
def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


# 日期：2026-11-07；同时核验实际方法、逐数据行和唯一权限跳过，拒绝额外失败或跳过。
def verify_scan(xml, log, windows):
    tree = ET.parse(xml).getroot()
    assert tree.get('failures') == '0' and not tree.findall('.//failure')
    cases = tree.findall('testcase')
    expected = {'initTestCase', 'retainedPreviewAndCleanup', 'interruptedCleanup', 'damagedEvidence',
                'publishedAndLocks', 'unsafeObjects', 'cancelledCleanup', 'corruptDatabase',
                'exhaustedCacheCredit', 'realCli', 'cleanupTestCase'}
    assert {case.get('name') for case in cases} == expected and len(cases) == 11
    text = log.read_text('utf-8-sig')
    assert 'Totals: ' + ('24 passed, 0 failed, 1 skipped' if windows else '25 passed, 0 failed, 0 skipped') in text
    skipped = [line for line in text.splitlines() if line.startswith('SKIP')]
    assert len(skipped) == (1 if windows else 0)
    for case in cases:
        assert case.get('result') == 'pass' or (windows and case.get('name') == 'unsafeObjects' and case.get('result') == 'skip')
    assert 'PASS   : UploadScanCleanupTests::exhaustedCacheCredit()' in text
    assert 'PASS   : UploadScanCleanupTests::realCli()' in text
    if not windows:
        assert 'PASS   : UploadScanCleanupTests::unsafeObjects(symbolic-link)' in text


# 日期：2026-11-07；原失败及早期通过分别留存，当前结果只绑定本次冻结的实际候选输入。
def main():
    audit = json.loads((ROOT / '.cache/r116-credit-fixed-source-audit.json').read_bytes())
    assert len(audit['files']) == 219 and not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
    old = LOCAL / 'before-cache-credit-fix'
    if not old.exists():
        old.mkdir()
        for name in ['msvc', 'ucrt']:
            shutil.copytree(LOCAL / name, old / name)
        shutil.copyfile(LOCAL / 'receipt.json', old / 'receipt.json')
        shutil.copyfile(LOCAL / 'source-audit.json', old / 'source-audit.json')
    rows = []
    for build, tag in [('windows', 'msvc'), ('windows-ucrt', 'ucrt')]:
        folder = LOCAL / tag
        for test in ['upload-scan-cleanup-tests', 'strong-manifest-tests', 'server-panel-tests']:
            for suffix in ['log', 'xml']:
                shutil.copyfile(ROOT / 'build' / build / 'Testing/QtTest' / (test + '.' + suffix), folder / (test + '.' + suffix))
            tree = ET.parse(folder / (test + '.xml')).getroot()
            assert tree.get('failures') == '0' and not tree.findall('.//failure')
            if test != 'upload-scan-cleanup-tests':
                assert all(case.get('result') == 'pass' for case in tree.findall('testcase'))
        verify_scan(folder / 'upload-scan-cleanup-tests.xml', folder / 'upload-scan-cleanup-tests.log', True)
        for path in (ROOT / '.cache').glob('r116-' + tag + '-credit-*.log'):
            shutil.copyfile(path, folder / path.name)
        assert '100% tests passed out of 3' in (ROOT / ('.cache/r116-' + tag + '-credit-fixed-ctest.log')).read_text()
        program = ROOT / 'build' / build / ('Release' if tag == 'msvc' else '') / 'upload-scan-cleanup-tests.exe'
        rows.append({'toolchain': tag, 'completeRelatedCtestsPassed': 3, 'scanRowsPassed': 24,
                     'scanRowsSkipped': 1, 'scanJUnitMethods': 11,
                     'skipReason': 'Windows account cannot create a native symbolic link',
                     'binarySha256': hashlib.sha256(program.read_bytes()).hexdigest()})
    failed = LOCAL / 'failed-cache-credit-before-fix'
    failed.mkdir(exist_ok=True)
    for path in (ROOT / '.cache').glob('r116-credit-exhaustion-failed.*'):
        shutil.copyfile(path, failed / path.name)
    failure = (failed / 'r116-credit-exhaustion-failed.log').read_text()
    assert 'Actual   (QSqlDatabase::connectionNames()) size: 1' in failure
    shutil.copyfile(ROOT / '.cache/r116-credit-fixed-source-audit.json', LOCAL / 'source-audit.json')
    ubuntu = ROOT / '.cache/upload-scan-r116-ubuntu'
    verify_scan(ubuntu / 'qt-credit-fixed.xml', ubuntu / 'qt-credit-fixed.log', False)
    assert (ubuntu / 'binaries-credit-before.sha256').read_bytes() == (ubuntu / 'binaries-credit-after.sha256').read_bytes()
    assert (ubuntu / 'test-credit-exit-code.txt').read_text().strip() == '0'
    final_inputs = json.loads((ubuntu / 'final-candidate-inputs.json').read_bytes())
    for name, digest in final_inputs.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
    objects = json.loads((ubuntu / 'frozen-objects-verified.json').read_bytes())
    missing = json.loads((ubuntu / 'missing-original-objects.json').read_bytes())
    assert len(objects) == 32 and len(missing) == 10
    LINUX.mkdir(exist_ok=True)
    for path in ubuntu.iterdir():
        if path.is_file() and path.suffix in ('.json', '.xml', '.log', '.txt', '.sha256', '.sh'):
            shutil.copyfile(path, LINUX / path.name)
    for name in ['validate-r116-ubuntu.py', 'resume-r116-ubuntu.py', 'repair-r116-ubuntu-harness.py', 'verify-r116-ubuntu-credit.py']:
        shutil.copyfile(ROOT / '.cache' / name, LINUX / name)
    write(LINUX / 'receipt.json', {'observedUtc': datetime.now(timezone.utc).isoformat(),
          'baselineObjectSourceCommit': '400e0621745dc250b3390ad01a5e9f47dfc924a4',
          'reusedCoreObjectsWithExactSourceAndObjectHashes': 32, 'missingCoreObjectsCompiledFromExactBaseline': missing,
          'candidateCoreSourcesIndependentlyCompiled': ['src/core/uploadmanifest.cpp', 'src/core/sourcefile.cpp', 'src/core/privatestore.cpp'],
          'cliAndTestsIndependentlyCompiled': True, 'candidateFinalInputs': final_inputs,
          'scanRowsPassed': 25, 'scanRowsSkipped': 0, 'scanJUnitMethods': 11,
          'realNativeSymbolicLinkPassed': True, 'binaryBeforeAfterUnchanged': True,
          'firstHarnessMissingObjectsAndQtMocFailuresRetained': True,
          'fullProjectFreshBuildQualified': False, 'passed': True, 'deliveryComplete': False, 'releaseQualified': False})
    index_path = REPO / 'docs/ci-verification-20261107-r116.json'
    index = json.loads(index_path.read_bytes())
    for row in index['qualificationInputs']:
        name = row['path']
        raw = (ROOT / name).read_bytes()
        if name in index['changedInputs']:
            shutil.copyfile(ROOT / name, REPO / name)
        assert raw == (REPO / name).read_bytes(), name
        row.update(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())
    assert len(index['qualificationInputs']) == 245
    write(LOCAL / 'receipt.json', {'observedUtc': datetime.now(timezone.utc).isoformat(),
          'baselineSourceCommit': index['baselineSourceCommit'], 'records': rows,
          'qualificationInputs': index['qualificationInputs'], 'inputCount': 245, 'changedInputs': index['changedInputs'],
          'originalJsonTemporaryReferenceFailureRetained': True,
          'cacheCreditExhaustionConnectionLeakReproducedAndFixed': True,
          'failureFix': 'Reserve SQLite cache before registering Qt database connection; three repeated exhaustion failures and retry preserve evidence and resources',
          'unknownPreOwnershipFilesStillPreserved': True, 'passed': True, 'deliveryComplete': False, 'releaseQualified': False})
    shutil.copyfile(Path(__file__), LOCAL / 'final-evidence-driver.py')
    index.update(observedUtc=datetime.now(timezone.utc).isoformat(), independentUbuntuScanQualified=True)
    index['receipts'] = [{'path': path.relative_to(REPO).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                         for path in [LOCAL / 'receipt.json', LOCAL / 'source-audit.json', LINUX / 'receipt.json']]
    write(index_path, index)
    for version in [113, 114]:
        path = REPO / ('docs/ci-verification-20261107-r' + str(version) + '.json')
        value = json.loads(path.read_bytes())
        suffix = 'skip-reconcile-r113-native-terminal' if version == 113 else 'private-read-r114-native-terminal'
        terminal = json.loads((BASE / suffix / 'receipt.json').read_bytes())
        value['nativeRun'] = terminal['run']
        if version == 113:
            assert terminal['allFourNativeProtocolJobsVerified']
            value['nativeProtocolQualified'] = True
            value['nativeProtocolQualificationPending'] = False
        for row in value['receipts']:
            row['sha256'] = hashlib.sha256((REPO / row['path']).read_bytes()).hexdigest()
        value['observedUtc'] = datetime.now(timezone.utc).isoformat()
        write(path, value)
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R116未发布源扫描清理已完成双Windows与独立Ubuntu验证，缓存额度耗尽连接残留已复现并修复，准备四平台原生CI及新Mac包。R113四平台完整协议已验；R114 Intel面板原失败保留，R115双Mac专项通过。现有含依赖Mac预览仍为R114。整体与正式发布未完成。', text, count=1, flags=re.M)
        text = text.replace('v0.115 / 原生编译与界面读取时序', 'v0.116 / 源扫描清理与资源失败恢复', 1)
        text = text.replace('R113三平台完整协议各47/47，Windows仍在执行。', 'R113四平台完整协议已验，Windows51/51、其他各47/47。R116扫描清理双Windows各24条/1权限跳过、独立Ubuntu25条全通过。', 1)
        text = text.replace('R113三平台完整协议各47/47 |', 'R113四平台完整协议已验；R116源扫描清理CLI与失败恢复已验 |', 1)
        text = text.replace('R113 Ubuntu/Apple Silicon/Intel完整job各47/47；', 'R113 Windows51/51、Ubuntu/Apple Silicon/Intel完整job各47/47；', 1)
        start = text.index('## R116 未发布源扫描清理')
        end = text.index('## R115 ', start)
        section = text[start:end].replace('各23通过/1权限跳过', '各24通过/1权限跳过')
        section = section.replace('原完整强清单和服务器面板CTest均通过。', '相关三个完整CTest在本次最终源码下均通过。缓存额度耗尽的Qt连接残留已真实复现并调整申请顺序，三次连续失败、原库/热日志不变和归还后重试通过。')
        section = section.replace('- [ ] 独立Ubuntu隔离构建及新源码四平台原生编译/测试待按实际终态收验，Windows原生符号链接行因账户权限跳过，不借用其他平台资格。', '- [x] 独立Ubuntu隔离验证25条/11方法全通过，包括原生符号链接保护；32个精确R113源/对象复用、10个缺失对象另编、3个候选核心与CLI/测试独立编译，初轮验证工程缺对象/Qt元对象链接失败原件保留，不称完整全新构建。[Ubuntu回执](docs/validation/2026-11-07/upload-scan-r116-ubuntu/receipt.json)。\n- [ ] 新源码四平台原生编译/测试与新双Mac含依赖预览待按实际终态收验。Windows本机符号链接权限跳过仍保留。')
        text = text[:start] + section + text[end:]
        return text
    edit(ROOT / '开发计划与进度.md', plan)
    edit(ROOT / 'docs/执行进度.md', lambda text: text.replace('双Windows各23条通过/1符号链接权限跳过，完整强清单和服务器面板通过，原失败保留。独立Ubuntu及四平台CI按实际原件另验。', '双Windows各24条通过/1符号链接权限跳过，三个相关完整CTest均通过；缓存额度耗尽连接残留已复现修复，原失败保留。独立Ubuntu25条全通过，四平台原生CI及新Mac包按实际原件另验。', 1))
    edit(ROOT / 'docs/decisions/0029-未发布上传源扫描清理.md', lambda text: text.replace('状态：实现及本机验证中；按各平台实际原件单独授予资格。', '状态：实现、双Windows专项及独立Ubuntu隔离验证通过；四平台完整CI和新包另验。', 1).replace('缓存1MiB纳入共享授信', '缓存1MiB纳入共享授信，先申请额度再注册Qt连接，额度失败不遗留连接', 1))
    for name in ['开发计划与进度.md', 'docs/执行进度.md', 'docs/decisions/0029-未发布上传源扫描清理.md']:
        shutil.copyfile(ROOT / name, REPO / name)
    for name in ['ci-verification-20261107-r113.json', 'ci-verification-20261107-r114.json', 'ci-verification-20261107-r116.json']:
        shutil.copyfile(REPO / 'docs' / name, ROOT / 'docs' / name)
    for folder in [LOCAL, LINUX, BASE / 'skip-reconcile-r113-native-terminal', BASE / 'private-read-r114-native-terminal']:
        shutil.copytree(folder, ROOT / folder.relative_to(REPO), dirs_exist_ok=True)
    print(json.dumps({'sourceInputs': 245, 'windowsScanPassRowsEach': 24, 'windowsSkipRowsEach': 1,
                      'ubuntuScanPassRows': 25, 'allThreeRelatedCtestsPassedBothWindows': True,
                      'publicationPending': True, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
