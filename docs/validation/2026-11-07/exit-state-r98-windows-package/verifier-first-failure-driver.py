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
    output = root / 'docs/validation/2026-11-07/exit-state-r98-windows-package'
    result = json.loads((output / 'driver-result.json').read_text('utf-8'))
    assert result['sourceCommit'] == 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
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
        sources = runpy.run_path('.cache/fetch-linux-preview-r98.py')['full_sources'](
            bundle.read(prefix + 'DuktoNext-corresponding-source.zip'), manifest['sourceFiles'],
            result['sourceCommit'], root / '.cache/github-29583855-dukto-next-r28')
        assert sources == 333
        for name, expected in result['binaries'].items():
            raw = bundle.read(prefix + name)
            assert hashlib.sha256(raw).hexdigest() == expected
            assert raw == (root / 'build/windows-ucrt' / name).read_bytes()
    original = (root / '.cache/audit-windows-r24-signed-payloads-r52.py').read_text('utf-8')
    original = original.replace('dist/windows-preview-20261105-r24-peer-close',
                                'dist/windows-preview-20261107-r98-exit-state')
    original = original.replace('ad02396dbba52a80df3e21315d79aa10936ea44a1fc7a77fae97f355801826ee',
                                result['archiveSha256'])
    original = original.replace("(evidence / 'windows-r24-signed-payload-map-r52.json')",
                                "(root / 'docs/validation/2026-11-07/exit-state-r98-windows-package/signed-payload-map.json')")
    original = original.replace('actual r24 deployed', 'actual R98 deployed')
    original = original.replace("report = {'date': '2026-11-05'", "report = {'date': '2026-11-07'")
    target = output / 'signed-payload-map.json'
    assert not target.exists()
    exec(compile(original, 'r98_signed_payload_verification', 'exec'), {'__name__': 'r98_signed_payload_verification'})
    dependencies = json.loads(target.read_text('utf-8'))
    assert dependencies['passed'] and dependencies['binaryPackages'] == 24
    assert dependencies['signedPayloadFilesVerified'] == 364
    assert dependencies['signedPackageLicenseFilesVerified'] == 53
    (output / 'signed-payload-verification-driver.py').write_text(original, 'utf-8')
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    value = dict(result, sourceFilesVerified=sources, allSourceBlobsMatchExactGitCommit=True,
                 signedDependencyFiles=364, signedDependencyPackages=24, signedLicenseFiles=53,
                 runtimeEvidence=proof(runtime_path), dependencyEvidence=proof(target), screenshotsViewed=False,
                 correspondingThirdPartySourceComplete=False, cleanSystemQualified=False)
    receipt = output / 'verified-receipt.json'
    assert not receipt.exists()
    receipt.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(root / '.cache/package-r98-windows.py', output / 'package-validation-driver.py')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    shutil.copyfile(root / '.cache/prepare-r98-package-source.py', output / 'source-freeze-driver.py')
    shutil.copyfile(root / '.cache/windows-r98-package-source.json', output / 'source-freeze.json')
    print(json.dumps({'sourceFilesVerified': sources, 'signedDependencyFiles': 364,
                      'signedDependencyPackages': 24, 'signedLicenseFiles': 53, 'runtimePassed': True}), flush=True)


if __name__ == '__main__':
    main()
