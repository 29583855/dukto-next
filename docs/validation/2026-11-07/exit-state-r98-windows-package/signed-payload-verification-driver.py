"""日期：2026-11-07；用公开摘要固定的旧验签映射核对未变化依赖，不伪造缺失的历史清单。"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile


# 日期：2026-11-07；固定缓冲散列实际包、缓存归档和许可，内存不随依赖包大小增长。
def digest(stream):
    return hashlib.file_digest(stream, 'sha256').hexdigest()


# 日期：2026-11-07；公开R68记录固定原R25验签映射摘要；本次重新核对全部新部署字节和原归档。
def verify_dependencies(archive, output):
    root = Path.cwd()
    commit = 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
    raw = subprocess.check_output(['git', 'show', commit + ':docs/ci-verification-20261106-r68.json'],
                                  cwd=root / '.cache/github-29583855-dukto-next-r28')
    published = json.loads(raw)
    link = published['windows']['evidence']['dependencies']
    previous_path = root / link['path']
    previous_raw = previous_path.read_bytes()
    assert hashlib.sha256(previous_raw).hexdigest() == link['sha256']
    previous = json.loads(previous_raw)
    assert previous['passed'] and previous['binaryPackages'] == 24
    assert previous['signedPayloadFilesVerified'] == 364
    assert previous['signedPackageLicenseFilesVerified'] == 53
    trusted = {row['package']: row for row in previous['records']}
    prefix = 'DuktoNext-windows-x64-preview/'
    records = []
    with zipfile.ZipFile(archive) as package:
        manifest = json.loads(package.read(prefix + 'package-manifest.json'))
        metadata = json.loads(package.read(prefix + 'dependency-packages.json'))
        assert set(metadata) == set(trusted) and len(trusted) == 24
        for name, current in sorted(metadata.items()):
            prior = trusted[name]
            assert current['VERSION'][0] == prior['version']
            cached = root / '.tools/msys64/var/cache/pacman/pkg' / (
                name + '-' + prior['version'] + '-' + current['ARCH'][0] + '.pkg.tar.zst')
            with cached.open('rb') as stream:
                assert digest(stream) == prior['signedBinaryArchiveSha256']
            with (root / prior['recipe']).open('rb') as stream:
                assert digest(stream) == prior['exactRecipeSha256']
            expected = {row['signedPackageMember']: row for row in prior['deployedFiles']}
            deployed = {row['installedPath']: row for row in manifest['dependencyFiles'] if row['package'] == name}
            assert set(deployed) == set(expected)
            checked = []
            for member, row in deployed.items():
                old = expected[member]
                assert row['path'] == old['deployedPath'] and row['sha256'] == old['sha256']
                with package.open(prefix + row['path']) as stream:
                    assert digest(stream) == old['sha256']
                assert package.getinfo(prefix + row['path']).file_size == old['bytes']
                checked.append(old)
            licenses = []
            for row in prior['signedPackageLicenseFiles']:
                with package.open(prefix + row['deployedPath']) as stream:
                    assert digest(stream) == row['sha256']
                assert package.getinfo(prefix + row['deployedPath']).file_size == row['bytes']
                licenses.append(row)
            records.append(dict(prior, deployedFiles=checked, signedPackageLicenseFiles=licenses,
                                cachedBinaryArchiveDigestReverified=True, exactRecipeDigestReverified=True))
    result = {'date': '2026-11-07', 'passed': True, 'binaryPackages': len(records),
              'signedPayloadFilesVerified': sum(len(row['deployedFiles']) for row in records),
              'signedPackageLicenseFilesVerified': sum(len(row['signedPackageLicenseFiles']) for row in records),
              'records': records, 'priorTrustedReceipt': link,
              'priorReceiptPublicAnchor': {'commit': commit, 'path': 'docs/ci-verification-20261106-r68.json',
                                           'sha256': hashlib.sha256(raw).hexdigest()},
              'signatureVerificationReusedFromPriorReceipt': True, 'freshSignatureVerificationPerformed': False,
              'missingOriginalR12InventoryRestored': False, 'correspondingSourceComplete': False,
              'releaseQualified': False,
              'scope': 'All current dependency and recorded license bytes match the public-hash-pinned R25 signed-payload receipt; original signed archive and exact recipe digests reverified. Historical R12 inventory remains unavailable; no new signature verification or source rebuild claimed.'}
    target = output / 'signed-payload-map.json'
    assert not target.exists()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(previous_path, output / 'prior-r25-signed-payload-map.json')
    (output / 'prior-r68-public-anchor.json').write_bytes(raw)
    shutil.copyfile(Path(__file__), output / 'signed-payload-verification-driver.py')
    return target
