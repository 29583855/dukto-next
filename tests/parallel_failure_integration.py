"""日期：2026-11-05；延迟控制连接的真实TLS回环验证，原始冲突不能被其他数据线程的取消覆盖。"""

import argparse
from collections import Counter
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

from process_output import JsonOutputDrain
from service_integration import free_port, run
from transfer_integration import digest
from transfer_recovery_integration import SlowProxy


class CauseDrain(JsonOutputDrain):
    # 日期：2026-11-05；固定数量用例只累计错误码/阶段计数，不保留无界服务输出。
    def __init__(self, stream):
        self.causes = Counter()
        super().__init__(self.lines(stream))

    # 日期：2026-11-05；控制与数据线程都必须保留原始错误，不能只检查碰巧先到的客户端结果。
    def lines(self, stream):
        for line in stream:
            event = json.loads(line)
            if event.get("event") == "service-connection-closed":
                self.causes[(event.get("code"), event.get("stage"))] += 1
            yield line


class DelayedControlProxy(SlowProxy):
    # 日期：2026-11-05；代理保持TLS密文，只在本测试所有数据连接已接受后延迟控制方向的一次转发。
    def __init__(self, target):
        self.accepted = 0
        self.control = 0
        self.channels = 0
        self.delayed = False
        super().__init__(target)

    # 日期：2026-11-05；下一条连接为本次操作的控制连接，配对及上一次线程全部结束后才重新标记。
    def arm(self, channels):
        self.control = self.accepted + 1
        self.channels = channels
        self.delayed = False

    # 日期：2026-11-05；每条测试连接保持独立读写线程，编号只用于网络时序，不解析协议或证书。
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
                self.accepted += 1
                number = self.accepted
                for connection in (client, server):
                    connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sockets.extend((client, server))
                for source, destination, from_server in ((client, server, False), (server, client, True)):
                    worker = threading.Thread(target=self.forward,
                                              args=(source, destination, number, from_server), daemon=True)
                    self.threads.append(worker)
                    worker.start()
            except OSError:
                client.close()

    # 日期：2026-11-05；控制失败比数据失败晚三秒到达，稳定暴露谁先返回就覆盖根因的竞态。
    def forward(self, source, destination, number, from_server):
        try:
            while not self.stopped.is_set():
                data = source.recv(16384)
                if not data:
                    break
                if (from_server and number == self.control and not self.delayed
                        and self.accepted >= self.control + self.channels):
                    self.delayed = True
                    if self.stopped.wait(3):
                        break
                destination.sendall(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


# 日期：2026-11-05；用真实服务器和独立客户端检查退出码、原始错误阶段、任务失败及目标保护。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report_path = Path(args.report)
    assert not report_path.exists()
    report = {"date": "2026-11-05", "passed": False, "binarySha256": digest(Path(executable)),
              "scriptSha256": digest(Path(__file__)), "cases": [],
              "scope": "real TLS upload conflict with delayed control connection; sibling cancellations must preserve original cause"}
    try:
        with tempfile.TemporaryDirectory(prefix="dukto-parallel-failure-") as temporary:
            root = Path(temporary)
            server, client, shared = root / "server", root / "client", root / "shared"
            shared.mkdir()
            source = root / "中文 payload.bin"
            source.write_bytes(bytes(range(251)) * 43)
            info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
            rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
            run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
            offer, _ = run(executable, server, ["serve", "pairing", *rights])
            port = free_port()
            process = subprocess.Popen([executable, "serve", "start", "--state-directory", str(server),
                                        "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            drain = CauseDrain(process.stdout)
            proxy = DelayedControlProxy(port)
            try:
                deadline = time.monotonic() + 15
                while not drain.events.get("service-listening"):
                    assert process.poll() is None and time.monotonic() < deadline, list(drain.recent)
                    time.sleep(0.01)
                run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                         "--fingerprint", info["fingerprint"],
                                         "--credential-file", offer["credentialFile"]])
                for channels in (4, 16):
                    for directory in (False, True):
                        destination = shared / f"target-{channels}-{directory}"
                        destination.mkdir()
                        original = destination / source.name
                        if directory:
                            original.mkdir()
                            preserved = original / "preserved"
                        else:
                            preserved = original
                        preserved.write_bytes(b"original user data")
                        expected = digest(preserved)
                        previous = drain.causes.copy()
                        proxy.arm(channels)
                        operation = subprocess.run([executable, "upload", "--share", "data", "--path", str(source),
                                                    "--remote-path", destination.name, "--threads", str(channels),
                                                    "--on-conflict", "fail", "--timeout", "10",
                                                    "--state-directory", str(client), "--json"],
                                                   capture_output=True, encoding="utf-8", timeout=40)
                        events = [json.loads(line) for line in operation.stdout.splitlines()]
                        actual = {"channels": channels, "directoryConflict": directory,
                                  "delayedControl": proxy.delayed, "exitCode": operation.returncode,
                                  "lastEvent": events[-1] if events else None,
                                  "originalPreserved": digest(preserved) == expected}
                        report["cases"].append(actual)
                        assert operation.returncode == 4 and not operation.stderr, actual
                        assert proxy.delayed and events[-1]["event"] == "error" and events[-1]["stage"] == "conflict", actual
                        assert actual["originalPreserved"] and sorted(item.name for item in destination.iterdir()) == [source.name], actual
                        assert not any(event.get("event") == "transfer-completed" for event in events), actual
                        task = next(event["taskId"] for event in events if event.get("taskId"))
                        status, _ = run(executable, client, ["task", "--task", task])
                        assert status["state"] == "failed" and status["error"] == 4 and not status["executionActive"], status
                        deadline = time.monotonic() + 10
                        while sum(drain.causes.values()) - sum(previous.values()) < channels + 1:
                            assert time.monotonic() < deadline, dict(drain.causes)
                            time.sleep(0.01)
                        causes = drain.causes - previous
                        actual["connectionCauses"] = [{"code": key[0], "stage": key[1], "count": count}
                                                      for key, count in sorted(causes.items())]
                        assert causes == Counter({(4, "conflict"): channels + 1}), actual
                        actual.update(taskId=task, persistedError=status["error"], state=status["state"], passed=True)
            finally:
                proxy.close()
                process.kill()
                process.wait(timeout=10)
                report["serverOutput"] = drain.finish()
                assert not process.stderr.read()
        report["passed"] = True
    finally:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "cases": report["cases"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
