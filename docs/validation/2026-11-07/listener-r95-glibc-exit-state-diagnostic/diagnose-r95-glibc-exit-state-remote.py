"""日期：2026-11-07；独立诊断Qt已退出状态与原十秒等待，不修改原构建或原断言语义。"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

ROOT = Path('/home/dukto/listener-r95-final')
OUTPUT = Path('/home/dukto/listener-r95-exit-state-diagnostic')


# 日期：2026-11-07；仅计算固定原文件摘要，诊断结束后再次核对，禁止覆盖原件。
def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


# 日期：2026-11-07；仅在新目录编译测试副本，复用精确原核心库并逐行记录原等待行为。
def main():
    OUTPUT.mkdir(exist_ok=False)
    binary = ROOT / 'build/file-exchange-tests'
    core = ROOT / 'build/libdukto-core.a'
    before = {str(path): digest(path) for path in (binary, core)}
    source_path = ROOT / 'tests/file_exchange_tests.cpp'
    source = source_path.read_text('utf-8')
    old = '        QVERIFY(server.waitForFinished(10000));'
    assert source.count(old) == 1
    replacement = '''        // 日期：2026-11-07；诊断副本仅增加状态日志，保留原十秒等待和原失败条件。
        qInfo() << "exit-state-before" << "state" << server.state()
                << "pid" << server.processId() << "error" << server.error();
        QElapsedTimer exitStateTimer;
        exitStateTimer.start();
        const bool exitStateWaitResult = server.waitForFinished(10000);
        qInfo() << "exit-state-after" << "state" << server.state()
                << "result" << exitStateWaitResult << "elapsedMs" << exitStateTimer.elapsed()
                << "exitStatus" << server.exitStatus() << "exitCode" << server.exitCode();
        QVERIFY(exitStateWaitResult);'''
    source = source.replace(old, replacement)
    probe_source = OUTPUT / 'file_exchange_tests.cpp'
    probe_source.write_text(source, 'utf-8')
    commands = subprocess.run(['ninja', '-t', 'commands', 'file-exchange-tests'],
                              cwd=ROOT / 'build', capture_output=True, text=True, check=True)
    compile_line, = [line for line in commands.stdout.splitlines()
                     if ' -c ' in line and str(source_path) in line]
    object_name = 'CMakeFiles/file-exchange-tests.dir/tests/file_exchange_tests.cpp.o'
    object_path = OUTPUT / 'probe.o'
    replacements = {object_name: str(object_path), object_name + '.d': str(OUTPUT / 'probe.o.d'),
                    str(source_path): str(probe_source)}
    compile_args = [replacements.get(arg, arg) for arg in shlex.split(compile_line)]
    link_line, = [line for line in commands.stdout.splitlines()
                  if line.startswith(': && ') and ' -o file-exchange-tests ' in line]
    assert link_line.endswith(' && :')
    link_args = shlex.split(link_line[len(': && '):-len(' && :')])
    probe = OUTPUT / 'file-exchange-tests-probe'
    link_args = [str(object_path) if arg == object_name else
                 str(probe) if arg == 'file-exchange-tests' else arg for arg in link_args]
    with (OUTPUT / 'compile.log').open('xb') as log:
        subprocess.run(compile_args, cwd=ROOT / 'build', stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=300)
        subprocess.run(link_args, cwd=ROOT / 'build', stdout=log, stderr=subprocess.STDOUT,
                       check=True, timeout=120)
    environment = os.environ.copy()
    environment['QT_QPA_PLATFORM'] = 'offscreen'
    started = time.monotonic()
    with (OUTPUT / 'probe.stdout.log').open('xb') as log:
        result = subprocess.run([str(probe), 'parallelDispositions',
                                 '-o', str(OUTPUT / 'probe.log') + ',txt',
                                 '-o', str(OUTPUT / 'probe.xml') + ',junitxml'],
                                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                timeout=1200)
    assert all(digest(Path(path)) == expected for path, expected in before.items())
    value = {'sourceCommit': '5dd243fbad36da36568943513deed95ee124ba2d',
             'originalFiles': before, 'originalBinaryAndCoreUnchanged': True,
             'diagnosticSourceSha256': digest(probe_source), 'diagnosticBinarySha256': digest(probe),
             'originalWaitMs': 10000, 'originalFailureConditionUnchanged': True,
             'exitCode': result.returncode, 'seconds': round(time.monotonic() - started, 3),
             'observerMayPerturbTiming': True, 'productionFixProven': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (OUTPUT / 'report.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)


if __name__ == '__main__':
    main()
