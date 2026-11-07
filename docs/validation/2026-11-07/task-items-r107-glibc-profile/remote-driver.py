"""日期：2026-11-07；隔离诊断201小文件下载，不放宽原90秒期限或更改冻结二进制。"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0, '/home/dukto/task-items-r105-after-core/tests')
from service_integration import free_port, run
from process_output import JsonOutputDrain
from transfer_integration import digest

OUTPUT = Path('/home/dukto/task-items-r107-profile')
BINARY = '/home/dukto/state-use-r104/build/dukto-cli'


# 日期：2026-11-07；只采集本次进程及线程的等待、CPU和IO指标，不读取环境或凭据。
def process_sample(parent):
    pending, found = [parent], []
    while pending and len(found) < 96:
        pid = pending.pop()
        root = Path('/proc') / str(pid)
        try:
            stat = (root / 'stat').read_text().split(') ', 1)[1].split()
            item = {'pid': pid, 'state': stat[0], 'cpuTicks': int(stat[11]) + int(stat[12]),
                    'rssPages': int(stat[21]), 'io': (root / 'io').read_text(), 'threads': []}
            for thread in sorted((root / 'task').iterdir())[:40]:
                item['threads'].append({'tid': int(thread.name), 'wait': (thread / 'wchan').read_text()})
                children = (thread / 'children').read_text().split()
                pending.extend(int(value) for value in children if int(value) not in pending)
            found.append(item)
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    return found


# 日期：2026-11-07；每秒记录固定上限的自有进程及系统压力，跟踪期间不修改系统设置。
def monitor(processes, stop, started):
    with (OUTPUT / 'samples.jsonl').open('x') as output:
        while not stop.is_set():
            value = {'seconds': round(time.monotonic() - started, 4),
                     'load': Path('/proc/loadavg').read_text().strip(),
                     'pressure': {name: Path('/proc/pressure', name).read_text()
                                  for name in ('cpu', 'io', 'memory')},
                     'processes': [process_sample(process.pid) for process in processes]}
            output.write(json.dumps(value) + '\n')
            output.flush()
            stop.wait(1)


# 日期：2026-11-07；逐行附加单调时间戳，服务输出另行持续消费，避免诊断管道影响传输。
def read_events(stream, started):
    with (OUTPUT / 'events.jsonl').open('x') as output:
        for line in stream:
            value = {'seconds': round(time.monotonic() - started, 6), 'event': json.loads(line)}
            output.write(json.dumps(value, ensure_ascii=False) + '\n')
            output.flush()


# 日期：2026-11-07；仅终止本诊断创建的独立进程组，等待strace保存原始统计。
def stop_process(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


# 日期：2026-11-07；保留同步系统调用次数及真实耗时，诊断结果不授予未完成整套测试资格。
def main():
    OUTPUT.mkdir(mode=0o700, exist_ok=False)
    before = digest(Path(BINARY))
    assert before == 'cefa0b54a009461d78f968160ea8bfdd46cf9b1690e52aadfafb76ed06bdd157'
    trace = []
    with tempfile.TemporaryDirectory(prefix='dukto-r106-diagnostic-') as temporary:
        root = Path(temporary)
        server, client, shared, destination = (root / name for name in ('server', 'client', 'shared', 'destination'))
        shared.mkdir()
        destination.mkdir()
        source = shared / 'source-download-16'
        (source / '资料/empty').mkdir(parents=True)
        expected = {}
        for index in range(201):
            path = source / '资料' / f'{index:04}.bin'
            path.write_bytes(bytes(range(251)) * 2 + str(index).encode())
            expected[path.relative_to(source).as_posix()] = digest(path)
        info, _ = run(BINARY, server, ['serve', 'init', '--server-name', '127.0.0.1'])
        rights = ['--share', 'data', '--allow-upload', '--allow-download', '--allow-browse']
        run(BINARY, server, ['serve', 'share', 'add', '--path', str(shared), *rights])
        offer, _ = run(BINARY, server, ['serve', 'pairing', *rights])
        port = free_port()
        with (OUTPUT / 'server.stderr').open('xb') as server_error, (OUTPUT / 'client.stderr').open('xb') as client_error:
            service = subprocess.Popen([*trace, BINARY, 'serve', 'start',
                                        '--state-directory', str(server), '--bind', '127.0.0.1', '--port', str(port), '--json'],
                                       stdout=subprocess.PIPE, stderr=server_error, text=True, start_new_session=True)
            try:
                assert json.loads(service.stdout.readline())['event'] == 'service-listening'
                drain = JsonOutputDrain(service.stdout)
                run(BINARY, client, ['pair', '--to', f'127.0.0.1:{port}', '--fingerprint', info['fingerprint'],
                                     '--credential-file', offer['credentialFile']])
                started = time.monotonic()
                process = subprocess.Popen([*trace, BINARY, 'download',
                                            '--share', 'data', '--remote-path', source.name, '--output', str(destination),
                                            '--threads', '16', '--state-directory', str(client), '--json'],
                                           stdout=subprocess.PIPE, stderr=client_error, text=True, start_new_session=True)
                stop = threading.Event()
                sampler = threading.Thread(target=monitor, args=([service, process], stop, started))
                reader = threading.Thread(target=read_events, args=(process.stdout, started))
                sampler.start()
                reader.start()
                # 日期：2026-11-07；低频仅用户态CPU采样附加到自有进程，原始栈数据保留于私有VM目录，禁止公开。
                perf_error = (OUTPUT / 'perf.stderr').open('xb')
                profile = subprocess.Popen(['sudo', '-n', 'perf', 'record', '-e', 'cpu-clock:u', '-F', '49',
                                            '--call-graph', 'dwarf,4096', '-p', f'{service.pid},{process.pid}',
                                            '-o', str(OUTPUT / 'profile.perf'), '--', 'sleep', '85'],
                                           stdout=subprocess.DEVNULL, stderr=perf_error)
                timed_out = False
                try:
                    process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    timed_out = True
                finally:
                    elapsed = time.monotonic() - started
                    stop_process(process)
                    stop.set()
                    sampler.join(5)
                    reader.join(5)
                    assert not sampler.is_alive() and not reader.is_alive()
                profile_code = profile.wait(timeout=95)
                perf_error.close()
                with (OUTPUT / 'perf-report.txt').open('xb') as report, (OUTPUT / 'perf-report.stderr').open('xb') as report_error:
                    report_code = subprocess.run(['sudo', '-n', 'perf', 'report', '--stdio', '--no-children',
                                                   '--percent-limit', '0.5', '--sort', 'comm,dso,symbol',
                                                   '-i', str(OUTPUT / 'profile.perf')], stdout=report,
                                                  stderr=report_error, timeout=60).returncode
                files = list((destination / source.name).rglob('*.bin'))
                verified = all(expected[path.relative_to(destination / source.name).as_posix()] == digest(path)
                               for path in files)
                result = {'binarySha256': before, 'binaryUnchanged': digest(Path(BINARY)) == before,
                          'deadlineSeconds': 90, 'elapsedSeconds': elapsed, 'timedOut': timed_out,
                          'exitCode': process.returncode, 'publishedFileCount': len(files),
                          'publishedFileHashesVerified': verified, 'expectedFiles': 201,
                          'tracedDiagnosticOnly': False, 'untracedDiagnosticOnly': True, 'fullTaskItemsQualified': False, 'cpuSamplingHz': 49, 'profileExitCode': profile_code, 'profileReportExitCode': report_code, 'rawStackDataKeptPrivateOnVM': True,
                          'releaseQualified': False, 'deliveryComplete': False}
            finally:
                stop_process(service)
                result['serviceOutput'] = drain.finish()
    (OUTPUT / 'diagnostic-result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
