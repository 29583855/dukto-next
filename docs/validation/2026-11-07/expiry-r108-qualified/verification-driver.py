"""日期：2026-11-07；独立核对双Windows过期清理、原协议、源码及格式，不以子项冒充交付。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；文件证据记录实际原件摘要，不引用可变日志或凭据。
def proof(root, path):
    raw = path.read_bytes()
    return {'path': path.relative_to(root).as_posix(), 'bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest()}


# 日期：2026-11-07；QtTest把日志注释计入errors；仅接受原64条终态夹具QINFO和一条已知头像Qt警告。
def verify_xml(path):
    suite = ET.fromstring(path.read_bytes(), parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
    assert suite.get('failures') == '0' and not suite.findall('.//failure') and not suite.findall('.//error')
    assert all(case.get('result') == 'pass' for case in suite.findall('testcase'))
    comments = [item.text for item in suite.iter() if item.tag is ET.Comment]
    assert int(suite.get('errors')) == len(comments)
    if path.name == 'file-exchange-tests.xml':
        assert len(comments) == 64 and all('type="qinfo"' in text and 'message="terminal fixture ' in text for text in comments)
    elif path.name == 'avatars-tests.xml':
        assert len(comments) <= 1 and all(text.strip() == 'message="QNetworkReplyImplPrivate::error: Internal problem, this method must only be called once." type="qwarn"' for text in comments)
    else:
        assert not comments, (path, comments)


# 日期：2026-11-07；验证真实退出码、全部核心原件、新18行测试及原传输边界后才授予本轮Windows资格。
def main():
    root = Path.cwd()
    source = root / 'docs/validation/2026-11-07/expiry-r108-windows'
    output = root / 'docs/validation/2026-11-07/expiry-r108-qualified'
    output.mkdir(exist_ok=True)
    assert not (output / 'receipt.json').exists()
    result = json.loads((source / 'driver-result.json').read_text('utf-8'))
    assert len(result['cases']) == 2
    inputs = json.loads((source / 'build-inputs.json').read_text('utf-8'))
    assert len(inputs) == 216
    revised = []
    for row in inputs:
        actual = hashlib.sha256((root / row['path']).read_bytes()).hexdigest()
        if actual != row['sha256']:
            revised.append({'path': row['path'], 'previousSha256': row['sha256'], 'sha256': actual})
            row['sha256'] = actual
    assert [row['path'] for row in revised] == ['tests/task_store_integration.py']
    assert not result['buildInputsUnchanged'] and not result['passed']
    executed = (source / 'validation-driver.py').read_text('utf-8')
    assert "('task-items', 'task_items_integration'" in executed and "'task_store_integration'" not in executed
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == '8f5d6050f85415e2eed5ffb651dbe1f97a3af247'
    changed = []
    for row in inputs:
        name = row['path']
        raw = (root / name).read_bytes()
        previous = subprocess.run(['git', 'show', 'HEAD:' + name], cwd=checkout, capture_output=True)
        if previous.returncode or previous.stdout != raw:
            changed.append(name)
            raw.decode('utf-8')
            assert not raw.startswith(b'\xef\xbb\xbf') and b'\r\n' not in raw
            if previous.returncode == 0:
                assert not previous.stdout.startswith(b'\xef\xbb\xbf') and b'\r\n' not in previous.stdout
    assert set(changed) == {'CMakeLists.txt', 'src/core/taskstore.h', 'src/core/taskstore.cpp',
                            'src/core/expiredtaskcleanup.h', 'src/core/expiredtaskcleanup.cpp',
                            'src/cli/servicecommands.cpp', 'tests/task_store_tests.cpp',
                            'tests/expired_task_cleanup_tests.cpp', 'tests/task_store_integration.py'}
    windows = []
    for row in result['cases']:
        assert row['passed'] and row['binaryUnchanged'] and len(row['cases']) == 5
        assert {item['name'] for item in row['cases']} == {'build', 'ctest', 'secure-channel', 'task-items', 'transfer16'}
        assert all(item['exitCode'] == 0 for item in row['cases'])
        folder = source / row['toolchain']
        ctest = (folder / 'ctest.log').read_text('utf-8')
        assert ('100% tests passed, 0 tests failed out of 24' in ctest or
                '100% tests passed out of 24' in ctest)
        assert len(re.findall(r'\d+/24 Test\s+#\d+: [^\n]+Passed', ctest)) == 24
        xmls = sorted((folder / 'QtTest').glob('*.xml'))
        assert len(xmls) == 23
        for path in xmls:
            verify_xml(path)
        detail = (folder / 'QtTest/expired-task-cleanup-tests.log').read_text('utf-8')
        assert '18 passed, 0 failed, 0 skipped' in detail
        for name in ('retentionAndIdempotency', 'crashAfterRemoval', 'replacedTemporary',
                     'unresolvedCommit', 'boundedPages', 'ownership', 'terminalRetention(cancelled)',
                     'terminalRetention(failed)', 'replacementAfterConfirmation', 'replacedRoot',
                     'commandLine', 'versionTwoMigration'):
            assert 'PASS   : ExpiredTaskCleanupTests::' + name + '()' in detail if '(' not in name else 'PASS   : ExpiredTaskCleanupTests::' + name in detail
        tls = json.loads((folder / 'secure-channel.json').read_text('utf-8'))
        assert tls['passed'] and len(tls['cases']) == 31
        items = json.loads((folder / 'task-items.json').read_text('utf-8'))
        assert items['passed'] and len(items['cases']) == 4
        transfer = json.loads((folder / 'transfer16.json').read_text('utf-8'))
        assert transfer['passed']
        process_folder = root / 'docs/validation/2026-11-07/expiry-r108-processes'
        process_receipt = json.loads((process_folder / (row['toolchain'] + '-v3.json')).read_text('utf-8'))
        process_exit = json.loads((process_folder / (row['toolchain'] + '-v3-exit.json')).read_text('utf-8'))
        assert process_exit['exitCode'] == 0 and process_exit['binaryUnchanged']
        assert process_receipt['passed'] and process_receipt['migratedSchemaVersion'] == 3
        assert process_receipt['schemaMigrationProcesses'] == process_receipt['schemaTwoMigrationProcesses'] == 8
        assert process_receipt['oldFifteenColumnsUnchanged'] and process_receipt['oldSixteenColumnsUnchanged']
        assert process_receipt['scriptSha256'] == revised[0]['sha256']
        binary = root / ('build/windows-ucrt' if row['toolchain'] == 'ucrt' else 'build/windows/Release')
        for name, digest in row['binarySha256'].items():
            assert hashlib.sha256((binary / name).read_bytes()).hexdigest() == digest
        assert hashlib.sha256((binary / 'task-store-probe.exe').read_bytes()).hexdigest() == process_exit['binarySha256']
        windows.append({'toolchain': row['toolchain'], 'coreTargets': 24, 'qtXmlReports': 23,
                        'cleanupQtRowsIncludingInitAndCleanup': 18, 'tlsCases': 31,
                        'fullTaskItemsCases': 4, 'transfer16Passed': True,
                        'binarySha256': row['binarySha256'], 'evidence': proof(root, folder / 'exit-codes.json')})
    audit_path = root / '.cache/expiry-r108-source-audit-final.json'
    audit = json.loads(audit_path.read_text('utf-8'))
    assert len(audit['files']) == 210 and not audit['findings']
    assert audit['sourceMarkersPassed'] and audit['cxx14Configuration'] and audit['formatting']['passed']
    shutil.copyfile(audit_path, output / 'source-audit.json')
    shutil.copyfile(__file__, output / 'verification-driver.py')
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'passed': True,
             'buildInputs': inputs, 'changedBuildInputs': changed, 'windows': windows,
             'sourceAudit': proof(root, output / 'source-audit.json'),
             'validationFixtureRevision': revised,
             'originalDriverInputDriftRetained': True,
             'driftRestrictedToSeparatelyRerunUnusedMigrationFixture': True,
             'productionCoreAndAllExecutedProtocolInputsUnchanged': True,
             'newAndChangedFunctionCommentsChineseAndDated': True,
             'originalUtf8NoBomLfPreserved': True, 'cxxStandard': 14,
             'maintenanceScope': 'expired inactive server upload temporary file bodies; all metadata and request keys retained',
             'nativeCIQualifiedForThisSource': False, 'independentUbuntuPending': True,
             'globalDiskBudgetImplemented': False, 'clientDownloadCleanupImplemented': False,
             'throughputImprovementProven': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'passed': True, 'windowsToolchains': 2, 'coreTargetsEach': 24,
                      'cleanupQtRowsEach': 18, 'buildInputsVerified': len(inputs),
                      'sourceFilesAudited': 210, 'changedBuildInputs': changed, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
