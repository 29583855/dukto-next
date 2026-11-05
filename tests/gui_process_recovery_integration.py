"""日期：2026-11-05；真实 GUI 面板进程被终止后，新 GUI 进程经生产按钮找回同任务并续传。"""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

from service_integration import free_port, run
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, wait_state


class GuiProcess:
    # 日期：2026-11-05；只启本测试自有 GUI 探针，事件队列有上限，不能把长传输积累成无界历史。
    def __init__(self, executable, configuration, events_path):
        self.events = queue.Queue(maxsize=32)
        self.path = events_path
        environment = os.environ.copy()
        environment.setdefault("QT_QPA_PLATFORM", "offscreen")
        if os.name != "nt" and not environment.get("XDG_RUNTIME_DIR"):
            runtime = configuration.parent / "runtime"
            runtime.mkdir(mode=0o700, exist_ok=True)
            environment["XDG_RUNTIME_DIR"] = str(runtime)
        self.process = subprocess.Popen([executable, str(configuration)], stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, encoding="utf-8", env=environment)
        self.reader = threading.Thread(target=self.read, daemon=True)
        self.reader.start()

    # 日期：2026-11-05；逐行保存实际面板快照，不解析或输出私有状态目录内的凭据文件。
    def read(self):
        with self.path.open("w", encoding="utf-8") as output:
            for line in self.process.stdout:
                output.write(line)
                output.flush()
                self.events.put(json.loads(line))
        self.events.put(None)

    # 日期：2026-11-05；事件消费者保持独立总截止，只保留实际任务、资源峰值及最终结果。
    def event(self, deadline):
        try:
            value = self.events.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty as error:
            raise AssertionError(("GUI process deadline", self.process.poll(), self.path)) from error
        assert value is not None, ("GUI process exited early", self.process.poll(), self.path)
        return value

    # 日期：2026-11-05；清理只涉及本测试创建的 GUI 进程，不停止现有长时或海量测试。
    def close(self):
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(10)
        while self.reader.is_alive():
            try:
                self.events.get(timeout=0.1)
            except queue.Empty:
                pass
            self.reader.join(0.01)
        error = self.process.stderr.read()
        assert not error, error


# 日期：2026-11-05；读取实际接收日志中的已同步字节，活动进程尚未完成时才允许注入终止。
def checkpoint(state, task):
    path = state / "transfers" / f"receive-{task}.sqlite"
    if not path.exists():
        return 0
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=0.01)) as database:
            return database.execute("SELECT COALESCE(SUM(confirmed),0) FROM files").fetchone()[0]
    except sqlite3.OperationalError:
        return 0


