"""日期：2026-11-07；原传输核心上验证取消三场景及双向恢复，两Windows工具链完整23项回归。"""
import hashlib
import json
import re
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；输入前后摘要必须一致，首轮错误断言报告保留，任何未知失败都不转授资格。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/cancel-r102-windows'
    output.mkdir(exist_ok=False)
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    original = json.loads((root / 'docs/ci-verification-20261107-r101.json').read_text('utf-8'))['buildInputs']
    inputs = [{'path': row['path'], 'sha256': hashlib.sha256((root / row['path']).read_bytes()).hexdigest()}
              for row in original]
    changed = {a['path'] for a, b in zip(inputs, original) if a != b}
    assert changed == {'tests/ui_tests.cpp'}, changed
    (output / 'build-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', 'utf-8')
    results = []
    for label, folder, cmake, ctest, extra in [
            ('ucrt', 'windows-ucrt', '.tools/msys64/ucrt64/bin/cmake.exe', '.tools/msys64/ucrt64/bin/ctest.exe', []),
            ('msvc', 'windows', '.tools/python/Scripts/cmake.exe', '.tools/python/Scripts/ctest.exe', ['-C', 'Release'])]:
        target = output / label
        target.mkdir()
        env = environment(label)
        with (target / 'build.log').open('xb') as log:
            build = subprocess.run([str(root / cmake), '--build', str(root / 'build' / folder),
                                    '--config', 'Release', '--parallel', '2'],
                                   env=env, stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        code = None
        navigation_code = None
        verified_rows = []
        if build.returncode == 0:
            command = [str(root / ctest), '--test-dir', str(root / 'build' / folder), *extra]
            description = json.loads(subprocess.check_output(command + ['--show-only=json-v1'], env=env))
            assert len(description['tests']) == 23
            with (target / 'ctest.log').open('xb') as log:
                process = subprocess.run(command + ['--output-on-failure'], env=env,
                                         stdout=log, stderr=subprocess.STDOUT, timeout=3600)
            code = process.returncode
            shutil.copytree(root / 'build' / folder / 'Testing/QtTest', target / 'QtTest')
            shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
            # 日期：2026-11-07；先持久记录真实子进程退出码，再独立核验JUnit聚合与文本中的逐数据行。
            (target / 'process-exit-codes.json').write_text(json.dumps({
                'buildExitCode': build.returncode, 'ctestExitCode': code}, indent=2) + '\n', 'utf-8')
            xml = ET.parse(target / 'QtTest/ui-tests.xml').getroot()
            if code == 0:
                assert xml.tag == 'testsuite' and xml.attrib['failures'] == xml.attrib['errors'] == '0'
                functions = [item for item in xml.findall('testcase')
                             if item.attrib['name'] == 'cancelThenTransferAgainThroughQml']
                assert len(functions) == 1 and functions[0].get('result') == 'pass'
                text = (target / 'QtTest/ui-tests.log').read_text('utf-8-sig')
                verified_rows = sorted(re.findall(r'^PASS   : UiTests::cancelThenTransferAgainThroughQml\(([^)]+)\)$', text, re.M))
                assert verified_rows == ['receive-header', 'receive-partial', 'send']
                assert not any(line.startswith(('FAIL!', 'XPASS', 'XFAIL', 'QFATAL', 'SKIP')) for line in text.splitlines())
                binary = root / 'build' / folder
                if label == 'msvc':
                    binary = binary / 'Release'
                with (target / 'native-navigation-driver.log').open('xb') as log:
                    navigation = subprocess.run(['python', '-X', 'utf8',
                        'tests/main_window_navigation_integration.py',
                        str(binary / 'ui-tests.exe'),
                        '--platform', 'windows', '--report', str(target / 'native-navigation.json')],
                        env=env, stdout=log, stderr=subprocess.STDOUT, timeout=300)
                navigation_code = navigation.returncode
                if navigation_code == 0:
                    report = json.loads((target / 'native-navigation.json').read_text('utf-8'))
                    assert report['passed'] and report['binaryUnchanged'] and len(report['cases']) == 3
                    for scene in report['cases']:
                        assert scene['verifiedCancellationRows'] == ['send', 'receive-header', 'receive-partial']
                    assert report['cases'][0]['nativeSelectorGuard']['passed']
        value = {'toolchain': label, 'buildExitCode': build.returncode, 'ctestExitCode': code,
                 'coreTestCount': 23, 'verifiedQmlCancellationRows': verified_rows,
                 'nativeNavigationExitCode': navigation_code,
                 'passed': build.returncode == 0 and code == 0 and len(verified_rows) == 3 and navigation_code == 0}
        results.append(value)
        (output / 'progress.json').write_text(json.dumps(results, indent=2) + '\n', 'utf-8')
        print(json.dumps(value), flush=True)
    unchanged = all(hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256'] for row in inputs)
    value = {'date': '2026-11-07', 'cases': results, 'buildInputsUnchanged': unchanged,
             'changedBuildInputs': sorted(changed), 'originalTransferCoreUnchanged': True,
             'initialIncorrectProgressAssertionFailureRetained': True,
             'cleanBuild': False, 'entireProtocolSuiteRun': False,
             'passed': unchanged and all(row['passed'] for row in results),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
