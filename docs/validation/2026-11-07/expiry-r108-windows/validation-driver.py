"""日期：2026-11-07；两种Windows工具链验证过期清理、版本三迁移及原传输边界。"""
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
import time


# 日期：2026-11-07；串行核心避免UDP竞争，保留所有真实命令、退出码和原始报告。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/expiry-r108-windows'
    output.mkdir(exist_ok=False)
    prior = json.loads((root / 'docs/ci-verification-20261107-r105.json').read_text('utf-8'))['buildInputs']
    names = sorted({row['path'] for row in prior} | {'src/core/expiredtaskcleanup.h', 'src/core/expiredtaskcleanup.cpp', 'tests/expired_task_cleanup_tests.cpp'})
    inputs = [dict(path=name, sha256=hashlib.sha256((root / name).read_bytes()).hexdigest()) for name in names]
    (output / 'build-inputs.json').write_text(json.dumps(inputs, indent=2) + '\n', 'utf-8')
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']
    results = []
    for label, folder, cmake, ctest, extra in [
        ('ucrt', 'windows-ucrt', '.tools/msys64/ucrt64/bin/cmake.exe', '.tools/msys64/ucrt64/bin/ctest.exe', []),
        ('msvc', 'windows', '.tools/python/Scripts/cmake.exe', '.tools/python/Scripts/ctest.exe', ['-C', 'Release'])]:
        target = output / label
        target.mkdir()
        env = environment(label)
        binary = root / 'build' / folder
        if label == 'msvc':
            binary /= 'Release'
        row = {'toolchain': label, 'cases': []}

        # 日期：2026-11-07；每个命令完成即持久记录，不能以最后一条成功覆盖更早失败。
        def check(name, args, timeout):
            started = time.monotonic()
            with (target / (name + '.log')).open('xb') as log:
                code = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
            row['cases'].append({'name': name, 'exitCode': code, 'seconds': round(time.monotonic() - started, 3)})
            (target / 'exit-codes.json').write_text(json.dumps(row, indent=2) + '\n', 'utf-8')
            print(json.dumps({'toolchain': label, **row['cases'][-1]}), flush=True)
            return code

        assert check('build', [str(root / cmake), '--build', str(root / 'build' / folder), '--config', 'Release', '--parallel', '2'], 1800) == 0
        before = {name: hashlib.sha256((binary / name).read_bytes()).hexdigest() for name in ('dukto-cli.exe', 'secure-channel-probe.exe', 'expired-task-cleanup-tests.exe')}
        check('ctest', [str(root / ctest), '--test-dir', str(root / 'build' / folder), *extra, '--output-on-failure'], 1200)
        shutil.copytree(root / 'build' / folder / 'Testing/QtTest', target / 'QtTest')
        shutil.copyfile(root / 'build' / folder / 'Testing/Temporary/LastTest.log', target / 'LastTest.log')
        openssl = root / ('.tools/msys64/ucrt64/bin/openssl.exe' if label == 'ucrt' else '.tools/openssl/Library/bin/openssl.exe')
        for name, script, exe, extra in [
            ('secure-channel', 'secure_channel_integration', 'secure-channel-probe.exe', ['--openssl', str(openssl)]),
            ('task-items', 'task_items_integration', 'dukto-cli.exe', []),
            ('transfer16', 'transfer_integration', 'dukto-cli.exe', ['--threads', '16'])]:
            check(name, [sys.executable, '-X', 'utf8', 'tests/' + script + '.py', str(binary / exe), *extra, '--report', str(target / (name + '.json'))], 600)
        after = {name: hashlib.sha256((binary / name).read_bytes()).hexdigest() for name in before}
        assert before == after
        row.update(binarySha256=before, binaryUnchanged=True, passed=all(item['exitCode'] == 0 for item in row['cases']))
        results.append(row)
        (output / 'progress.json').write_text(json.dumps(results, indent=2) + '\n', 'utf-8')
    unchanged = all(hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256'] for row in inputs)
    value = {'cases': results, 'buildInputsUnchanged': unchanged, 'passed': unchanged and all(row['passed'] for row in results), 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'driver-result.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, output / 'validation-driver.py')
    return 0 if value['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
