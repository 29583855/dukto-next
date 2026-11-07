"""日期：2026-11-08；执行固定账本原生专项，按真实进程、恢复原件及精确源码分别授予底层资格。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-08；流式核对身份，不随程序或源文件长度累积内容。
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


# 日期：2026-11-08；所有方法/数据行必须通过，精确限定六条子进程行尾信息，不接受跳过和未知警告。
def verify_xml(path, windows):
    tree = ET.fromstring(path.read_bytes())
    expected = {'initTestCase', 'fixedFileAndPrivateBoundary', 'categoriesAndLargeAmounts',
                'processesCompeteForLastCredit', 'processesCompeteForSameObject',
                'exitRetainsCreditAndMaintenanceReconciles', 'revisionsIdempotenceAndOverdraw',
                'nativeLockTimeoutAndCancellation', 'threadsShareOneInstance', 'writeAheadRecovery',
                'completedTransactionReplay', 'corruptionAndDomainBinding', 'staleJournalIsRejected',
                'tornIntentIsRejected', 'invalidAdmissionLeavesLedgerUnchanged', 'fixedSlotExhaustion',
                'hardLinkIsRejected', 'repeatedUseReturnsResources', 'cleanupTestCase'}
    methods = tree.findall('TestFunction')
    assert tree.tag == 'TestCase' and len(methods) == len(expected)
    assert {method.get('name') for method in methods} == expected
    readiness = {'processesCompeteForLastCredit': 2, 'processesCompeteForSameObject': 2,
                 'exitRetainsCreditAndMaintenanceReconciles': 1, 'nativeLockTimeoutAndCancellation': 1}
    rows = 0
    messages = 0
    for method in methods:
        name = method.get('name')
        incidents = method.findall('Incident')
        assert len(incidents) == (5 if name == 'writeAheadRecovery' else 1), name
        assert all(node.get('type') == 'pass' for node in incidents), name
        if name == 'writeAheadRecovery':
            assert [node.findtext('DataTag') for node in incidents] == ['0', '1', '2', '3', '4']
        notes = method.findall('Message')
        assert len(notes) == readiness.get(name, 0), name
        for note in notes:
            assert note.get('type') == 'qinfo', name
            assert note.findtext('Description') == 'Child readiness bytes: ' + ('72656164790d0a' if windows else '72656164790a')
        rows += len(incidents)
        messages += len(notes)
    assert rows == 23 and messages == 6
    return {'methodsPassed': len(methods), 'rowsPassed': rows, 'exactReadinessMessages': messages,
            'skipped': 0, 'warnings': 0, 'ledgerFixedBytes': 1056768, 'recordSlots': 4096}


# 日期：2026-11-08；冻结全部维护输入与CLI/专项程序，先保留退出及原件，再独立核对真实测试结果。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--configuration', default='Release')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    build = args.build.resolve()
    output = build / 'state-budget-regression'
    output.mkdir(exist_ok=False)
    directory = build / args.configuration if os.name == 'nt' else build
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = [directory / (name + suffix) for name in ['dukto-cli', 'state-budget-tests']]

    # 日期：2026-11-08；每次重新枚举输入，额外/缺失文件也构成执行期间身份变化。
    def sources():
        paths = [root / 'CMakeLists.txt']
        for folder in ['src', 'tests', 'scripts', 'third-party/sqlite-runtime', '.github/workflows']:
            paths.extend(path for path in (root / folder).rglob('*')
                         if path.is_file() and '__pycache__' not in path.parts)
        return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}

    before = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    inputs = sources()
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    command = [str(binaries[1]), '-o', str(output / 'state-budget-tests.log') + ',txt',
               '-o', str(output / 'state-budget-tests.xml') + ',xml',
               '-o', str(output / 'state-budget-tests-junit.xml') + ',junitxml']
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    after = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'system': platform.platform(), 'architecture': platform.machine(), 'testExitCode': result.returncode,
             'binaryBefore': before, 'binaryAfter': after, 'binaryUnchanged': before == after,
             'sourceInputs': inputs, 'sourceInputsUnchanged': inputs == sources(), 'passed': False,
             'completeCoreQualified': False, 'runtimeOwnershipRegistryImplemented': False,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        try:
            value.update(verify_xml(output / 'state-budget-tests.xml', os.name == 'nt'))
            value['passed'] = value['binaryUnchanged'] and value['sourceInputsUnchanged']
        except (AssertionError, ET.ParseError) as error:
            value['verificationError'] = str(error)
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value.get(key) for key in ['sourceCommit', 'architecture', 'testExitCode',
                                                    'methodsPassed', 'rowsPassed', 'passed']}), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
