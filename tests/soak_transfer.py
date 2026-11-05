"""日期：2026-11-04；隔离的定时收发与长期资源采样，流式保留证据，不累积测试文件。"""

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import tempfile
import time

import psutil


# 日期：2026-11-04；报告原子替换，运行中只写 running，不把尚未结束的测试标为通过。
def save_report(path, report):
    temporary = path.with_suffix(".new")
    temporary.write_bytes((json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    temporary.replace(path)


# 日期：2026-11-04；事件按增量读取并限制未完成行，不将 24 小时日志全部加载进内存。
def await_event(reader, process, name, timeout):
    deadline = time.monotonic() + timeout
    pending = b""
    while time.monotonic() < deadline:
        data = reader.read(8192)
        if data:
            pending += data
            if len(pending) > 65536:
                raise RuntimeError("receiver emitted an oversized event")
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if not line.strip():
                    continue
                event = json.loads(line)
                if event["event"] == "error":
                    raise RuntimeError(event)
                if event["event"] == name:
                    if pending.strip():
                        raise RuntimeError("unexpected queued events after terminal event")
                    return event
        if process.poll() is not None:
            raise RuntimeError("receiver exited: " + str(process.returncode))
        time.sleep(0.02)
    raise TimeoutError("receiver did not emit " + name)


# 日期：2026-11-04；稳定接收进程必须可观测，权限失败不能静默丢掉长期样本。
def metrics(target):
    memory = target.memory_info()
    private = memory.private if os.name == "nt" else target.memory_full_info().uss
    return {"rss": memory.rss, "private": private, "threads": target.num_threads(),
            "handles": target.num_handles() if os.name == "nt" else target.num_fds()}


# 日期：2026-11-04；摘要始终分片读取，每轮清理只删除刚验证过的本任务副本。
def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(256 * 1024):
            value.update(block)
    return value.hexdigest()


# 日期：2026-11-04；按固定节奏执行同一工作负载，样本直接写 CSV，暖机后增长门槛为 16 MiB。
def run(executable, root, report_path, duration, interval):
    report = {"date": "2026-11-04", "status": "running", "passed": False,
              "scope": "persistent R6 receiver; one sender process per round; not parallel-protocol qualification",
              "platform": platform.platform(), "durationSeconds": duration,
              "intervalSeconds": interval, "sampleIntervalSeconds": 1,
              "privateMetric": "PrivateUsage" if os.name == "nt" else "USS", "rounds": 0,
              "testScriptSha256": digest(Path(__file__).resolve()),
              "executableSha256": digest(Path(executable)), "peaks": {}}
    save_report(report_path, report)
    source = root / "payload.bin"
    source.write_bytes(os.urandom(1024 * 1024 + 131))
    expected = digest(source)
    output = root / "received"
    output.mkdir()
    original = output / "payload.bin"
    original.write_bytes(b"original must survive")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = str(reservation.getsockname()[1])
    receiver = None
    samples_path = report_path.parent / "samples.csv"
    events_path = report_path.parent / "events.jsonl"
    error_path = report_path.parent / "stderr.log"
    with events_path.open("wb") as events, error_path.open("wb") as errors, \
            events_path.open("rb", buffering=0) as reader, \
            samples_path.open("w", encoding="utf-8", newline="") as samples:
        try:
            receiver = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", port,
                                         "--output", str(output), "--state-directory", str(root / "state"),
                                         "--timeout", "15", "--json"], stdout=events, stderr=errors)
            await_event(reader, receiver, "listening", 15)
            target = psutil.Process(receiver.pid)
            report["receiverPid"] = receiver.pid
            started = time.monotonic()
            report["startedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            report["payloadBytes"] = source.stat().st_size
            report["payloadSha256"] = expected
            writer = csv.DictWriter(samples, fieldnames=["elapsedSeconds", "rounds", "phase", "rss", "private", "threads", "handles"])
            writer.writeheader()
            next_round = started
            next_sample = started
            baseline = None
            latest = None
            while time.monotonic() - started < duration:
                now = time.monotonic()
                phase = "idle"
                if now >= next_round:
                    sent = subprocess.run([executable, "send", "--to", "127.0.0.1", "--port", port,
                                           "--path", str(source), "--timeout", "15", "--json"],
                                          capture_output=True, timeout=30)
                    assert sent.returncode == 0 and not sent.stderr, (sent.returncode, sent.stdout, sent.stderr)
                    result = await_event(reader, receiver, "result", 30)
                    assert result["stage"] == "received"
                    destination = Path(result["path"]).resolve()
                    assert destination.parent == output.resolve() and destination != original.resolve()
                    assert destination.stat().st_size == source.stat().st_size and digest(destination) == expected
                    assert original.read_bytes() == b"original must survive"
                    destination.unlink()
                    assert not list(output.glob(".dukto-*.part"))
                    assert error_path.stat().st_size == 0
                    assert events_path.stat().st_size < 16 * 1024**2
                    report["rounds"] += 1
                    phase = "after-transfer"
                    next_round = time.monotonic() + interval
                    if report["rounds"] == 10:
                        baseline = metrics(target)
                        report["warmBaseline"] = baseline
                        # 日期：2026-11-04；Qt/系统线程会按空闲期限收缩，使用同工作负载暖机峰值核对数量。
                        report["warmResourceLimits"] = {
                            "threads": max(baseline["threads"], report["peaks"].get("threads", 0)) + 1,
                            "handles": max(baseline["handles"], report["peaks"].get("handles", 0)) + 8}
                    report["elapsedSeconds"] = round(time.monotonic() - started, 3)
                    save_report(report_path, report)
                if now >= next_sample or phase == "after-transfer":
                    latest = metrics(target)
                    for key, value in latest.items():
                        report["peaks"][key] = max(report["peaks"].get(key, 0), value)
                    writer.writerow({"elapsedSeconds": round(time.monotonic() - started, 3),
                                     "rounds": report["rounds"], "phase": phase, **latest})
                    samples.flush()
                    next_sample = time.monotonic() + 1
                    assert latest["rss"] < 512 * 1024**2 and latest["private"] < 512 * 1024**2
                    if baseline and report["rounds"] >= 20:
                        assert latest["rss"] - baseline["rss"] <= 16 * 1024**2
                        assert latest["private"] - baseline["private"] <= 16 * 1024**2
                        assert latest["threads"] <= report["warmResourceLimits"]["threads"], latest
                        assert latest["handles"] <= report["warmResourceLimits"]["handles"], latest
                time.sleep(0.1)
            assert baseline is not None and report["rounds"] >= 20, "insufficient steady workload rounds"
            report.update(status="passed", passed=True, final=latest,
                          elapsedSeconds=round(time.monotonic() - started, 3))
        except BaseException as error:
            report.update(status="failed", passed=False, failure=type(error).__name__ + ": " + str(error))
            raise
        finally:
            if receiver and receiver.poll() is None:
                receiver.terminate()
                try:
                    receiver.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    receiver.kill()
                    receiver.wait(timeout=5)
            report["finishedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            save_report(report_path, report)
    return report


# 日期：2026-11-04；Windows 使用独立 EXE 副本避免长时验证锁住开发产物，所有数据在自建临时目录。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--duration", type=int, default=86400)
    parser.add_argument("--interval", type=float, default=30)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if not 1 <= args.duration <= 172800 or args.interval < 0.1 or math.ceil(args.duration / args.interval) > 9000:
        raise ValueError("duration/interval exceeds this test's bounded task-history quota")
    report = Path(args.report).resolve()
    if report.exists():
        raise FileExistsError("use a new report path to preserve prior validation evidence")
    report.parent.mkdir(parents=True, exist_ok=True)
    cache = Path(__file__).resolve().parent.parent / ".cache"
    cache.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="soak-", dir=cache) as temporary:
        root = Path(temporary)
        executable = Path(args.executable).resolve()
        if os.name == "nt":
            copied = root / executable.name
            shutil.copy2(executable, copied)
            executable = copied
        result = run(str(executable), root, report, args.duration, args.interval)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
