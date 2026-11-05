"""日期：2026-11-05；真实 TLS 断线后的有限自动重连、检查点复用及总时限专项。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

from process_output import JsonOutputDrain
from service_integration import free_port, run
from transfer_integration import digest
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint, wait_state


class ReconnectProxy(SlowProxy):
    # 日期：2026-11-05；持续接受重连，只切断测试拥有的当前 TLS 连接，正文不解密。
    def __init__(self, target):
        self.rate = 1024 * 1024
        super().__init__(target)

    # 日期：2026-11-05；冷传输限速到可见部分检查点，重连后仍为原始 TLS 字节转发。
    def pump(self, source, destination):
        try:
            while not self.stopped.is_set():
                data = source.recv(16384)
                if not data:
                    return
                if self.rate and self.stopped.wait(len(data) / self.rate):
                    return
                destination.sendall(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    # 日期：2026-11-05；只切断已经建立的连接，监听器继续运行供同进程自动重试。
    def cut(self):
        self.rate = 0
        for connection in tuple(self.sockets):
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


# 日期：2026-11-05；持续排空的进程事件逐条核对，只返回小型断言证据，不将正文读入内存。
def finish(operation, expected, timeout=120):
    code = operation.process.wait(timeout)
    operation.reader.join(3)
    events = []
    while not operation.events.empty():
        event = operation.events.get_nowait()
        if event:
            events.append(event)
    assert code == expected and not operation.process.stderr.read(), (code, events)
    assert events, code
    if expected == 0:
        assert events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed", events
    else:
        assert events[-1]["event"] == "error" and not any(event.get("event") == "transfer-completed" for event in events), events
    return events


# 日期：2026-11-05；私有测试资料直接写回既有 inode，保持生产权限检查且不把秘密写入报告。
def change_profile(path, update):
    value = json.loads(path.read_text(encoding="utf-8"))
    update(value)
    with path.open("w", encoding="utf-8", newline="\n") as output:
        json.dump(value, output)
    return value


# 日期：2026-11-05；六组真实双向断线复用、网络次数封顶、证书/授权错误与排队/正文期限均独立验证。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    # 日期：2026-11-05；包内运行保持 EXE 与依赖相邻，开发目录默认复制避免构建文件占用。
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--case-deadline-seconds", type=int, default=120)
    parser.add_argument("--case-exit-timeout", type=int, default=120)
    parser.add_argument("--ready-timeout", type=int, default=30)
    args = parser.parse_args()
    assert 10 <= args.case_deadline_seconds <= 600 and 10 <= args.case_exit_timeout <= 660
    assert 1 <= args.ready_timeout <= 180
    timing = {"caseDeadlineSeconds": args.case_deadline_seconds,
              "caseExitBudgetSeconds": args.case_exit_timeout, "readyBudgetSeconds": args.ready_timeout}
    print(json.dumps({"kind": "retry-test-configuration", **timing}), flush=True)
    executable = str(Path(args.executable).resolve())
    executable_sha = digest(Path(executable))
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-auto-retry-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt" and not args.in_place:
            local = root / "dukto-cli.exe"
            shutil.copyfile(executable, local)
            executable = str(local)
        state, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        source = root / "body.bin"
        with source.open("wb") as output:
            for index in range(128):
                output.write(bytes([index]) * (1024 * 1024))
            output.write(b"bounded-retry-tail")
        expected_sha = digest(source)
        with (shared / "deadline-body.bin").open("wb") as output:
            for index in range(8):
                output.write(bytes([index]) * (1024 * 1024))
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, state, ["serve", "pairing", *rights])
        port = free_port()
        service = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state),
                                    "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        drain = JsonOutputDrain(service.stdout)
        proxy = ReconnectProxy(port)
        active = []
        try:
            deadline = time.monotonic() + 15
            while not drain.events.get("service-listening"):
                assert service.poll() is None and time.monotonic() < deadline, list(drain.recent)
                time.sleep(0.01)
            run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}", "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels in (1, 4, 16):
                for direction in ("upload", "download"):
                    key = f"{direction}-{channels}"
                    remote = shared / key
                    remote.mkdir()
                    destination = remote if direction == "upload" else root / key
                    destination.mkdir(exist_ok=True)
                    if direction == "download":
                        shutil.copyfile(source, remote / source.name)
                    original = destination / source.name
                    original.write_bytes(b"original user content")
                    original_sha = digest(original)
                    request = str(uuid.uuid4())
                    arguments = [direction, "--share", "data", "--threads", str(channels), "--request-id", request,
                                 "--retries", "3", "--deadline-seconds", str(args.case_deadline_seconds)]
                    arguments += (["--path", str(source), "--remote-path", key] if direction == "upload" else
                                  ["--remote-path", key + "/body.bin", "--output", str(destination)])
                    proxy.rate = 1024 * 1024
                    operation = TransferProcess(executable, client, arguments)
                    active.append(operation)
                    task = operation.task(args.ready_timeout)
                    local_state = state / "service" if direction == "upload" else client / "transfers"
                    confirmed = wait_checkpoint(local_state, task)
                    assert 0 < confirmed < source.stat().st_size and not (destination / "body (2).bin").exists()
                    proxy.cut()
                    events = finish(operation, 0, args.case_exit_timeout)
                    result = events[-1]
                    assert result["taskId"] == task and result["requestId"] == request
                    retried = [event for event in events if event.get("event") == "transfer-retrying"]
                    assert 1 <= len(retried) <= 3 and retried[0]["retry"] == 1, events
                    reused = max(int(event.get("restoredBytes", "0")) for event in events)
                    assert reused >= confirmed, (reused, confirmed, events)
                    assert digest(destination / "body (2).bin") == expected_sha and digest(original) == original_sha
                    assert sorted(path.name for path in destination.iterdir() if not path.name.startswith(".")) == ["body (2).bin", "body.bin"]
                    status, _ = run(executable, client, ["task", "--task", task])
                    assert status["state"] == "completed" and not status["executionActive"]
                    cases.append({"direction": direction, "channels": channels, "taskId": task, "requestId": request,
                                  "checkpoint": confirmed, "restoredBytes": reused, "retries": len(retried),
                                  "sha256": expected_sha, "sameTask": True, "noDuplicate": True})
                    print(json.dumps(cases[-1]), flush=True)
            profile = client / "clients/profile-default.json"
            original_profile = profile.read_bytes()
            try:
                change_profile(profile, lambda value: value.update(port=str(free_port())))
                operation = TransferProcess(executable, client, ["download", "--share", "data", "--output", str(root),
                                                                 "--retries", "3", "--timeout", "1", "--deadline-seconds", "15"])
                active.append(operation)
                events = finish(operation, 3, 20)
                retries = [event for event in events if event.get("event") == "transfer-retrying"]
                assert [event["retry"] for event in retries] == [1, 2, 3]
                assert events[-1]["stage"] != "deadline"
                cases.append({"kind": "connection-refused", "retries": 3, "delaysMs": [event["delayMs"] for event in retries]})
            finally:
                profile.write_bytes(original_profile)
            try:
                change_profile(profile, lambda value: value.update(fingerprint="00" * 32))
                operation = TransferProcess(executable, client, ["download", "--share", "data", "--output", str(root), "--retries", "3"])
                active.append(operation)
                events = finish(operation, 4, 15)
                assert not any(event.get("event") == "transfer-retrying" for event in events)
                cases.append({"kind": "wrong-certificate", "retries": 0, "exitCode": 4})
            finally:
                profile.write_bytes(original_profile)
            operation = TransferProcess(executable, client, ["download", "--share", "denied", "--output", str(root), "--retries", "3"])
            active.append(operation)
            events = finish(operation, 4, 15)
            assert not any(event.get("event") == "transfer-retrying" for event in events)
            cases.append({"kind": "permission-denied", "retries": 0, "exitCode": 4})
            for stop in ("pause", "cancel"):
                proxy.rate = 1024 * 1024
                destination = root / ("remote-" + stop)
                destination.mkdir()
                operation = TransferProcess(executable, client, ["download", "--share", "data", "--remote-path", "download-1/body.bin",
                                                                 "--output", str(destination), "--threads", "4", "--retries", "3"])
                active.append(operation)
                task = operation.task()
                checkpoint = wait_checkpoint(client / "transfers", task)
                run(executable, client, [stop, "--task", task])
                events = finish(operation, 7, 15)
                expected_state = "paused" if stop == "pause" else "cancelled"
                status = wait_state(executable, client, task, expected_state)
                assert not (destination / "body.bin").exists() and status["state"] == expected_state
                assert not any(event.get("event") == "transfer-completed" for event in events)
                if stop == "pause":
                    repeated = TransferProcess(executable, client, ["download", "--share", "data", "--remote-path", "download-1/body.bin",
                                                                    "--output", str(destination), "--request-id", status["requestId"], "--retries", "3"])
                    active.append(repeated)
                    finish(repeated, 7, 10)
                    assert wait_state(executable, client, task, "paused")["state"] == "paused"
                cases.append({"kind": "remote-" + stop, "taskId": task, "state": expected_state,
                              "checkpoint": checkpoint, "exitCode": 7, "automaticRestartPrevented": True})
            proxy.rate = 64 * 1024
            for index in range(2):
                destination = root / f"holder-{index}"
                destination.mkdir()
                operation = TransferProcess(executable, client, ["download", "--share", "data", "--remote-path", "download-1/body.bin",
                                                                 "--output", str(destination), "--deadline-seconds", "30"])
                active.append(operation)
                operation.task(15)
            destination = root / "queued-deadline"
            destination.mkdir()
            started = time.monotonic()
            operation = TransferProcess(executable, client, ["download", "--share", "data", "--remote-path", "download-1/body.bin",
                                                             "--output", str(destination), "--retries", "3", "--deadline-seconds", "1"])
            active.append(operation)
            events = finish(operation, 3, 5)
            elapsed = time.monotonic() - started
            assert events[-1]["stage"] == "deadline" and elapsed < 4
            assert any(event.get("state") == "queued" for event in events)
            assert not any(event.get("event") == "transfer-retrying" for event in events)
            assert not list(destination.iterdir())
            cases.append({"kind": "queue-deadline", "seconds": round(elapsed, 3), "exitCode": 3, "retries": 0})
            for operation in active:
                if operation.process.poll() is None:
                    operation.process.kill()
                    operation.process.wait(10)
            active.clear()
            # 日期：2026-11-05；确认占位任务实际退出后再验证正文期限，不把再次排队误算为传输中断。
            time.sleep(0.4)
            destination = root / "body-deadline"
            destination.mkdir()
            operation = TransferProcess(executable, client, ["download", "--share", "data", "--remote-path", "deadline-body.bin",
                                                             "--output", str(destination), "--retries", "3", "--deadline-seconds", "3"])
            active.append(operation)
            task = operation.task(5)
            events = finish(operation, 3, 5)
            assert events[-1]["stage"] == "deadline" and not (destination / "deadline-body.bin").exists()
            assert not any(event.get("event") == "transfer-retrying" for event in events)
            cases.append({"kind": "body-deadline", "taskId": task, "exitCode": 3, "retries": 0})
            # 日期：2026-11-05；规范参数失败保留明确码 2，其他命令不能静默接受传输专用策略。
            for arguments in (["auth", "--retries", "0"], ["download", "--retries", "4"],
                              ["download", "--deadline-seconds", "0"], ["download", "--retries", "01"],
                              ["download", "--retries", "1", "--retries", "2"]):
                operation = TransferProcess(executable, client, arguments)
                active.append(operation)
                events = finish(operation, 2, 5)
                assert not any(event.get("event") == "transfer-retrying" for event in events)
            cases.append({"kind": "invalid-options", "cases": 5, "exitCode": 2})
        finally:
            for operation in active:
                if operation.process.poll() is None:
                    operation.process.kill()
                    operation.process.wait(10)
            proxy.close()
            if service.poll() is None:
                service.kill()
                service.wait(10)
            drain.finish()
            assert not service.stderr.read(), list(drain.recent)
    report = {"date": "2026-11-05", "passed": True, "executableSha256": executable_sha,
              "scriptSha256": digest(Path(__file__)), "inPlaceRequested": args.in_place, "cases": cases,
              "timingConfiguration": timing,
              "defaultTimingGatesPassed": (args.case_deadline_seconds, args.case_exit_timeout, args.ready_timeout) == (120, 120, 30),
              "scope": "loopback TLS fault proxy; no physical LAN or uninterruptible OS-call hard deadline claim"}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "cases": len(cases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
