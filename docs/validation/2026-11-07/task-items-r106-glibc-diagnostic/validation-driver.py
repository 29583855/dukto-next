"""日期：2026-11-07；上传隔离诊断程序并只收集列明的非凭据证据。"""
from pathlib import Path
import json
import runpy
import shutil
import subprocess
import tarfile


# 日期：2026-11-07；不更改Ubuntu二进制/现有测试；诊断退出码及原始跟踪均保留。
def main():
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    output = Path('docs/validation/2026-11-07/task-items-r106-glibc-diagnostic')
    output.mkdir(exist_ok=False)
    driver = Path('.cache/task-items-r106-diagnostic-remote.py')
    with (output / 'driver.log').open('xb') as log:
        code = subprocess.run(ssh + ['python3 -'], input=driver.read_bytes(), stdout=log,
                              stderr=subprocess.STDOUT, timeout=300).returncode
    (output / 'driver-exit.json').write_text(json.dumps({'exitCode': code}) + '\n')
    names = ['diagnostic-result.json', 'samples.jsonl', 'events.jsonl', 'server.stderr',
             'client.stderr', 'server-sync.trace', 'client-sync.trace']
    with (output / 'results.tar.gz').open('xb') as data:
        collection = subprocess.run(ssh + ['tar czf - -C /home/dukto/task-items-r106-diagnostic ' + ' '.join(names)],
                                    stdout=data, stderr=subprocess.PIPE, timeout=60)
    (output / 'collection.stderr').write_bytes(collection.stderr)
    (output / 'collection-exit.json').write_text(json.dumps({'exitCode': collection.returncode}) + '\n')
    with tarfile.open(output / 'results.tar.gz') as archive:
        for item in archive:
            assert item.isfile() and item.name in names and item.size <= 8 * 1024**2
            (output / item.name).write_bytes(archive.extractfile(item).read())
    shutil.copyfile(driver, output / 'remote-driver.py')
    shutil.copyfile(__file__, output / 'validation-driver.py')
    assert code == collection.returncode == 0
    print((output / 'diagnostic-result.json').read_text())


if __name__ == '__main__':
    main()
