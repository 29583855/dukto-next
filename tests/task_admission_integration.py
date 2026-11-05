"""日期：2026-11-05；真实 TLS 额度占用、主体轮转、等待控制/到期/撤权/重启及原任务恢复。"""

import argparse
from contextlib import closing
import json
from pathlib import Path
import queue
import shutil
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time
import uuid

from credential_rotation_integration import IndependentSession
from process_output import JsonOutputDrain
from service_integration import free_port, run
from proxy_pacing import ProxyPacer
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint, wait_state


class AdmissionBlocker(IndependentSession):
    # 日期：2026-11-05；独立协议客户端取得八通道许可后暂不发送清单，固定占用本测试自有的活动槽。
    def __init__(self, port, profile):
        super().__init__(port, profile)
        self.stopped = threading.Event()
        self.error = None
        self.worker = None
        kind, initial = self.request(32, {"share": "data", "path": "", "requestId": str(uuid.uuid4()),
                                         "manifest": {"sha256": "12" * 32}, "channels": "8", "queue": True})
        assert kind == 34 and initial["state"] == "queued"
        header = struct.unpack(">8sHHHHQII", self.exact(32))
        assert header[3] == 51 and header[5] == self.correlation and header[6] <= 65536
        admitted = json.loads(self.exact(header[6]))
        assert admitted == {"taskId": initial["taskId"], "needManifest": True, "channels": "8"}
        self.worker = threading.Thread(target=self.keep_alive, daemon=True)
        self.worker.start()

    # 日期：2026-11-05；只发送协议已有 busy 心跳，不刷新认证期限，不创建测试用旁路资源。
    def keep_alive(self):
        payload = b'{"state":"busy"}'
        frame = struct.pack(">8sHHHHQII", b"DKTNEXT1", 1, 0, 46, 0,
                            self.correlation, len(payload), 0) + payload
        try:
            while not self.stopped.wait(0.2):
                self.socket.sendall(frame)
        except OSError as error:
            if not self.stopped.is_set():
                self.error = type(error).__name__

    # 日期：2026-11-05；结束测试自有连接，允许服务端按网络中断清理持有的许可和任务执行锁。
    def close(self):
        self.stopped.set()
        if self.worker:
            self.worker.join(3)
            assert not self.worker.is_alive()
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        super().close()


