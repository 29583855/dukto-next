"""日期：2026-11-08；执行真实状态观察专项，保留精确源码和原始报告，不代替完整核心/协议。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-08；摘要流式读取，证据计算不因文件增大而建立整份正文副本。
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


# 日期：2026-11-08；仅允许已披露的Windows符号链接权限跳过，新增身份/分配/数据库锁方法必须通过。
def verify_xml(path):
    tree = ET.fromstring(path.read_bytes(), ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    assert tree.tag == 'testsuite' and tree.get('failures') == '0'
    assert not tree.findall('.//failure') and not tree.findall('.//error')
    expected = {'initTestCase', 'logicalLengthsAndCategories', 'hotJournalIsObservedWithoutRecovery',
                'hardLinksCountPerName', 'nativeIdentityMatchesSqliteAndAliases', 'visitorFailureIsReusable',
                'inventoryPreservesSqliteWriteLock', 'nestedDataIsExcluded', 'nativeSymbolicLinkIsExcluded',
                'maintenanceCancellationAndMutation', 'manyEntriesKeepReportBounded', 'realCli', 'cleanupTestCase'}
    cases = tree.findall('testcase')
    assert len(cases) == len(expected) and {case.get('name') for case in cases} == expected
    skipped = 0
    for case in cases:
        comments = [node.text for node in case.iter() if node.tag is ET.Comment]
        if comments:
            assert os.name == 'nt' and case.get('name') == 'nativeSymbolicLinkIsExcluded'
            assert comments == [' message="Windows account cannot create a native symbolic link" type="skip" ']
            assert case.get('result') is None
            skipped += 1
        else:
            assert case.get('result') == 'pass', case.attrib
    assert int(tree.get('errors', '0')) == skipped
    text = path.with_suffix('.log').read_text('utf-8-sig')
    assert re.search(r'Totals: ' + str(14 - skipped) + r' passed, 0 failed, ' + str(skipped) + r' skipped', text)
    return {'testMethods': len(cases), 'rowsPassed': 14 - skipped, 'permissionRowsSkipped': skipped,
            'newNativeIdentityAllocationAndLockMethodsPassed': 3}


# 日期：2026-11-08；原生CLI和观察程序前后保持摘要，全部参与源码前后不变才授予专项资格。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--configuration', default='Release')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    build = args.build.resolve()
    output = build / 'state-inventory-regression'
    output.mkdir(exist_ok=False)
    directory = build / args.configuration if os.name == 'nt' else build
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = [directory / (name + suffix) for name in ['dukto-cli', 'state-storage-tests']]
    inputs = [root / 'CMakeLists.txt']
    for folder in ['src', 'tests', 'scripts', 'third-party/sqlite-runtime', '.github/workflows']:
        inputs.extend(path for path in (root / folder).rglob('*')
                      if path.is_file() and '__pycache__' not in path.parts)
    before = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    sources = {path.relative_to(root).as_posix(): digest(path) for path in sorted(inputs)}
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    with (output / 'driver.log').open('wb') as log:
        result = subprocess.run(['ctest', '--test-dir', str(build), '-C', args.configuration,
                                 '-R', '^state-storage-tests$', '--output-on-failure',
                                 '--output-log', str(output / 'ctest.log')], stdout=log, stderr=subprocess.STDOUT)
    after = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    sources_after = {path.relative_to(root).as_posix(): digest(path) for path in sorted(inputs)}
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'system': platform.platform(), 'architecture': platform.machine(), 'ctestExitCode': result.returncode,
             'binaryBefore': before, 'binaryAfter': after, 'binaryUnchanged': before == after,
             'sourceInputs': sources, 'sourceInputsUnchanged': sources == sources_after,
             'completeCoreQualified': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False, 'passed': False}
    if result.returncode == 0:
        value.update(verify_xml(build / 'Testing/QtTest/state-storage-tests.xml'))
        value['passed'] = value['binaryUnchanged'] and value['sourceInputsUnchanged']
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value.get(key) for key in ['sourceCommit', 'architecture', 'ctestExitCode',
                                                    'rowsPassed', 'permissionRowsSkipped', 'passed']}), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
