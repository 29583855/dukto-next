"""日期：2026-11-07；原传输核心上验证取消三场景及双向恢复，两Windows工具链完整23项回归。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；输入前后摘要必须一致，首轮错误断言报告保留，任何未知失败都不转授资格。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/cancel-r101-corrected-windows'
    output.mkdir(exist_ok=False)
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    original = json.loads((root / 'docs/ci-verification-20261107-r100.json').read_text('utf-8'))['buildInputs']
    inputs = [{'path': row['path'], 'sha256': hashlib.sha256((root / row['path']).read_bytes()).hexdigest()}
              for row in original]
    changed = {a['path'] for a, b in zip(inputs, original) if a != b}
    assert changed == {'ui/Main.qml', 'tests/ui_tests.cpp'}, changed
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
            xml = ET.parse(target / 'QtTest/ui-tests.xml').getroot()
            function, = [item for item in xml.findall('TestFunction')
                         if item.attrib['name'] == 'cancelThenTransferAgainThroughQml']
            incidents = function.findall('Incident')
            if code == 0:
                assert len(incidents) == 3 and all(item.attrib['type'] == 'pass' for item in incidents)
                verified_rows = sorted(item.findtext('DataTag') for item in incidents)
                assert verified_rows == ['receive-header', 'receive-partial', 'send']
        value = {'toolchain': label, 'buildExitCode': build.returncode, 'ctestExitCode': code,
                 'coreTestCount': 23, 'verifiedQmlCancellationRows': verified_rows,
                 'passed': build.returncode == 0 and code == 0 and len(verified_rows) == 3}
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
