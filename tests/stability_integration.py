"""日期：2026-11-04；真实进程验证海量文件、重复任务、源变化与资源边界。"""

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import struct
import subprocess
import tempfile
import threading
import time

import psutil

from large_transfer import await_listener, digest, sample


# 日期：2026-11-04；固定读取预算解析事件，只由测试读取日志，不干预目标进程。
def events(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


# 日期：2026-11-04；异常时只终止本测试创建且仍存活的子进程。
def stop(processes):
    for process in processes:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)


# 日期：2026-11-04；资源采样只保留秒级桶与峰值，不随文件数量保留事件副本。
def monitor(processes, timeout):
    started = time.monotonic()
    peaks = [{} for _ in processes]
    buckets = []
    while any(process.poll() is None for process in processes):
        elapsed = time.monotonic() - started
        if elapsed > timeout:
            raise TimeoutError("stability case exceeded deadline")
        for process, peak in zip(processes, peaks):
            sample(process, peak)
        second = int(elapsed)
        if len(buckets) <= second:
            buckets.append({"second": second, "rss": []})
            for process in processes:
                try:
                    buckets[-1]["rss"].append(psutil.Process(process.pid).memory_info().rss)
                except psutil.NoSuchProcess:
                    buckets[-1]["rss"].append(None)
        time.sleep(0.05)
    for peak in peaks:
        assert peak["rss"] < 512 * 1024**2, peak
        assert peak["threads"] <= 16, peak
        assert peak["handles"] <= 512, peak
    return {"seconds": round(time.monotonic() - started, 3), "peaks": peaks,
            "rssBySecond": buckets, "sampleIntervalMs": 50}


# 日期：2026-11-04；分组建立小文件，逐项计算期望内容，避免所有文件名进入应用参数。
def many_files(executable, root, count):
    source = root / "tree"
    source.mkdir()
    total = 0
    for index in range(count):
        directory = source / f"group-{index // 1000:04d}"
        directory.mkdir(exist_ok=True)
        content = (f"{index}:中文\n".encode("utf-8") if index % 3 else b"")
        (directory / f"file-{index:06d}.bin").write_bytes(content)
        total += len(content)
    output = root / "received"
    output.mkdir()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = str(reservation.getsockname()[1])
    processes = []
    rx_path = root / "receive.jsonl"
    tx_path = root / "send.jsonl"
    with rx_path.open("wb") as rx, tx_path.open("wb") as tx, (root / "error.log").open("wb") as err:
        try:
            receiver = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", port,
                                         "--output", str(output), "--once", "--json", "--state-directory",
                                         str(root / "state")], stdout=rx, stderr=err)
            processes.append(receiver)
            await_listener(receiver, rx_path)
            sender = subprocess.Popen([executable, "send", "--to", "127.0.0.1", "--port", port,
                                       "--path", str(source), "--json"], stdout=tx, stderr=err)
            processes.append(sender)
            metrics = monitor(processes, 1800)
            assert all(process.returncode == 0 for process in processes), events(rx_path)[-1]
        finally:
            stop(processes)
    checked = 0
    with closing(sqlite3.connect(root / "state/receipts.sqlite")) as db:
        assert db.execute("SELECT state,total,received FROM tasks").fetchone() == ("completed", total, total)
        for relative, path, size, sha in db.execute("SELECT source,path,bytes,sha256 FROM files"):
            if size < 0:
                assert Path(path).is_dir()
                continue
            index = int(Path(relative).stem.removeprefix("file-"))
            expected = f"{index}:中文\n".encode("utf-8") if index % 3 else b""
            target = Path(path)
            assert target.read_bytes() == expected
            assert size == len(expected) and sha == hashlib.sha256(expected).hexdigest()
            checked += 1
        assert checked == count
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert not (root / "error.log").read_bytes()
    assert not any(output.rglob("*.part"))
    return {"test": "many-files", "passed": True, "files": checked, "bytes": str(total),
            "catalogBytes": (root / "state/receipts.sqlite").stat().st_size, **metrics}


