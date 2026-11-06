"""日期：2026-11-07；双Windows完整构建及23核心回归，保存拒绝草稿和8MiB边界的原Qt报告。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；测试使用现有隔离offscreen，不读取系统剪贴板，所有源字节前后核对。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/text-send-r99-windows'
    output.mkdir(exist_ok=False)
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    inputs = json.loads((root / 'docs/ci-verification-20261107-r98.json').read_text('utf-8'))['buildInputs']
    records = [{'path': row['path'], 'sha256': hashlib.sha256((root / row['path']).read_bytes()).hexdigest()}
               for row in inputs]
    (output / 'build-inputs.json').write_text(json.dumps(records, indent=2) + '\n', 'utf-8')
    results = []
    for label, folder, cmake, ctest, extra in [
            ('ucrt', 'windows-ucrt', '.tools/msys64/ucrt64/bin/cmake.exe', '.tools/msys64/ucrt64/bin/ctest.exe', []),
            ('msvc', 'windows', '.tools/python/Scripts/cmake.exe', '.tools/python/Scripts/ctest.exe', ['-C', 'Release'])]:
        target = output / label
        target.mkdir()
        with (target / 'build.log').open('xb') as log:
            build = subprocess.run([str(root / cmake), '--build', str(root / 'build' / folder),
                                    '--config', 'Release', '--parallel', '2'],
                                   env=environment(label), stdout=log, stderr=subprocess.STDOUT, timeout=1800)
        code = None
        if build.returncode == 0:
            with (target / 'ctest.log').open('xb') as log:
                process = subprocess.run([str(root / ctest), '--test-dir', str(root / 'build' / folder),
                                          *extra, '--output-on-failure'], env=environment(label),
                                         stdout=log, stderr=subprocess.STDOUT, timeout=3600)
            code = process.returncode
            shutil.copytree(root / 'build' / folder / 'Testing/QtTest', target / 'QtTest')
            shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
        result = {'toolchain': label, 'buildExitCode': build.returncode, 'ctestExitCode': code,
                  'passed': build.returncode == 0 and code == 0}
        results.append(result)
        print(json.dumps(result), flush=True)
    unchanged = all(hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256'] for row in records)
    value = {'buildInputsUnchanged': unchanged, 'cases': results, 'completed': True,
             'passed': unchanged and all(row['passed'] for row in results),
             'cleanBuild': False, 'entireProtocolSuiteRun': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