class QueueProxy(SlowProxy):
    # 日期：2026-11-05；每通道 1 MiB/s 为公平顺序和中途暂停留下实际可观察窗口，不解密生产 TLS。
    def pump(self, source, destination):
        pacer = ProxyPacer()
        try:
            while not self.stopped.is_set():
                receiving = time.monotonic()
                data = source.recv(16384)
                received = time.monotonic()
                if not data or pacer.wait(self.stopped, len(data), 1024 * 1024, received - receiving):
                    break
                destination.sendall(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


# 日期：2026-11-05；等待真实客户端 queued 事件而非伪造任务，超时只保留最近十六条诊断。
def queued_task(operation):
    deadline = time.monotonic() + 20
    recent = []
    while time.monotonic() < deadline:
        event = operation.events.get(timeout=max(0.01, deadline - time.monotonic()))
        assert event is not None, recent
        recent = (recent + [event])[-16:]
        if event.get("state") == "queued":
            return event["taskId"]
    raise AssertionError(recent)


# 日期：2026-11-05；按原生进程最终事件检查完成和复用量，只有该有界测试的输出进入诊断数组。
def finished(operation):
    result = None
    restored = 0
    recent = []
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        event = operation.events.get(timeout=max(0.01, deadline - time.monotonic()))
        if event is None:
            break
        recent = (recent + [event])[-16:]
        if event.get("event") == "byte-progress":
            restored = max(restored, int(event["restoredBytes"]))
        if event.get("event") == "transfer-completed":
            result = event
    code = operation.process.wait(timeout=10)
    operation.reader.join(3)
    error = operation.process.stderr.read()
    assert code == 0 and not error and result and result["state"] == "completed", (code, error, recent)
    return result, restored


# 日期：2026-11-05；只读测试自有私有库，撤销后原主体不再能远程查询，不能为测试绕过生产权限。
def stored_state(server, task):
    path = server / "service/tasks.sqlite"
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as database:
        return database.execute("SELECT state FROM tasks WHERE id=?", (task,)).fetchone()[0]


# 日期：2026-11-05；所有进程、端口和资料均在独立临时目录，持续读取服务输出，不碰长时验证。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--old-executable")
    parser.add_argument("--mode", choices=("upload", "download", "mixed"), default="upload")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    script_sha, binary_sha = digest(Path(__file__)), digest(Path(executable))
    checks, results, drains = [], [], []
    with tempfile.TemporaryDirectory(prefix="dukto-admission-") as temporary:
        root = Path(temporary).resolve()
        server, shared = root / "server", root / "shared"
        shared.mkdir()
        source = root / "排队正文.bin"
        with source.open("wb") as output:
            for _ in range(64):
                output.write(bytes(range(256)) * 4096)
            output.write(b"fair admission tail")
        expected = digest(source)
        remote_source = "服务器正文.bin"
        shutil.copyfile(source, shared / remote_source)
        specifications = {}
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offers = [run(executable, server, ["serve", "pairing", *rights])[0] for _ in range(3)]
        port = free_port()
        proxy = QueueProxy(port)
        clients = [root / f"client-{index}" for index in range(3)]
        operations, blockers, service = [], [], None

        # 日期：2026-11-05；每次真实重启共用原状态、证书与端口，启动后持续排空输出。
        def start_service():
            process = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                        "--state-directory", str(server), "--timeout", "10", "--json"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            assert json.loads(process.stdout.readline())["event"] == "service-listening"
            process.drain = JsonOutputDrain(process.stdout)
            drains.append(process.drain)
            return process

        # 日期：2026-11-05；先退出服务再归档输出，读取器与 communicate 不竞争同一条标准输出管道。
        def stop_service(process):
            process.kill()
            process.wait(timeout=10)
            process.drain.finish()
            assert not process.stderr.read()

        # 日期：2026-11-05；双向使用相同全局队列；混合模式让 A 上传、B 下载，真实申请十六通道并校验降至八条。
        def begin(index, name):
            request = str(uuid.uuid4())
            direction = "download" if args.mode == "download" or (args.mode == "mixed" and index == 1) else "upload"
            if direction == "upload":
                (shared / name).mkdir()
                arguments = ["upload", "--path", str(source), "--remote-path", name]
                resume = ["--path", str(source)]
                final, receive = shared / name / source.name, server / "service"
            else:
                output = root / ("下载-" + name)
                output.mkdir()
                arguments = ["download", "--remote-path", remote_source, "--output", str(output)]
                resume = ["--output", str(output)]
                final, receive = output / remote_source, clients[index] / "transfers"
            specifications[name] = {"resume": resume, "final": final, "receive": receive, "direction": direction}
            operation = TransferProcess(executable, clients[index], [*arguments, "--share", "data",
                                        "--threads", "16", "--timeout", "3", "--request-id", request])
            operations.append(operation)
            return operation, queued_task(operation), request

        # 日期：2026-11-05；完成前必须观察服务实际授信，不能把十六通道请求当成十六通道已获准。
        def running(operation, task):
            admitted = None
            deadline = time.monotonic() + 30
            recent = []
            while time.monotonic() < deadline:
                event = operation.events.get(timeout=max(0.01, deadline - time.monotonic()))
                assert event is not None, recent
                recent = (recent + [event])[-16:]
                if event.get("event") == "transfer-admitted":
                    admitted = event
                if event.get("state") == "transferring":
                    assert event["taskId"] == task and admitted and admitted["taskId"] == task, recent
                    assert admitted["channels"] == "8", admitted
                    return task
            raise AssertionError(recent)

        # 日期：2026-11-05；独立摘要及目录条数验证双向落盘，不能只核对 completed 事件。
        def verify_final(name):
            final = specifications[name]["final"]
            assert digest(final) == expected and len(list(final.parent.iterdir())) == 1

        # 日期：2026-11-05；排队时不得进入正文扫描或接收清单，持久任务仍可由所属主体查询和控制。
        def assert_waiting(index, task):
            status, _ = run(executable, clients[index], ["task", "--task", task])
            assert status["state"] == "queued" and status["executionActive"], status
            assert not (server / f"service/manifest-{task}.sqlite").exists()
            return status

        try:
            service = start_service()
            paired = []
            for client, offer in zip(clients, offers):
                event, _ = run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                                   "--fingerprint", info["fingerprint"], "--credential-file", offer["credentialFile"]])
                paired.append(event)
            profile = json.loads((clients[0] / "clients/profile-default.json").read_text(encoding="utf-8"))
            blockers = [AdmissionBlocker(port, profile), AdmissionBlocker(port, profile)]
            # 日期：2026-11-05；未协商新等待阶段的对端繁忙时明确拒绝，不能绕过全局额度。
            with closing(IndependentSession(port, profile)) as old:
                kind, denied = old.request(32, {"share": "data", "path": "", "requestId": str(uuid.uuid4()),
                                                "manifest": {"sha256": "34" * 32}, "channels": "1"})
                assert kind == 7 and denied["code"] == 4 and denied["stage"] == "scheduler"
            a1, t1, r1 = begin(0, "a-first")
            a2, t2, r2 = begin(0, "a-second")
            a3, t3, _ = begin(0, "a-cancelled")
            b1, tb, rb = begin(1, "b-first")
            time.sleep(4)
            for index, task in ((0, t1), (0, t2), (0, t3), (1, tb)):
                assert_waiting(index, task)
            assert all(operation.process.poll() is None for operation in (a1, a2, a3, b1))
            run(executable, clients[1], ["task", "--task", t1], 4)
            run(executable, clients[0], ["cancel", "--task", t3])
            a3.finish()
            wait_state(executable, clients[0], t3, "cancelled")
            run(executable, clients[0], ["pause", "--task", t2])
            a2.finish()
            wait_state(executable, clients[0], t2, "paused")
            a2 = TransferProcess(executable, clients[0], ["resume", "--task", t2, *specifications["a-second"]["resume"], "--threads", "16"])
            operations.append(a2)
            assert queued_task(a2) == t2
            assert_waiting(0, t2)
            blockers.pop(0).close()
            assert running(a1, t1) == t1
            prefix_a = wait_checkpoint(specifications["a-first"]["receive"], t1)
            assert_waiting(0, t2)
            assert_waiting(1, tb)
            run(executable, clients[0], ["pause", "--task", t1])
            a1.finish()
            wait_state(executable, clients[0], t1, "paused")
            assert running(b1, tb) == tb
            prefix_b = wait_checkpoint(specifications["b-first"]["receive"], tb)
            assert_waiting(0, t2)
            run(executable, clients[1], ["pause", "--task", tb])
            b1.finish()
            wait_state(executable, clients[1], tb, "paused")
            assert running(a2, t2) == t2
            completed_a2, _ = finished(a2)
            assert completed_a2["taskId"] == t2 and completed_a2["requestId"] == r2
            verify_final("a-second")
            blockers.pop().close()
            for index, task, request, prefix, name in ((0, t1, r1, prefix_a, "a-first"), (1, tb, rb, prefix_b, "b-first")):
                operation = TransferProcess(executable, clients[index], ["resume", "--task", task,
                                             *specifications[name]["resume"], "--threads", "16"])
                operations.append(operation)
                completed, restored = finished(operation)
                assert completed["taskId"] == task and completed["requestId"] == request and restored >= prefix
                verify_final(name)
                results.append({"task": name, "direction": specifications[name]["direction"], "confirmedBeforePause": prefix, "restoredBytes": restored, "passed": True})
            checks.extend(["two active tasks and shared16 lanes", "old peer busy refusal", "queued > frame timeout with heartbeat",
                           "no queued scan/manifest", "queue cancel", "unbound queue pause/resume", "owner FIFO and round robin",
                           "other owner query refused", "same task/checkpoint restoration and SHA", "16 requested,8 actually granted"])

            if args.old_executable:
                (shared / "old-client").mkdir()
                legacy = transfer(str(Path(args.old_executable).resolve()), clients[0],
                                  ["upload", "--share", "data", "--path", str(source), "--remote-path", "old-client", "--threads", "4"])
                assert legacy["state"] == "completed" and digest(shared / "old-client" / source.name) == expected
                checks.append("actual pre-admission binary transfer compatibility")

            blockers = [AdmissionBlocker(port, profile), AdmissionBlocker(port, profile)]
            run(executable, server, ["serve", "session", "set", "--session-seconds", "2"])
            expired, task, _ = begin(2, "expiry")
            expired.finish()
            run(executable, server, ["serve", "session", "set", "--session-seconds", "86400"])
            wait_state(executable, clients[2], task, "interrupted")
            assert not (server / f"service/manifest-{task}.sqlite").exists()
            assert any(event.get("stage") == "session" for event in list(service.drain.recent))
            lost, task, _ = begin(1, "disconnect")
            lost.finish(kill=True)
            wait_state(executable, clients[1], task, "interrupted")
            revoked, task, _ = begin(2, "revoked")
            run(executable, server, ["serve", "revoke", "--client", paired[2]["client"]])
            revoked.finish()
            run(executable, clients[2], ["task", "--task", task], 4)
            assert stored_state(server, task) == "interrupted"
            restart, task, request = begin(1, "restart")
            assert_waiting(1, task)
            # 日期：2026-11-05；先停止服务确保等待任务没有得到许可，保留同资料与同请求跨真实进程重启恢复。
            stop_service(service)
            service = None
            assert not (server / f"service/manifest-{task}.sqlite").exists()
            for blocker in blockers:
                blocker.close()
            blockers.clear()
            restart.finish()
            service = start_service()
            wait_state(executable, clients[1], task, "interrupted")
            completed = transfer(executable, clients[1], ["resume", "--task", task, *specifications["restart"]["resume"], "--threads", "16"])
            assert completed["taskId"] == task and completed["requestId"] == request
            verify_final("restart")
            checks.extend(["queued expiry", "queued disconnect", "queued revocation", "queued process restart and same task recovery"])
        finally:
            for blocker in blockers:
                blocker.close()
            for operation in operations:
                if operation.process.poll() is None:
                    operation.process.kill()
                    operation.process.wait(timeout=10)
            if service and service.poll() is None:
                stop_service(service)
            proxy.close()
    report = {"date": "2026-11-05", "passed": True, "binarySha256": binary_sha, "scriptSha256": script_sha, "mode": args.mode,
              "checks": checks, "recovery": results, "payloadSha256": expected,
              "serverOutput": [drain.finish() for drain in drains],
              "scope": "real local TLS owner-round-robin start admission, before any scan/manifest; active work nonpreemptive,100 waiting structural cap separately unit tested; physical network, cross-process shared budgets and all platforms remain open"}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "checks": len(checks)}), flush=True)


if __name__ == "__main__":
    main()

