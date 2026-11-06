"""日期：2026-11-07；收验Ubuntu20轮原件和真实长测启动快照，完整24小时结论保持待验。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import runpy
import shutil
import subprocess
import tarfile


# 日期：2026-11-07；在远端先逐摘要确认冻结文件和运行依赖，再只读快照已稳定短测及长测初始报告。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-07/linux-r98-stability-launch'
    assert not output.exists()
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    program = '''from datetime import datetime, timezone
import hashlib, io, json, sys, tarfile
from pathlib import Path
root = Path('/home/dukto/current-linux-r98-long')
results = root / 'results'
launch = json.loads((results / 'launch.json').read_text('utf-8'))
assert launch['sourceCommit'] == 'b2e4659b347c65eef24c8e568e07e96a2d6ff2d7'
assert launch['binarySha256'] == '816b549fd5c34be611e9e1f669e54ab8a2c224ace1206cc3b314adcceb9d2412'
assert all(hashlib.sha256((root / name).read_bytes()).hexdigest() == sha
           for name, sha in launch['frozenFiles'].items())
assert all(hashlib.sha256(Path(name).read_bytes()).hexdigest() == sha
           for name, sha in launch['runtimeDependencies'].items())
short = json.loads((results / 'smoke20.json').read_text('utf-8'))
long_bytes = (results / 'summary24h.json').read_bytes()
long = json.loads(long_bytes)
sampling = json.loads((results / 'sampling.json').read_text('utf-8'))
assert sampling['passed'] and short['passed'] and short['status'] == 'passed' and short['rounds'] == 20
assert short['requestedChannels'] == long['requestedChannels'] == 16
assert long['status'] == 'running' and not long['passed'] and long['rounds'] >= 1
assert long['durationRequestedSeconds'] == 86400
assert long['executableSha256'] == short['executableSha256'] == launch['binarySha256']
names = ['launch.json', 'ldd-before.txt', 'sampling.json', 'sampling.log',
         'smoke20.json', 'smoke20.log', 'smoke20-samples.csv', 'smoke20-test-inputs.json',
         'summary24h-test-inputs.json']
files = {name: (results / name).read_bytes() for name in names}
files['summary24h-initial.json'] = long_bytes
observation = {'observedUtc': datetime.now(timezone.utc).isoformat(),
               'frozenFilesVerified': len(launch['frozenFiles']),
               'runtimeDependenciesVerified': len(launch['runtimeDependencies']),
               'allFrozenInputsUnchanged': True, 'shortRoundsPassed': 20,
               'longTestRunning': True, 'longTestQualified': False}
files['frozen-observation.json'] = (json.dumps(observation, indent=2) + '\\n').encode('utf-8')
with tarfile.open(fileobj=sys.stdout.buffer, mode='w|gz') as archive:
    for name, raw in files.items():
        assert len(raw) < 4 * 1024**2
        member = tarfile.TarInfo(name)
        member.size = len(raw)
        archive.addfile(member, io.BytesIO(raw))
'''
    result = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'),
                            capture_output=True, timeout=60)
    if result.returncode:
        failure = root / '.cache/linux-r98-long-launch-collection-failure.json'
        assert not failure.exists()
        failure.write_text(json.dumps({'exitCode': result.returncode,
                                       'stderr': result.stderr.decode('utf-8')}, indent=2) + '\n', 'utf-8')
        raise RuntimeError(result.stderr.decode('utf-8'))
    assert not result.stderr
    archive_path = root / '.cache/linux-r98-long-launch-snapshot.tar.gz'
    assert not archive_path.exists()
    archive_path.write_bytes(result.stdout)
    output.mkdir()
    with tarfile.open(archive_path) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert len(path.parts) == 1 and not path.is_absolute() and '..' not in path.parts
            assert ':' not in member.name and member.isfile() and member.size < 4 * 1024**2
            (output / member.name).write_bytes(archive.extractfile(member).read())
    launch = json.loads((output / 'launch.json').read_text('utf-8'))
    short = json.loads((output / 'smoke20.json').read_text('utf-8'))
    initial = json.loads((output / 'summary24h-initial.json').read_text('utf-8'))
    observation = json.loads((output / 'frozen-observation.json').read_text('utf-8'))
    tests = json.loads((output / 'smoke20-test-inputs.json').read_text('utf-8'))['files']
    long_tests = json.loads((output / 'summary24h-test-inputs.json').read_text('utf-8'))['files']
    assert tests == long_tests
    for name, sha in tests.items():
        assert launch['frozenFiles']['tests/' + name] == sha
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(),
             'sourceCommit': launch['sourceCommit'], 'binarySha256': launch['binarySha256'],
             'shortRoundsPassed': short['rounds'], 'requestedChannels': 16,
             'samplingSelfCheckPassed': True, 'allFrozenInputsUnchanged': observation['allFrozenInputsUnchanged'],
             'frozenFilesVerified': observation['frozenFilesVerified'],
             'runtimeDependenciesVerified': observation['runtimeDependenciesVerified'],
             'longRequestedSeconds': initial['durationRequestedSeconds'],
             'longObservedRounds': initial['rounds'], 'longObservedStatus': initial['status'],
             'reports': [proof(path) for path in sorted(output.iterdir())],
             'longTestQualified': False, 'qualificationScope': launch['qualificationScope'],
             'releaseQualified': False, 'deliveryComplete': False, 'passed': True}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    shutil.copyfile(root / '.cache/start-current-linux-r98-long.py', output / 'launch-driver.py')
    print(json.dumps({k: value[k] for k in ('sourceCommit', 'shortRoundsPassed', 'frozenFilesVerified',
                                          'runtimeDependenciesVerified', 'longObservedStatus', 'longTestQualified')}), flush=True)


if __name__ == '__main__':
    main()
