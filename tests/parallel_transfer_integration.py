"""日期：2026-11-04；独立进程与不透明限速 TLS 代理核对真实并发通道、耗时及双端摘要。"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import shutil
import subprocess
import tempfile
import time
import uuid

import psutil

from service_integration import free_port, run
from process_output import JsonOutputDrain
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess


# 日期：2026-11-05；Linux 退出与 waitpid 可短暂错开，仅在有界等待确认退出后忽略 fd 枚举竞态。
def sample(process, peak):
    try:
        item = psutil.Process(process.pid)
        memory = item.memory_info()
        peak["rss"] = max(peak["rss"], memory.rss)
        peak["threads"] = max(peak["threads"], item.num_threads())
        resources = item.num_handles() if os.name == "nt" else item.num_fds()
        peak["handlesOrFds"] = max(peak["handlesOrFds"], resources)
    except psutil.NoSuchProcess:
        pass
    except psutil.AccessDenied as error:
        try:
            process.wait(timeout=0.1)
        except subprocess.TimeoutExpired:
            raise error


# 日期：2026-11-05；完整命令耗时包含扫描和收尾；超时明确报告进度和服务存活，不能丢弃失败。
def measured(executable, state, arguments, server, receive_state, timeout=120):
    started = time.monotonic()
    operation = TransferProcess(executable, state, arguments)
    task = operation.task()
    log = receive_state / f"receive-{task}.sqlite"
    overlap = False
    next_probe = 0
    peaks = {name: {"rss": 0, "threads": 0, "handlesOrFds": 0} for name in ("client", "server")}
    try:
        deadline = started + timeout
        while operation.process.poll() is None:
            assert time.monotonic() < deadline, ("parallel transfer exceeded deadline", arguments,
                                                peaks, server.poll(), log.exists())
            sample(operation.process, peaks["client"])
            sample(server, peaks["server"])
            if not overlap and time.monotonic() >= next_probe and log.exists():
                # 日期：2026-11-04；多个 receiving 文件同时有持久字节证明真实跨文件并行，不靠线程数推断。
                next_probe = time.monotonic() + 0.1
                try:
                    with closing(sqlite3.connect(f"{log.as_uri()}?mode=ro", uri=True, timeout=0.01)) as database:
                        overlap = database.execute("SELECT COUNT(*) FROM files WHERE state='receiving' AND confirmed>0").fetchone()[0] > 1
                except sqlite3.OperationalError:
                    pass
            time.sleep(0.025)
        operation.reader.join(3)
        error = operation.process.stderr.read()
        events = []
        while not operation.events.empty():
            value = operation.events.get_nowait()
            if value:
                events.append(value)
        assert operation.process.returncode == 0 and not error, (operation.process.returncode, error, events)
        assert events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed", events
        assert not any("token" in event or "parallel" in event or "credential" in event for event in events)
        return events[-1], round(time.monotonic() - started, 3), peaks, overlap
    finally:
        if operation.process.poll() is None:
            operation.process.kill()
            operation.process.wait(10)


# 日期：2026-11-05；五档双向核对真实文件，同时记录二进制/脚本身份及持续排空的服务输出计数。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--task-timeout", type=int, default=120)
    parser.add_argument("--channels", type=int, nargs="+", choices=(1, 2, 4, 8, 16), default=(1, 2, 4, 8, 16))
    args = parser.parse_args()
    assert 30 <= args.task_timeout <= 1800
    executable = str(Path(args.executable).resolve())
    binary_hash = hashlib.sha256(Path(executable).read_bytes()).hexdigest()
    script_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    helper_hash = hashlib.sha256(Path(__file__).with_name("process_output.py").read_bytes()).hexdigest()
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-parallel-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt":
            # 日期：2026-11-04；运行自有二进制副本，验证期间仍可构建下一份源码。
            local_executable = root / "dukto-cli.exe"
            shutil.copyfile(executable, local_executable)
            executable = str(local_executable)
        server_state, client_state = root / "server", root / "client"
        shared, bundle = root / "shared", root / "资料集"
        shared.mkdir()
        (bundle / "空目录").mkdir(parents=True)
        (bundle / "empty").touch()
        (bundle / "note.txt").write_text("并行块与中文目录\n", encoding="utf-8")
        payload = bundle / "large.bin"
        with payload.open("wb") as output:
            for block in range(256):
                output.write(bytes([block % 251]) * (256 * 1024))
            output.write(b"tail" * 9 + b"!")
        expected = digest(payload)
        for index in range(4):
            (bundle / f"small-{index}.bin").write_bytes(bytes([index + 1]) * (256 * 1024))
        expected_files = {path.name: digest(path) for path in bundle.iterdir() if path.is_file()}
        total_bytes = sum(path.stat().st_size for path in bundle.iterdir() if path.is_file())
        info, _ = run(executable, server_state, ["serve", "init", "--server-name", "127.0.0.1"])
        run(executable, server_state, ["serve", "share", "add", "--share", "data", "--path", str(shared),
                                       "--allow-browse", "--allow-upload", "--allow-download"])
        offer, _ = run(executable, server_state, ["serve", "pairing", "--share", "data", "--allow-browse",
                                                 "--allow-upload", "--allow-download"])
        port = free_port()
        server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(server_state),
                                   "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        proxy = SlowProxy(port)
        server_output = None
        try:
            assert json.loads(server.stdout.readline())["event"] == "service-listening"
            server_output = JsonOutputDrain(server.stdout)
            run(executable, client_state, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                           "--fingerprint", info["fingerprint"],
                                           "--credential-file", offer["credentialFile"]])
            for channels in args.channels:
                destination = shared / f"channels-{channels}"
                destination.mkdir()
                upload_request = str(uuid.uuid4())
                upload = ["upload", "--share", "data", "--path", str(bundle), "--remote-path", destination.name,
                          "--request-id", upload_request, "--threads", str(channels)]
                sent, seconds, peaks, overlap = measured(executable, client_state, upload, server, server_state / "service", args.task_timeout)
                assert sent["channels"] == str(channels), sent
                assert digest(destination / bundle.name / payload.name) == expected
                assert all(digest(destination / bundle.name / name) == sha for name, sha in expected_files.items())
                if channels > 1:
                    assert overlap, "multiple file checkpoints did not overlap"
                cases.append({"direction": "upload", "channels": channels, "seconds": seconds, "peaks": peaks,
                              "MiBPerSecond": round(total_bytes / 1048576 / seconds, 3), "overlappingFileCheckpoints": overlap, "passed": True})
                print(json.dumps(cases[-1]), flush=True)
                output = root / f"download-{channels}"
                output.mkdir()
                download_request = str(uuid.uuid4())
                download = ["download", "--share", "data", "--remote-path", destination.name + "/" + bundle.name,
                            "--output", str(output), "--request-id", download_request, "--threads", str(channels)]
                received, seconds, peaks, overlap = measured(executable, client_state, download, server, client_state / "transfers", args.task_timeout)
                assert received["channels"] == str(channels), received
                assert digest(output / bundle.name / payload.name) == expected
                assert all(digest(output / bundle.name / name) == sha for name, sha in expected_files.items())
                if channels > 1:
                    assert overlap, "multiple file checkpoints did not overlap"
                assert (output / bundle.name / "空目录").is_dir()
                assert (output / bundle.name / "empty").stat().st_size == 0
                assert (output / bundle.name / "note.txt").read_bytes() == (bundle / "note.txt").read_bytes()
                cases.append({"direction": "download", "channels": channels, "seconds": seconds, "peaks": peaks,
                              "MiBPerSecond": round(total_bytes / 1048576 / seconds, 3), "overlappingFileCheckpoints": overlap, "passed": True})
                print(json.dumps(cases[-1]), flush=True)
            repeated = transfer(executable, client_state, [*download, "--threads", "2"])
            assert repeated["taskId"] == received["taskId"]
            assert list(output.iterdir()) == [output / bundle.name]
            assert digest(output / bundle.name / payload.name) == expected
            run(executable, client_state, ["upload", "--share", "data", "--path", str(payload), "--threads", "3"], 2)
            run(executable, client_state, ["download", "--share", "data", "--output", str(output), "--threads", "0"], 2)
        finally:
            proxy.close()
            if server.poll() is None:
                server.kill() if os.name == "nt" else server.send_signal(signal.SIGTERM)
            server.wait(timeout=15)
            if server_output:
                server_output.finish()
            error = server.stderr.read()
            assert not error, error
        report = {"date": "2026-11-04", "passed": True, "payloadBytes": payload.stat().st_size,
                  "binarySha256": binary_hash, "scriptSha256": script_hash, "outputHelperSha256": helper_hash,
                  "serverOutput": {"bytes": server_output.bytes, "events": dict(server_output.events)},
                  "channelsTested": list(args.channels), "taskTimeoutSeconds": args.task_timeout,
                  "payloadSha256": expected, "totalBytes": total_bytes, "cases": cases,
                  "scope": "local opaque TLS proxy requests 4MiB/s per connection; timer granularity may reduce actual rate; complete command timings; not physical LAN performance",
                  "open": ["fair allocation between tasks and complete budget/resource verification", "extended fault offsets and platform matrix"]}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
