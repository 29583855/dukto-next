"""日期：2026-11-04；限速真实 TLS 链路，独立进程验证公共任务控制及重启恢复。"""

import argparse
from contextlib import closing
import json
import math
import os
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

from service_integration import free_port, run
from proxy_pacing import ProxyPacer
from process_output import JsonOutputDrain
from transfer_integration import digest, transfer


class SlowProxy:
    # 日期：2026-11-04；只代理本测试回环端口，每条连接双向限速，TLS 内容保持不透明。
    def __init__(self, target):
        self.target = target
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.listener.settimeout(0.2)
        self.port = self.listener.getsockname()[1]
        self.stopped = threading.Event()
        self.threads = []
        self.sockets = []
        self.worker = threading.Thread(target=self.accept, daemon=True)
        self.worker.start()

    # 日期：2026-11-04；每条测试连接独立转发，控制连接不会排在大文件之后。
    def accept(self):
        while not self.stopped.is_set():
            try:
                client, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            try:
                server = socket.create_connection(("127.0.0.1", self.target), timeout=3)
                server.settimeout(None)
                for connection in (client, server):
                    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sockets.extend((client, server))
                for source, destination in ((client, server), (server, client)):
                    worker = threading.Thread(target=self.pump, args=(source, destination), daemon=True)
                    self.threads.append(worker)
                    worker.start()
            except OSError:
                client.close()

    # 日期：2026-11-05；原4MiB/s改用单调期限补偿超睡，固定片段和取消检查保持。
    def pump(self, source, destination):
        pacer = ProxyPacer()
        try:
            while not self.stopped.is_set():
                receiving = time.monotonic()
                data = source.recv(16384)
                received = time.monotonic()
                if not data or pacer.wait(self.stopped, len(data), 4 * 1024 * 1024, received - receiving):
                    break
                destination.sendall(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    # 日期：2026-11-04；清理仅关闭测试自有套接字和线程，不影响工程长时测试进程。
    def close(self):
        self.stopped.set()
        self.listener.close()
        self.worker.join(3)
        for connection in self.sockets:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()
        for worker in self.threads:
            worker.join(3)


class TransferProcess:
    # 日期：2026-11-04；异步逐行读取客户端事件，避免管道占满，也不在内存积累数据正文。
    def __init__(self, executable, state, arguments):
        self.events = queue.Queue()
        self.process = subprocess.Popen([executable, *arguments, "--state-directory", str(state), "--json"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    # 日期：2026-11-04；测试样本仅少量事件，结束哨兵允许明确判断进程提前退出。
    def read(self):
        for line in self.process.stdout:
            self.events.put(json.loads(line))
        self.events.put(None)

    # 日期：2026-11-05；就绪等待独立于暂停时限；慢 CPU 的强清单扫描允许调用方显式增加预算，超时保留有界诊断。
    def task(self, timeout=30):
        deadline = time.monotonic() + timeout
        recent = []
        while True:
            try:
                event = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
            except queue.Empty as error:
                raise AssertionError(("transfer ready deadline", timeout, self.process.poll(), recent)) from error
            assert event is not None, ("transfer exited before ready", self.process.poll(), recent)
            recent = (recent + [event])[-16:]
            if event.get("state") == "transferring":
                return event["taskId"]

    # 日期：2026-11-04；强制退出只作用于本测试创建的客户端，并验证没有伪造批次完成事件。
    def finish(self, kill=False):
        if kill and self.process.poll() is None:
            self.process.kill()
        code = self.process.wait(timeout=20)
        self.reader.join(3)
        error = self.process.stderr.read()
        remaining = []
        while not self.events.empty():
            remaining.append(self.events.get_nowait())
        assert not error and code != 0, (code, error, remaining)
        assert not any(event and event.get("event") == "transfer-completed" for event in remaining)
        return code


# 日期：2026-11-04；读取所有文件实际已同步字节总量，支持非前缀块与指定故障比例，不依赖 UI 进度。
def wait_checkpoint(state, task, minimum=4 * 1024 * 1024):
    log = state / f"receive-{task}.sqlite"
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if log.exists():
            try:
                with closing(sqlite3.connect(f"{log.as_uri()}?mode=ro", uri=True, timeout=0.1)) as database:
                    row = database.execute("SELECT SUM(confirmed) FROM files").fetchone()
                    if row and row[0] and row[0] >= minimum:
                        return row[0]
            except sqlite3.OperationalError:
                pass
        time.sleep(0.03)
    raise AssertionError("no durable checkpoint")


# 日期：2026-11-04；实际状态由工作者或取得空闲租约的控制连接确认，控制请求不冒充已经暂停。
def wait_state(executable, state, task, expected):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result, _ = run(executable, state, ["task", "--task", task])
        if result["state"] == expected and not result["executionActive"]:
            return result
        time.sleep(0.05)
    raise AssertionError(result)


# 日期：2026-11-05；隔离真实故障与恢复，服务输出持续排空，不能让测试管道伪造管理连接超时。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--on-conflict", choices=("rename", "fail"), default="rename")
    # 日期：2026-11-05；实际部署包运行原 EXE 保持 DLL 相邻，开发验证默认仍使用独立副本。
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--resume-threads", type=int)
    parser.add_argument("--checkpoint-percent", type=int, default=0, choices=range(0, 100))
    parser.add_argument("--files", type=int, default=1)
    parser.add_argument("--payload-mib", type=int, default=24)
    parser.add_argument("--resume-timeout", type=int, default=90)
    parser.add_argument("--ready-timeout", type=int, default=30)
    args = parser.parse_args()
    assert 1 <= args.resume_timeout <= 600 and 1 <= args.ready_timeout <= 300
    assert 1 <= args.files <= 64 and 4 <= args.payload_mib <= 256
    executable = str(Path(args.executable).resolve())
    cases = []
    binary_sha, script_sha = digest(Path(executable)), digest(Path(__file__))
    with tempfile.TemporaryDirectory(prefix="dukto-recovery-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt" and not args.in_place:
            # 日期：2026-11-05；开发程序副本支持继续构建；仅显式包内测试关闭复制，DLL 搜索路径不放宽。
            local_executable = root / "dukto-cli.exe"
            shutil.copyfile(executable, local_executable)
            executable = str(local_executable)
        server_state, client_state = root / "server", root / "client"
        shared = root / "shared"
        shared.mkdir()
        source = root / ("payload.bin" if args.files == 1 else "资料集")
        if args.files > 1:
            source.mkdir()
            (source / "空目录").mkdir()
            (source / "empty").touch()
        samples = [source] if args.files == 1 else [source / f"file-{index:02}.bin" for index in range(args.files)]
        for index, sample in enumerate(samples):
            with sample.open("wb") as output:
                for _ in range(args.payload_mib * 4):
                    output.write(bytes([index + 1]) * (256 * 1024))
                output.write(b"tail")
        expected_files = {sample.name: digest(sample) for sample in samples}
        expected = expected_files[samples[0].name]
        total_bytes = sum(sample.stat().st_size for sample in samples)
        checkpoint = max(4 * 1024 * 1024, math.ceil(total_bytes * args.checkpoint_percent / 100))
        remote_name = "remote.bin" if args.files == 1 else source.name
        if args.files == 1:
            shutil.copyfile(source, shared / remote_name)
        else:
            shutil.copytree(source, shared / remote_name)
        info, _ = run(executable, server_state, ["serve", "init", "--server-name", "127.0.0.1"])
        run(executable, server_state, ["serve", "share", "add", "--share", "data", "--path", str(shared),
                                      "--allow-browse", "--allow-download", "--allow-upload"])
        offer, _ = run(executable, server_state, ["serve", "pairing", "--share", "data", "--allow-browse",
                                                "--allow-download", "--allow-upload"])
        port = free_port()
        proxy = SlowProxy(port)
        process = None
        active = None
        server_outputs = []

        # 日期：2026-11-05；重启沿用身份/目录/端口，监听后持续读取故障关闭事件并保持有界内存。
        def start_server():
            service = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                        "--state-directory", str(server_state), "--timeout", "10", "--json"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            assert json.loads(service.stdout.readline())["event"] == "service-listening"
            service.output_drain = JsonOutputDrain(service.stdout)
            server_outputs.append(service.output_drain)
            return service

        # 日期：2026-11-05；stdout 只由读取器消费，不能与 communicate 竞争；标准错误仍严格核对。
        def finish_server(service):
            service.wait(timeout=10)
            service.output_drain.finish()
            error = service.stderr.read()
            assert not error, error

        try:
            process = start_server()
            paired, _ = run(executable, client_state, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                                       "--fingerprint", info["fingerprint"],
                                                       "--credential-file", offer["credentialFile"]])
            for direction, fault in (("upload", "pause"), ("download", "pause"),
                                     ("upload", "kill-client"), ("download", "kill-client"),
                                     ("upload", "kill-server"), ("download", "kill-server"),
                                     ("upload", "cancel"), ("download", "cancel")):
                request = str(uuid.uuid4())
                output = root / (direction + "-" + fault)
                output.mkdir()
                if direction == "upload":
                    # 日期：2026-11-04；各用例独立共享目标，避免取消保留项影响另一用例的同名判定。
                    (shared / output.name).mkdir()
                    arguments = ["upload", "--share", "data", "--path", str(source),
                                 "--remote-path", output.name, "--request-id", request]
                    resume_arguments = ["--path", str(source)]
                    receive_state = server_state / "service"
                    final = shared / output.name / source.name
                else:
                    arguments = ["download", "--share", "data", "--remote-path", remote_name,
                                 "--output", str(output), "--request-id", request]
                    resume_arguments = ["--output", str(output)]
                    receive_state = client_state / "transfers"
                    final = output / remote_name
                # 日期：2026-11-05；显式非默认策略只用于首次创建，恢复不能靠测试重复传参补救策略丢失。
                arguments += ["--threads", str(args.threads)]
                if args.on_conflict != "rename":
                    arguments += ["--on-conflict", args.on_conflict]
                resume_arguments += ["--threads", str(args.resume_threads or args.threads)]
                active = TransferProcess(executable, client_state, arguments)
                task = active.task(args.ready_timeout)
                prefix = wait_checkpoint(receive_state, task, checkpoint)
                if fault in ("pause", "cancel"):
                    pending, _ = run(executable, client_state, [fault, "--task", task])
                    assert pending["desired"] == fault or pending["state"] == fault + ("d" if fault == "pause" else "led"), pending
                    active.finish()
                    status = wait_state(executable, client_state, task, "paused" if fault == "pause" else "cancelled")
                elif fault == "kill-client":
                    active.finish(kill=True)
                    status = wait_state(executable, client_state, task, "interrupted")
                else:
                    process.kill()
                    finish_server(process)
                    active.finish()
                    process = start_server()
                    status = wait_state(executable, client_state, task, "interrupted")
                active = None
                assert not status["executionActive"], status
                assert status.get("conflict", "rename") == args.on_conflict, status
                if args.files == 1:
                    assert not final.exists(), status
                resume_seconds = None
                if fault == "cancel":
                    transfer(executable, client_state, ["resume", "--task", task, *resume_arguments], 2)
                    status, _ = run(executable, client_state, ["task", "--task", task])
                    assert status["state"] == "cancelled"
                else:
                    resume_started = time.monotonic()
                    completed = transfer(executable, client_state, ["resume", "--task", task, *resume_arguments], timeout=args.resume_timeout)
                    resume_seconds = round(time.monotonic() - resume_started, 3)
                    assert completed["taskId"] == task and completed["requestId"] == request
                    assert completed.get("conflict", "rename") == args.on_conflict, completed
                    if args.files == 1:
                        assert digest(final) == expected
                    else:
                        assert all(digest(final / name) == sha for name, sha in expected_files.items())
                        assert (final / "空目录").is_dir() and (final / "empty").stat().st_size == 0
                        assert {path.name for path in final.iterdir()} == set(expected_files) | {"empty", "空目录"}
                    assert len(list(final.parent.iterdir())) == 1
                    status, _ = run(executable, client_state, ["task", "--task", task])
                    assert status["state"] == "completed" and not status["executionActive"]
                cases.append({"direction": direction, "fault": fault, "confirmedBeforeFault": prefix,
                              "finalState": status["state"], "resumeSeconds": resume_seconds, "passed": True})
                print(f"{direction}/{fault}: passed", flush=True)
            # 日期：2026-11-04；另一个真实配对主体不能查询已知的任务 UUID，撤权也阻止原主体查询。
            other_offer, _ = run(executable, server_state, ["serve", "pairing", "--share", "data", "--allow-download"])
            run(executable, root / "other", ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                             "--fingerprint", info["fingerprint"], "--credential-file", other_offer["credentialFile"]])
            run(executable, root / "other", ["task", "--task", task], 4)
            run(executable, server_state, ["serve", "grant", "--client", paired["client"], "--share", "data", "--allow-browse"])
            run(executable, client_state, ["task", "--task", task], 4)
        finally:
            try:
                if active and active.process.poll() is None:
                    active.process.kill()
                    active.process.wait(timeout=10)
            finally:
                try:
                    if process and process.poll() is None:
                        process.kill()
                        finish_server(process)
                finally:
                    proxy.close()
    report = {"date": "2026-11-05", "passed": True, "payloadBytes": total_bytes,
              "binarySha256": binary_sha, "inPlaceExecution": args.in_place, "scriptSha256": script_sha,
              "resumeBudgetSeconds": args.resume_timeout, "readyBudgetSeconds": args.ready_timeout,
              "defaultTimingGatesPassed": args.resume_timeout == 90 and args.ready_timeout == 30,
              "payloadSha256": expected, "cases": cases, "foreignOwnerRefused": True, "revokedQueryRefused": True,
              "conflictPolicy": args.on_conflict, "channelsRequested": args.threads, "resumeChannelsRequested": args.resume_threads or args.threads,
              "regularFiles": args.files, "checkpointPercentRequested": args.checkpoint_percent,
              "serverOutput": [output.finish() for output in server_outputs],
              "fileSha256": expected_files,
              "scope": "public CLI with selected channels and requested durable-byte threshold; process faults, actual pause/cancel/resume; power loss and arbitrary instruction offsets require further validation"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_bytes(text.encode("utf-8"))
    print(text)


if __name__ == "__main__":
    main()