# 日期：2026-11-05；本机不透明 TLS 慢代理便于观察中途检查点，协议/磁盘/身份全部使用生产实现。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("gui_probe")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    gui = str(Path(args.gui_probe).resolve())
    report = args.report.resolve()
    report.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dukto-gui-process-") as temporary:
        root = Path(temporary).resolve()
        state, client, shared, output = [root / name for name in ("server", "client", "shared", "output")]
        shared.mkdir()
        output.mkdir()
        source = shared / "data.bin"
        size = 64 * 1024**2 + 37
        with source.open("wb") as stream:
            for block in range(256):
                stream.write(bytes([block % 251]) * (256 * 1024))
            stream.write(b"tail" * 9 + b"!")
        expected = digest(source)
        original = output / source.name
        original.write_bytes(b"preserve local original")
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "docs", "--allow-browse", "--allow-download"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, state, ["serve", "pairing", *rights])
        port = free_port()
        active = None
        proxy = None
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as events, \
                tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state),
                "--bind", "127.0.0.1", "--port", str(port), "--json"], stdout=events, stderr=errors)
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    events.seek(0)
                    line = events.readline()
                    if line:
                        assert json.loads(line)["event"] == "service-listening"
                        break
                    assert server.poll() is None
                    time.sleep(0.02)
                else:
                    raise AssertionError("Service startup deadline")
                proxy = SlowProxy(port)
                run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                    "--fingerprint", info["fingerprint"], "--credential-file", offer["credentialFile"]])
                request = str(uuid.uuid4())
                configuration = root / "gui.json"
                options = {"state": str(client), "share": "docs", "remotePath": source.name,
                    "output": str(output), "requestId": request, "channels": "4", "operation": "download",
                    "screenshot": str(report.with_suffix(".initial.png"))}
                configuration.write_text(json.dumps(options, ensure_ascii=False), encoding="utf-8")
                active = GuiProcess(gui, configuration, report.with_suffix(".initial.jsonl"))
                first_pid = active.process.pid
                task = None
                durable = 0
                ready = False
                initial_platform = None
                deadline = time.monotonic() + 120
                while time.monotonic() < deadline:
                    event = active.event(deadline)
                    ready = ready or event["event"] == "gui-ready"
                    if event["event"] == "gui-ready":
                        initial_platform = event["platform"]
                    assert event["event"] != "gui-finished", event
                    value = event.get("task", {})
                    task = value.get("taskId", task)
                    if task:
                        durable = checkpoint(client, task)
                        if durable >= 8 * 1024**2:
                            assert durable < size and active.process.poll() is None
                            break
                assert ready and task and durable >= 8 * 1024**2
                active.process.kill()
                active.close()
                active = None
                interrupted = wait_state(executable, client, task, "interrupted")
                assert interrupted["requestId"] == request
                options.update({"operation": "resume", "taskId": task, "channels": "8",
                                "screenshot": str(report.with_suffix(".resumed.png"))})
                configuration.write_text(json.dumps(options, ensure_ascii=False), encoding="utf-8")
                active = GuiProcess(gui, configuration, report.with_suffix(".resumed.jsonl"))
                second_pid = active.process.pid
                recovered = False
                resumed_platform = None
                restored = 0
                deadline = time.monotonic() + 180
                while True:
                    event = active.event(deadline)
                    if event["event"] == "gui-ready":
                        resumed_platform = event["platform"]
                    if event["event"] == "gui-task-recovered":
                        assert event["taskId"] == task
                        recovered = True
                    restored = max(restored, int(event.get("task", {}).get("restoredBytes", "0")))
                    if event["event"] == "gui-finished":
                        assert event["passed"] and event["task"]["state"] == "completed", event
                        assert event["task"]["taskId"] == task and event["task"]["requestId"] == request
                        assert event["task"]["channels"] == "8", event
                        final = event["task"]
                        break
                assert active.process.wait(15) == 0
                active.close()
                active = None
                assert recovered and restored >= durable and first_pid != second_pid
                assert initial_platform and initial_platform == resumed_platform
                received = output / "data (2).bin"
                assert received.stat().st_size == size and digest(received) == expected
                assert original.read_bytes() == b"preserve local original"
                retry = transfer(executable, client, ["download", "--share", "docs", "--remote-path", source.name,
                    "--output", str(output), "--threads", "8", "--request-id", request])
                assert retry["taskId"] == task and len(list(output.iterdir())) == 2
                result = {"date": "2026-11-05", "passed": True, "firstPid": first_pid,
                    "secondPid": second_pid, "confirmedAtKill": durable, "restoredBytes": restored,
                    "taskId": task, "requestId": request, "bytes": str(size), "sha256": expected,
                    "channelsBeforeAfter": [4, 8], "final": final, "sameNameOriginalPreserved": True,
                    "qtPlatform": initial_platform, "testScriptSha256": digest(Path(__file__).resolve()),
                    "guiProbeSha256": digest(Path(gui)), "cliSha256": digest(Path(executable)),
                    "scope": "new processes render production ServerPage/ServerPanel and click actual buttons; not full application shell restart or native chooser qualification"}
            finally:
                if active:
                    active.close()
                if proxy:
                    proxy.close()
                server.kill()
                server.wait(10)
                errors.seek(0)
                assert not errors.read()
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("GUI panel process restart and same-task recovery passed", flush=True)


if __name__ == "__main__":
    main()