# 日期：2026-11-04；同一监听器反复接收，记录暖机后与末轮资源，校验所有同名副本。
def repeated(executable, root, rounds):
    source = root / "sample.bin"
    source.write_bytes(bytes(range(256)) * 4096)
    expected = digest(source)
    output = root / "received"
    output.mkdir()
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = str(reservation.getsockname()[1])
    processes = []
    rx_path = root / "receive.jsonl"
    snapshots = []
    peak = {}
    started = time.monotonic()
    with rx_path.open("wb") as rx, (root / "error.log").open("wb") as err:
        try:
            receiver = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", port,
                                         "--output", str(output), "--json", "--state-directory",
                                         str(root / "state")], stdout=rx, stderr=err)
            processes.append(receiver)
            await_listener(receiver, rx_path)
            for index in range(rounds):
                sent = subprocess.run([executable, "send", "--to", "127.0.0.1", "--port", port,
                                       "--path", str(source), "--json"], capture_output=True, timeout=30)
                assert sent.returncode == 0, sent.stdout
                deadline = time.monotonic() + 10
                while len([e for e in events(rx_path) if e["event"] == "result"]) < index + 1:
                    if time.monotonic() > deadline:
                        raise TimeoutError("receiver result missing")
                    time.sleep(0.01)
                time.sleep(0.02)
                sample(receiver, peak)
                current = psutil.Process(receiver.pid)
                snapshots.append({"round": index + 1, "rss": current.memory_info().rss,
                                  "handles": current.num_handles() if os.name == "nt" else current.num_fds(),
                                  "threads": current.num_threads()})
            assert all(e["stage"] == "received" for e in events(rx_path) if e["event"] == "result")
            copies = list(output.glob("*.bin"))
            assert len(copies) == rounds
            for path in copies:
                assert digest(path) == expected
            with closing(sqlite3.connect(root / "state/receipts.sqlite")) as db:
                assert db.execute("SELECT count(*) FROM tasks WHERE state='completed'").fetchone()[0] == rounds
            warm = snapshots[min(9, rounds - 1)]
            final = snapshots[-1]
            assert final["rss"] - warm["rss"] <= 32 * 1024**2, snapshots
            assert final["handles"] - warm["handles"] <= 8, snapshots
            assert final["threads"] <= warm["threads"] + 1, snapshots
        finally:
            stop(processes)
    assert not (root / "error.log").read_bytes()
    return {"test": "repeated-receiver", "passed": True, "rounds": rounds, "peaks": peak,
            "warm": warm, "final": final, "snapshots": snapshots,
            "seconds": round(time.monotonic() - started, 3)}


# 日期：2026-11-04；独立慢接收方在包头之后修改源大小，发送方必须拒绝报告成功。
def source_changes(executable, root):
    source = root / "changing.bin"
    size = 32 * 1024**2
    with source.open("wb") as stream:
        stream.truncate(size)
    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(15)
    failures = []
    transferred = []

    # 日期：2026-11-04；精确读取有限包头，测试端不共享应用的协议编解码实现。
    def exact(connection, length):
        data = bytearray()
        while len(data) < length:
            fragment = connection.recv(length - len(data))
            if not fragment:
                raise EOFError("unexpected sender disconnect")
            data.extend(fragment)
        return bytes(data)

    # 日期：2026-11-04；源修改发生在清单扫描后、传输完成前，以避免时间竞争的假通过。
    def consume():
        try:
            with server.accept()[0] as connection:
                connection.settimeout(15)
                assert struct.unpack("<qq", exact(connection, 16)) == (1, size)
                name = bytearray()
                while True:
                    byte = exact(connection, 1)
                    if byte == b"\0":
                        break
                    name.extend(byte)
                assert name == b"changing.bin"
                assert struct.unpack("<q", exact(connection, 8))[0] == size
                with source.open("r+b") as stream:
                    stream.truncate(size + 1)
                received = 0
                while received < size:
                    block = connection.recv(min(256 * 1024, size - received))
                    if not block:
                        break
                    received += len(block)
                transferred.append(received)
        except BaseException as error:
            failures.append(repr(error))

    thread = threading.Thread(target=consume, daemon=True)
    thread.start()
    try:
        result = subprocess.run([executable, "send", "--to", "127.0.0.1", "--port",
                                 str(server.getsockname()[1]), "--path", str(source), "--json"],
                                capture_output=True, timeout=30)
        thread.join(timeout=20)
        assert not thread.is_alive() and not failures, failures
        assert result.returncode == 6, result.stdout
        final = json.loads(result.stdout.splitlines()[-1])
        assert final["event"] == "error" and final["stage"] == "send", final
        return {"test": "source-changes", "passed": True, "exit": result.returncode,
                "transferred": transferred, "result": final}
    finally:
        server.close()


# 日期：2026-11-04；每个用例使用隔离目录，结果只在实际校验成功后写入报告。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--case", choices=["all", "many", "repeat", "source"], default="all")
    parser.add_argument("--files", type=int, default=100000)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    assert 1 <= args.files <= 1000000 and 1 <= args.rounds <= 1000
    executable = str(Path(args.executable).resolve())
    cache = Path(__file__).resolve().parent.parent / ".cache"
    cache.mkdir(exist_ok=True)
    cases = [("source", source_changes, None), ("repeat", repeated, args.rounds),
             ("many", many_files, args.files)]
    results = []
    for name, function, value in cases:
        if args.case not in ("all", name):
            continue
        with tempfile.TemporaryDirectory(prefix="stability-", dir=cache) as temporary:
            parameters = [executable, Path(temporary)] + ([] if value is None else [value])
            result = function(*parameters)
            results.append(result)
            print(json.dumps({key: value for key, value in result.items()
                              if key not in ("rssBySecond", "snapshots")}, ensure_ascii=False), flush=True)
        Path(args.report).write_text(json.dumps({"date": "2026-11-04", "platform": "Windows x64",
                                                "scope": "loopback; not a 24-hour or cross-platform result",
                                                "results": results}, ensure_ascii=False, indent=2) + "\n",
                                     encoding="utf-8")


if __name__ == "__main__":
    main()
