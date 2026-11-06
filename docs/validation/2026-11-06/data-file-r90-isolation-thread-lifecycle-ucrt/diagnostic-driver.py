"""日期：2026-11-06；三次独立采集原专项及空闲线程生存期，所有失败均原样保留。"""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import sys
import time
import traceback


# 日期：2026-11-06；摘要绑定本次同一二进制及未修改的正式专项输入。
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-06；每个实例在原第12次样本后观察60秒，返回原样本且不改变原断言。
def attempt(output, observer, number):
    directory = output / ('attempt-' + str(number))
    directory.mkdir(exist_ok=False)
    script = Path('tests/parallel_isolation_integration.py')
    binary = Path('build/windows-ucrt/dukto-cli.exe').resolve()
    scope = runpy.run_path(str(script))
    original = scope['idle_sample']
    observations = []
    observer.__globals__['START'] = time.monotonic()

    # 日期：2026-11-06；原样本和相邻原生快照同时留档；额外观察不写回原正式样本。
    def sample(process):
        value = original(process)
        row = observer(process)
        row['originalSample'] = value
        observations.append(row)
        if len(observations) == 12:
            for _ in range(12):
                time.sleep(5)
                observations.append(observer(process))
        return value

    scope['main'].__globals__['idle_sample'] = sample
    sys.argv = [str(script), str(binary), '--report', str(directory / 'original-report.json')]
    failure = None
    with (directory / 'driver.log').open('x', encoding='utf-8') as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                scope['main']()
            except Exception as error:
                failure = {'type': type(error).__name__, 'message': str(error)}
                traceback.print_exc()
    result = {'binarySha256': sha(binary), 'originalScriptSha256': sha(script),
              'originalAssertionsUnchanged': True, 'failure': failure, 'observations': observations}
    (directory / 'diagnosis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    initial = {row['id'] for row in observations[0]['rows']} if observations else set()
    additions = {row['id']: {key: row.get(key) for key in ('id', 'startModule', 'moduleOffset')}
                 for observation in observations for row in observation['rows'] if row['id'] not in initial}
    summary = {'attempt': number, 'failure': failure, 'sampleCounts': [row['originalSample']['threads']
               for row in observations if 'originalSample' in row],
               'observedCounts': [row['threads'] for row in observations], 'addedThreads': list(additions.values()),
               'diagnosisSha256': sha(directory / 'diagnosis.json')}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


# 日期：2026-11-06；限定三次诊断且不按通过与否追加重试，旧失败记录不可覆盖。
def main():
    output = Path('docs/validation/2026-11-06/data-file-r90-isolation-thread-lifecycle-ucrt')
    output.mkdir(exist_ok=False)
    shutil.copyfile(__file__, output / 'diagnostic-driver.py')
    sys.path.insert(0, str(Path('tests').resolve()))
    environment = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']('ucrt')
    os.environ.clear()
    os.environ.update(environment)
    observer = runpy.run_path('.cache/diagnose-isolation-threads-r90.py')['observe']
    binary = Path('build/windows-ucrt/dukto-cli.exe')
    script = Path('tests/parallel_isolation_integration.py')
    before = (sha(binary), sha(script))
    rows = [attempt(output, observer, number) for number in range(1, 4)]
    assert before == (sha(binary), sha(script))
    result = {'sourceCommit': 'effd3115e95e696077a13038f3bb0616362eac5d', 'binarySha256': before[0],
              'originalScriptSha256': before[1], 'attempts': rows, 'firstFailureRetained': True,
              'originalFailedInstanceRootCauseProven': False, 'expectationsWeakened': False}
    (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')


if __name__ == '__main__':
    main()
