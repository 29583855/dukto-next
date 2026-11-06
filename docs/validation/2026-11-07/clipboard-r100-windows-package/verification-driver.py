"""日期：2026-11-07；将当前Windows实际ZIP绑定到精确源码、构建二进制及受信依赖原件。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import zipfile


# 日期：2026-11-07；迁移必须终态成功，再逐件比较源码Git字节与签名包载荷，截图资格另行登记。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/clipboard-r100-windows-package'
    result = json.loads((output / 'driver-result.json').read_text('utf-8'))
    assert result['sourceCommit'] == 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
    assert result['completed'] and result['passed'] and result['allFrozenInputsUnchanged']
    assert len(result['cases']) == 2 and all(row['exitCode'] == 0 for row in result['cases'])
    archive = root / result['archive']
    with archive.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == result['archiveSha256']
    runtime_path = output / 'runtime.json'
    runtime = json.loads(runtime_path.read_text('utf-8'))
    assert runtime['passed'] and runtime['archiveSha256'] == result['archiveSha256']
    assert runtime['workingPathUnicodeAndSpaces'] and runtime['developerPathsRemoved']
    runpy.run_path('.cache/verify-overwrite-r62-terminal.py')['passed_flags'](runtime)
    prefix = 'DuktoNext-windows-x64-preview/'
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read(prefix + 'package-manifest.json'))
        full_sources = runpy.run_path('.cache/fetch-linux-preview-r98.py')['full_sources']
        full_sources.__globals__['COMMIT'] = result['sourceCommit']
        sources = full_sources(
            bundle.read(prefix + 'DuktoNext-corresponding-source.zip'), manifest['sourceFiles'],
            result['sourceCommit'], root / '.cache/github-29583855-dukto-next-r28')
        assert sources == 338
        for name, expected in result['binaries'].items():
            raw = bundle.read(prefix + name)
            assert hashlib.sha256(raw).hexdigest() == expected
            assert raw == (root / 'build/windows-ucrt' / name).read_bytes()
    target = runpy.run_path('.cache/verify-r98-dependency-reuse.py')['verify_dependencies'](archive, output)
    dependencies = json.loads(target.read_text('utf-8'))
    assert dependencies['passed'] and dependencies['binaryPackages'] == 24
    assert dependencies['signedPayloadFilesVerified'] == 364
    assert dependencies['signedPackageLicenseFilesVerified'] == 53
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    value = dict(result, sourceFilesVerified=sources, allSourceBlobsMatchExactGitCommit=True,
                 signedDependencyFiles=364, signedDependencyPackages=24, signedLicenseFiles=53,
                 runtimeEvidence=proof(runtime_path), dependencyEvidence=proof(target), screenshotsViewed=False,
                 signatureVerificationReusedFromPriorReceipt=True, freshSignatureVerificationPerformed=False,
                 missingOriginalR12InventoryRestored=False,
                 correspondingThirdPartySourceComplete=False, cleanSystemQualified=False)
    receipt = output / 'verified-receipt.json'
    assert not receipt.exists()
    receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/package-r100-windows.py', output / 'package-validation-driver.py')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    shutil.copyfile(root / '.cache/prepare-r100-package-source.py', output / 'source-freeze-driver.py')
    shutil.copyfile(root / '.cache/windows-r100-package-source.json', output / 'source-freeze.json')
    print(json.dumps({'sourceFilesVerified': sources, 'signedDependencyFiles': 364,
                      'signedDependencyPackages': 24, 'signedLicenseFiles': 53, 'runtimePassed': True}), flush=True)


if __name__ == '__main__':
    main()
