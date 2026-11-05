"""日期：2026-11-04；真实服务/客户端验证十万条目录分页、双端资源、扫描中断连和撤销。"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time

from large_transfer import sample
from service_integration import free_port, run


# 日期：2026-11-04；只在测试创建的进程之间采样，不采集用户进程或保留无界时间序列。
def monitor(processes, peaks, stopped, errors):
    try:
        while not stopped.is_set():
            for process in tuple(processes):
                sample(process, peaks.setdefault(process.pid, {}))
            stopped.wait(0.05)
    except BaseException as error:
        errors.append(repr(error))


# 日期：2026-11-04；测试自有扫描临时文件达到阈值时才注入故障，避免把连接前失败算作扫描取消。
def await_scan(process, private, deadline=20):
    until = time.monotonic() + deadline
    while time.monotonic() < until:
        for path in private.glob(".dukto-*.part"):
            try:
                if path.stat().st_size >= 65536:
                    return
            except FileNotFoundError:
                pass
        if process.poll() is not None:
            raise AssertionError("scan finished before fault injection")
        time.sleep(0.005)
    raise TimeoutError("no active directory snapshot observed")


# 日期：2026-11-04；断开的扫描必须停止并清理临时快照，不能等扫描全部目录后才发现无人接收。
def await_cleanup(private):
    until = time.monotonic() + 5
    while time.monotonic() < until:
        if not list(private.glob(".dukto-*.part")):
            return
        time.sleep(0.025)
    raise AssertionError("abandoned browse snapshot still growing or retained")


# 日期：2026-11-04；所有状态/数据均在测试目录，Windows 使用独立 EXE 避免锁住后续开发构建。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--files", type=int, default=100000)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    assert args.files >= 1000
    original = Path(args.executable).resolve()
    cache = Path(__file__).resolve().parent.parent / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="browse-load-", dir=cache) as temporary:
        root = Path(temporary).resolve()
        executable = original
        if os.name == "nt":
            executable = root / "dukto-cli.exe"
            shutil.copyfile(original, executable)
        executable = str(executable)
        data = root / "data"
        data.mkdir()
        fixture_start = time.monotonic()
        for index in range(args.files):
            (data / f"item-{index:06d}.txt").touch()
        fixture_seconds = round(time.monotonic() - fixture_start, 3)
        server_state, client_state = root / "server", root / "client"
        info, _ = run(executable, server_state, ["serve", "init", "--server-name", "127.0.0.1"])
        run(executable, server_state, ["serve", "share", "add", "--share", "docs", "--path", str(data), "--allow-browse"])
        offer, _ = run(executable, server_state, ["serve", "pairing", "--share", "docs", "--allow-browse"])
        port = free_port()
        server_log = root / "server.jsonl"
        server_error = root / "server.error"
        processes, peaks = [], {}
        stopped = threading.Event()
        monitor_errors = []
        worker = threading.Thread(target=monitor, args=(processes, peaks, stopped, monitor_errors), daemon=True)
        worker.start()
        try:
            with server_log.open("wb") as out, server_error.open("wb") as err:
                server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(server_state),
                                           "--bind", "127.0.0.1", "--port", str(port), "--timeout", "120", "--json"],
                                          stdout=out, stderr=err)
            processes.append(server)
            until = time.monotonic() + 15
            while not server_log.stat().st_size:
                assert server.poll() is None
                if time.monotonic() >= until:
                    raise TimeoutError("service did not start")
                time.sleep(0.025)
            paired, _ = run(executable, client_state,
                            ["pair", "--to", "127.0.0.1:" + str(port), "--fingerprint", info["fingerprint"],
                             "--credential-file", offer["credentialFile"]])
            command = [executable, "list", "--share", "docs", "--all", "--timeout", "120",
                       "--state-directory", str(client_state), "--json"]
            started = time.monotonic()
            with (root / "client.error").open("wb") as err, closing(sqlite3.connect(root / "seen.sqlite")) as observed:
                observed.execute("CREATE TABLE seen(name TEXT PRIMARY KEY)")
                client = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err, encoding="utf-8")
                processes.append(client)
                pages, received = 0, 0
                last_cursor = None
                for line in client.stdout:
                    page = json.loads(line)
                    assert page["event"] == "listing" and len(page["entries"]) <= 100, page
                    assert len(line.encode("utf-8")) < 65536
                    for entry in page["entries"]:
                        name = entry["name"]
                        assert name.startswith("item-") and name.endswith(".txt") and len(name) == 15
                        number = int(name[5:11])
                        assert 0 <= number < args.files and name == f"item-{number:06d}.txt"
                        assert entry["type"] == "file" and entry["bytes"] == "0"
                        observed.execute("INSERT INTO seen VALUES(?)", (name,))
                        received += 1
                    last_cursor = page["cursor"]
                    pages += 1
                assert client.wait(timeout=10) == 0
                assert received == args.files and observed.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == args.files
                assert last_cursor == ""
            seconds = round(time.monotonic() - started, 3)
            assert not (root / "client.error").read_bytes()
            private = server_state / "service"
            snapshots = list(private.glob("browse-*.json"))
            assert len(snapshots) == 1
            snapshot_bytes = sum(p.stat().st_size for p in private.glob("browse-*.*"))
            # 日期：2026-11-04；真实断开客户端后服务工作者须周期检查 TLS 状态并释放未发布快照。
            with (root / "disconnected.log").open("wb") as out:
                disconnected = subprocess.Popen(command, stdout=out, stderr=out)
            processes.append(disconnected)
            await_scan(disconnected, private)
            interrupted = time.monotonic()
            disconnected.kill()
            disconnected.wait(timeout=5)
            await_cleanup(private)
            disconnect_seconds = round(time.monotonic() - interrupted, 3)
            assert len(list(private.glob("browse-*.json"))) == 1
            # 日期：2026-11-04；在扫描已开始后由另一真实管理进程撤销身份，不能泄露任何列表页。
            with (root / "revoked.error").open("wb") as err:
                revoked = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=err, encoding="utf-8")
            processes.append(revoked)
            await_scan(revoked, private)
            run(executable, server_state, ["serve", "revoke", "--client", paired["client"]])
            output, _ = revoked.communicate(timeout=10)
            assert revoked.returncode == 4, output
            events = [json.loads(line) for line in output.splitlines()]
            assert len(events) == 1 and events[0]["event"] == "error" and events[0]["stage"] == "auth", events
            await_cleanup(private)
            assert len(list(private.glob("browse-*.json"))) == 1 and server.poll() is None
            assert not server_error.read_bytes() and not (root / "revoked.error").read_bytes()
        finally:
            for process in reversed(processes):
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=10)
            stopped.set()
            worker.join(timeout=5)
        assert not worker.is_alive() and not monitor_errors, monitor_errors
        for value in peaks.values():
            assert value["rss"] < 128 * 1024**2 and value["handles"] < 512 and value["threads"] <= 16, value
        report = {"date": "2026-11-04", "passed": True, "files": args.files, "pages": pages,
                  "browseSeconds": seconds, "fixtureSeconds": fixture_seconds,
                  "snapshotBytes": snapshot_bytes, "disconnectCleanupSeconds": disconnect_seconds,
                  "scanDisconnectPassed": True, "scanRevocationPassed": True,
                  "peaks": {str(pid): value for pid, value in peaks.items()}, "sampleIntervalMs": 50,
                  "scope": "real metadata browsing; no file transfer or multi-channel performance claim"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
