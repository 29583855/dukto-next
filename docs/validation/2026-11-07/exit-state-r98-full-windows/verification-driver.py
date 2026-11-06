"""日期：2026-11-07；收验R98双Windows完整核心，不把专项或增量构建声称为干净重建。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；全部210输入与精确Git匹配，23目标/22Qt报告及新旧退出数据行均逐项检查。
def main():
    root = Path.cwd()
    commit = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    frozen = json.loads((root / 'docs/ci-verification-20261107-r98.json').read_text('utf-8'))
    assert len(frozen['buildInputs']) == 210
    for row in frozen['buildInputs']:
        raw = subprocess.check_output(['git', 'show', commit + ':' + row['path']],
                                      cwd=root / '.cache/github-29583855-dukto-next-r28')
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert raw == (root / row['path']).read_bytes()
    output = root / 'docs/validation/2026-11-07/exit-state-r98-full-windows'
    driver = json.loads((output / 'driver-result.json').read_text('utf-8'))
    assert driver['sourceCommit'] == commit and driver['completed'] and driver['passed']
    assert driver['buildInputsUnchanged'] == 210
    assert [row['toolchain'] for row in driver['cases']] == ['ucrt', 'msvc']
    assert all(row['buildExitCode'] == row['ctestExitCode'] == 0 for row in driver['cases'])
    verify_core = runpy.run_path('.cache/verify-r95-local-terminals.py')['core']
    results = []
    for label in ('ucrt', 'msvc'):
        folder = output / label
        result = verify_core(folder, folder / 'ctest.log', folder / 'QtTest')
        text = (folder / 'QtTest/file-exchange-tests.log').read_text('utf-8')
        for row in ('already-finished', 'already-finished-error', 'running-finishes', 'real-deadline'):
            assert 'PASS   : FileExchangeTests::childExitWait(' + row + ')' in text
        assert text.count('PASS   : FileExchangeTests::parallelDispositions(') == 16
        result.update(toolchain=label, newExitStateRows=4, originalParallelRows=16)
        results.append(result)
    value = {'sourceCommit': commit, 'buildInputsVerified': 210, 'allInputsMatchExactGitCommit': True,
             'toolchains': results, 'incrementalBuild': True, 'cleanBuild': False,
             'entireProtocolSuiteRun': False, 'passed': True, 'originalWaitMs': 10000,
             'releaseQualified': False, 'deliveryComplete': False}
    receipt = output / 'verified-receipt.json'
    assert not receipt.exists()
    receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/validate-exit-state-r98-full-windows.py', output / 'validation-driver.py')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'sourceCommit': commit, 'coreTargetsEach': 23, 'toolchains': 2,
                      'newExitStateRowsEach': 4, 'originalParallelRowsEach': 16, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()
