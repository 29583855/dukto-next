"""日期：2026-11-08；只读核对独立Ubuntu实际安装输入与冻结快照，不以当前文档替换旧快照。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-08；逐件验证远端实际字节、完整manifest和C++14构建选项，测试结论单独记录。
def main():
    root = Path.cwd()
    output = root / '.cache/r121-glibc-installed-source.json'
    assert not output.exists()
    ssh = runpy.run_path(str(root / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    program = '''import hashlib,json,subprocess
from pathlib import Path
root=Path('/home/dukto/state-inventory-r121-qualified')
manifest=json.loads((root/'.dukto-source-snapshot.json').read_bytes())
actual={}
for name in manifest['files']:
    raw=(root/name).read_bytes()
    actual[name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
assert actual==manifest['files']
ninja=(root/'build/build.ninja').read_text()
assert '-std=c++14' in ninja
print(json.dumps({'files':actual,'cpp14BuildFlagPresent':True,'compiler':subprocess.check_output(['c++','--version']).decode(),'qtVersion':subprocess.check_output(['qmake','-query','QT_VERSION']).decode().strip()}))
'''
    result = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    installed = json.loads(result.stdout)
    snapshot = root / '.cache/r121-native-state-source.tar.gz'
    sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    assert sha == '45b71d5c57c86939957ab13802b1f6f51a2c4e64734e0bad86d7971e32bb8c7d'
    manifest, _ = runpy.run_path(str(root / 'scripts/source_snapshot.py'))['read_archive'](snapshot)
    assert installed['files'] == manifest['files']
    index = json.loads((root / 'docs/ci-verification-20261108-r121.json').read_bytes())
    for row in index['qualificationInputs']:
        assert installed['files'][row['path']] == {'bytes': row['bytes'], 'sha256': row['sha256']}, row['path']
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'snapshotSha256': sha,
             'actualSourceFileCount': len(installed['files']), 'actualQualificationInputCount': len(index['qualificationInputs']),
             'allActualSourceBytesMatchFrozenSnapshot': True, 'allOriginalQualificationInputsMatch': True,
             'sourceDocumentsPrecedePublishedProgress': True, 'ciPosixCounterFixIncluded': False,
             'productInputsMatchR121': True, 'testQualificationGrantedByThisReceipt': False,
             'installed': installed, 'deliveryComplete': False, 'releaseQualified': False}
    output.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value[key] for key in ['actualSourceFileCount', 'actualQualificationInputCount',
                                               'allActualSourceBytesMatchFrozenSnapshot', 'productInputsMatchR121']}))


if __name__ == '__main__':
    main()
