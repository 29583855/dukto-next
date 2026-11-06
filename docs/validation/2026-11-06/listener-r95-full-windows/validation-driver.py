"""日期：2026-11-06；R95双Windows全量编译与23核心独立回归，固定输入并保留所有原件。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-06；两套核心顺序执行，避免发现端口或系统剪贴板相互干扰；失败仍完整留档。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-06/listener-r95-full-windows'
    output.mkdir(exist_ok=False)
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    inputs = json.loads((root / 'docs/ci-verification-20261106-r95.json').read_text('utf-8'))['buildInputs']
    assert len(inputs) == 207
    for row in inputs:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
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
    for row in inputs:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    value = {'sourceCommit': '5dd243fbad36da36568943513deed95ee124ba2d', 'buildInputsUnchanged': 207,
             'cases': results, 'completed': True, 'passed': all(row['passed'] for row in results),
             'entireProtocolSuiteRun': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
