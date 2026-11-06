"""日期：2026-11-05；真实多主体竞争 16 数据槽，控制隔离和连续任务后的空闲资源回落验证。"""

import argparse
from collections import deque
import json
import os
from pathlib import Path
import shutil
import socket
import threading
import subprocess
import tempfile
import time

from idle_resources import idle_sample

from process_output import JsonOutputDrain
from service_integration import free_port, run
from proxy_pacing import ProxyPacer
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint, wait_state


class HeldUploadProxy(SlowProxy):
    # 日期：2026-11-05；每条 TLS 连接先通过 8 MiB 再限为 512 KiB/s；每个 4 MiB 块仍可在默认帧期限内确认。
    def __init__(self, target):
        self.released = threading.Event()
        self.held = 0
        self.held_lock = threading.Lock()
        super().__init__(target)

    # 日期：2026-11-05；只控制本测试代理流量；正文先有真实持久块，认证/查询/暂停短连接不触及阈值。
    def pump(self, source, destination):
        pacer = ProxyPacer()
        forwarded = 0
        holding = False
        try:
            while not self.stopped.is_set():
                receiving = time.monotonic()
                data = source.recv(16384)
                received = time.monotonic()
                if not data:
                    break
                if forwarded >= 8 * 1024 * 1024 and not self.released.is_set():
                    if not holding:
                        with self.held_lock:
                            self.held += 1
                        holding = True
                # 日期：2026-11-05；保持原512KiB/s与4MiB/s两个等待的合成速率，释放后恢复原4MiB/s。
                rate = (4 * 1024 * 1024) / 9 if holding and not self.released.is_set() else 4 * 1024 * 1024
                if pacer.wait(self.stopped, len(data), rate, received - receiving):
                    break
                destination.sendall(data)
                forwarded += len(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    # 日期：2026-11-05；检查确实进入保持且工作进程仍活；失败诊断给出真实状态，不容许已完成冒充资源占用。
    def assert_held(self, operation, executable, client, task, timeout):
        deadline = time.monotonic() + timeout
        while not self.held and time.monotonic() < deadline and operation.process.poll() is None:
            time.sleep(0.02)
        status, _ = run(executable, client, ["task", "--task", task])
        evidence = {"heldConnections": self.held, "processExitCode": operation.process.poll(),
                    "state": status["state"], "executionActive": status["executionActive"]}
        if evidence["processExitCode"] is not None:
            operation.reader.join(3)
            recent = deque(maxlen=16)
            while not operation.events.empty():
                event = operation.events.get_nowait()
                if event:
                    recent.append(event)
            evidence["lastEvents"] = list(recent)
            evidence["stderr"] = operation.process.stderr.read()
        assert self.held and evidence["processExitCode"] is None, evidence
        assert status["state"] == "transferring" and status["executionActive"], evidence
        return evidence


# 日期：2026-11-05；等待真实客户端退出并排空有界测试事件，不把线程启动或就绪当任务成功。
def completed(operation):
    code = operation.process.wait(120)
    operation.reader.join(3)
    error = operation.process.stderr.read()
    events = []
    while not operation.events.empty():
        value = operation.events.get_nowait()
        if value:
            events.append(value)
    assert code == 0 and not error, (code, error, events)
    assert events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed", events
    return events[-1]


# 日期：2026-11-05；隔离目录、独立身份及回环服务，不改共享配置或触碰旧版长时测试。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--ready-timeout", type=int, default=30)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    samples = []
    binary_sha = digest(Path(executable))
    script_sha = digest(Path(__file__))
    with tempfile.TemporaryDirectory(prefix="dukto-isolation-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt":
            local = root / "dukto-cli.exe"
            shutil.copyfile(executable, local)
            executable = str(local)
        state, shared = root / "server", root / "shared"
        shared.mkdir()
        source = root / "large.bin"
        with source.open("wb") as output:
            for _ in range(1024):
                output.write(b"concurrent-roles" * 16384)
        expected = digest(source)
        # 日期：2026-11-05；第三项只用于验证等待/取消，无需重扫另一份大文件；前两项仍有真实部分正文。
        small = root / "small.bin"
        small.write_bytes(b"short-round" * 8192)
        small_sha = digest(small)
        holder_bytes, queued_bytes = source.stat().st_size, small.stat().st_size
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        permissions = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *permissions])
        offers = [run(executable, state, ["serve", "pairing", *permissions])[0] for _ in range(3)]
        port = free_port()
        server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state),
                                   "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        proxies = [HeldUploadProxy(port) for _ in range(2)]
        proxies.append(SlowProxy(port))
        output = None
        operations = []
        try:
            assert json.loads(server.stdout.readline())["event"] == "service-listening"
            output = JsonOutputDrain(server.stdout)
            clients = [root / f"client-{index}" for index in range(3)]
            for client, offer, proxy in zip(clients, offers, proxies):
                run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                         "--fingerprint", info["fingerprint"],
                                         "--credential-file", offer["credentialFile"]])
            for name in ("first", "second", "third"):
                (shared / name).mkdir()
            first = TransferProcess(executable, clients[0], ["upload", "--share", "data", "--path", str(source),
                                                              "--remote-path", "first", "--threads", "8"])
            operations.append(first)
            first_task = first.task(args.ready_timeout)
            wait_checkpoint(state / "service", first_task)
            second = TransferProcess(executable, clients[1], ["upload", "--share", "data", "--path", str(source),
                                                               "--remote-path", "second", "--threads", "16"])
            operations.append(second)
            second_task = second.task(args.ready_timeout)
            wait_checkpoint(state / "service", second_task)
            held_before = [proxies[index].assert_held(operation, executable, clients[index], task,
                                                       args.ready_timeout)
                           for index, operation, task in ((0, first, first_task), (1, second, second_task))]
            # 日期：2026-11-05；资源满时第三个新版任务有限等待，不能暗中启动；取消等待不得影响其他传输。
            third = TransferProcess(executable, clients[2], ["upload", "--share", "data", "--path", str(small),
                                                            "--remote-path", "third", "--threads", "4"])
            operations.append(third)
            while True:
                queued = third.events.get(timeout=args.ready_timeout)
                assert queued is not None
                if queued.get("state") == "queued":
                    third_task = queued["taskId"]
                    break
            queued_status, _ = run(executable, clients[2], ["task", "--task", third_task])
            held_during_queue = [proxies[index].assert_held(operation, executable, clients[index], task,
                                                             args.ready_timeout)
                                 for index, operation, task in ((0, first, first_task), (1, second, second_task))]
            assert queued_status["state"] == "queued" and queued_status["executionActive"], (queued_status, held_during_queue)
            run(executable, clients[2], ["cancel", "--task", third_task])
            third.finish()
            wait_state(executable, clients[2], third_task, "cancelled")
            started = time.monotonic()
            run(executable, clients[0], ["pause", "--task", first_task])
            first.finish()
            wait_state(executable, clients[0], first_task, "paused")
            pause_seconds = round(time.monotonic() - started, 3)
            assert pause_seconds < 8, pause_seconds
            second_status, _ = run(executable, clients[1], ["task", "--task", second_task])
            assert second_status["executionActive"] and second_status["state"] == "transferring", second_status
            proxies[1].released.set()
            second_result = completed(second)
            assert second_result["channels"] == "8", second_result
            assert digest(shared / "second" / source.name) == expected
            proxies[0].released.set()
            resumed = transfer(executable, clients[0], ["resume", "--task", first_task,
                                                       "--path", str(source), "--threads", "16"])
            assert resumed["taskId"] == first_task and resumed["channels"] == "16"
            assert digest(shared / "first" / source.name) == expected
            # 日期：2026-11-05；同一服务反复创建/销毁数据线程，采样暖机后空闲句柄/RSS/线程趋势。
            for index in range(15):
                destination = shared / f"round-{index}"
                destination.mkdir()
                transfer(executable, clients[2], ["upload", "--share", "data", "--path", str(small),
                                                   "--remote-path", destination.name, "--threads", "4"])
                assert digest(destination / small.name) == small_sha
                if index >= 3:
                    samples.append(idle_sample(server, samples[0] if samples else None))
            baseline = samples[0]
            assert max(item["handlesOrFds"] for item in samples) <= baseline["handlesOrFds"] + 8, samples
            assert max(item["threads"] for item in samples) <= baseline["threads"] + 1, samples
            assert samples[-1]["rss"] <= baseline["rss"] + 8 * 1024 * 1024, samples
        finally:
            for operation in operations:
                if operation.process.poll() is None:
                    operation.process.kill()
                    operation.process.wait(10)
            for proxy in proxies:
                proxy.close()
            server.kill()
            server.wait(timeout=15)
            server_output = output.finish() if output else None
            error = server.stderr.read()
            assert not error, error
    report = {"date": "2026-11-05", "passed": True, "binarySha256": binary_sha, "scriptSha256": script_sha, "payloadSha256": expected,
              "heldBeforeThirdScan": held_before, "heldWhenThirdQueued": held_during_queue,
              "serverOutput": server_output, "heldLaneBytesPerSecond": 524288,
              "holderPayloadBytes": holder_bytes, "queuedPayloadBytes": queued_bytes,
              "frameTimeoutSeconds": 30, "pauseGateSeconds": 8,
              "readyTimeoutSeconds": args.ready_timeout, "requestedChannels": [8, 16], "actualChannels": [8, 8], "thirdTaskQueuedAndCancelled": True,
              "pauseSecondsWhileSaturated": pause_seconds, "unrelatedTaskContinued": True,
              "resumeChannels": 16, "idleSamplesAfterWarmup": samples,
              "scope": "two active owners and a third queued/cancelled, shared16 slots and independent pause; broader fair-owner ordering and budgets have separate validation"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
