"""日期：2026-11-07；准备精确R100 Windows部署及收验驱动，不改变历史R98包或长测。"""
import ast
from pathlib import Path


# 日期：2026-11-07；沿用完整迁移和依赖验证门槛，明确本次四GUI回归与十九个既有相同二进制的范围。
def main():
    root = Path.cwd()
    for name in ('package-r98-windows.py', 'verify-r98-windows-package.py'):
        text = (root / '.cache' / name).read_bytes().decode('utf-8')
        text = text.replace('b2e4659b347c65eef24c8e568e07e96a2d6ff2d7', 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3')
        text = text.replace('r98', 'r100').replace('333', '338')
        text = text.replace('exit-state-r100-windows-package', 'clipboard-r100-windows-package')
        text = text.replace('windows-preview-20261107-r100-exit-state', 'windows-preview-20261107-r100-clipboard')
        if name == 'package-r98-windows.py':
            text = text.replace('exit-state-r100-full-windows/verified-receipt.json',
                                'clipboard-r100-qualified/verified-receipt.json')
            old = "    assert verified['sourceCommit'] == 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3' and verified['passed']"
            new = """    assert verified['passed'] and len(verified['windows']) == 2
    assert verified['incrementalBuild'] and not verified['freshFull23TargetsRun']
    assert len(verified['buildInputs']) == 210
    for row in verified['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    prior = json.loads((root / 'docs/validation/2026-11-07/clipboard-r100-windows/driver-result.json').read_text('utf-8'))
    ucrt, = [row for row in prior['cases'] if row['toolchain'] == 'ucrt']
    assert ucrt['passed'] and len(ucrt['guiTargets']) == 4 and len(ucrt['unchangedCoreTestBinaries']) == 19
    for name, expected in ucrt['unchangedCoreTestBinaries'].items():
        assert hashlib.sha256((root / 'build/windows-ucrt' / (name + '.exe')).read_bytes()).hexdigest() == expected
"""
            assert text.count(old) == 1
            text = text.replace(old, new.rstrip())
            text = text.replace("    assert frozen['sourceCommit'] == verified['sourceCommit'] and frozen['buildInputsVerified'] == 210",
                                "    assert frozen['sourceCommit'] == 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3' and frozen['buildInputsVerified'] == 210")
            marker = '    output.mkdir(parents=True)'
            assert text.count(marker) == 1
            text = text.replace(marker, marker + """
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']('ucrt')
    with (output / 'build-binding.log').open('xb') as log:
        subprocess.run([str(root / '.tools/msys64/ucrt64/bin/cmake.exe'), '--build',
                        str(root / 'build/windows-ucrt'), '--config', 'Release', '--parallel', '2'],
                       env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
    assert 'ninja: no work to do.' in (output / 'build-binding.log').read_text('utf-8')
    assert all(hashlib.sha256((root / 'build/windows-ucrt' / name).read_bytes()).hexdigest() == sha
               for name, sha in binary_hashes.items())
""".rstrip())
            text = text.replace("'coreEvidence': str(full.relative_to(root)),", "'guiAndUnchangedCoreEvidence': str(full.relative_to(root)),\n             'guiTargetsRechecked': 4, 'existingCoreBinariesUnchanged': 19, 'freshFull23TargetsRun': False,")
        else:
            old = "        sources = runpy.run_path('.cache/fetch-linux-preview-r100.py')['full_sources']("
            new = """        full_sources = runpy.run_path('.cache/fetch-linux-preview-r98.py')['full_sources']
        full_sources.__globals__['COMMIT'] = result['sourceCommit']
        sources = full_sources("""
            assert text.count(old) == 1
            text = text.replace(old, new)
            text = text.replace(".cache/verify-r100-dependency-reuse.py", ".cache/verify-r98-dependency-reuse.py")
            text = text.replace('source-freeze-driver.py', 'source-freeze-driver.py')
        ast.parse(text)
        target = root / '.cache' / name.replace('r98', 'r100')
        assert not target.exists()
        target.write_bytes(text.encode('utf-8'))
    print('Prepared Windows package and strict verification for 338 exact Git source files')


if __name__ == '__main__':
    main()
