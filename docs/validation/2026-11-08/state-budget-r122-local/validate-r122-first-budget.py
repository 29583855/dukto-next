"""日期：2026-11-08；冻结本轮首次真实账本专项的源码/程序身份与原XML，失败保留。"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；直接运行已构建测试，记录真实退出和前后身份，不在失败后覆盖原报告。
def main():
    root = Path.cwd()
    output = root / '.cache/r122-first-msvc'
    output.mkdir(exist_ok=False)
    names = ['CMakeLists.txt', 'src/core/budgetfile.h', 'src/core/statebudget.h', 'src/core/statebudget.cpp',
             'src/core/privatestore.cpp', 'src/core/privatestore.h', 'tests/state_budget_tests.cpp']
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}
    binary = root / 'build/windows/Release/state-budget-tests.exe'
    before = hashlib.sha256(binary.read_bytes()).hexdigest()
    environment = os.environ.copy()
    environment['PATH'] = str(root / '.tools/Qt/5.15.2/msvc2019_64/bin') + os.pathsep + str(root / '.tools/openssl/Library/bin') + os.pathsep + environment['PATH']
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run([str(binary), '-o', str(output / 'state-budget-tests.xml') + ',xml'],
                                stdout=log, stderr=subprocess.STDOUT, env=environment, timeout=300)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'exitCode': result.returncode,
             'inputs': inputs, 'binaryBeforeSha256': before,
             'binaryAfterSha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
             'inputsAfter': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
             'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({'exitCode': result.returncode, 'binaryUnchanged': before == value['binaryAfterSha256'],
                      'inputsUnchanged': inputs == value['inputsAfter']}))
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
