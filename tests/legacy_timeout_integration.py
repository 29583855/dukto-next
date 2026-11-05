"""日期：2026-11-05；暂停真实接收进程，区分已经到达的数据与真正的网络无进展。"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time

import psutil

from legacy_integration import frame, free_port, receiver


# 日期：2026-11-05；只暂停本测试创建的进程，异常路径先恢复再结束，保留原五秒超时。
def buffered(executable, root, name, packet, expected):
    directory = root / name
    directory.mkdir()
    port = free_port()
    process = receiver(executable, directory, port)
    native = psutil.Process(process.pid)
    paused = False
    started = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
            client.sendall(packet[:8])
            time.sleep(0.25)
            native.suspend()
            paused = True
            client.sendall(packet[8:])
            client.shutdown(socket.SHUT_WR)
            time.sleep(6)
            native.resume()
            paused = False
        output, error = process.communicate(timeout=30)
        events = [json.loads(line) for line in output.splitlines()]
        actual = {"name": name, "expected": expected, "exitCode": process.returncode,
                  "seconds": round(time.monotonic() - started, 3),
                  "lastEvent": events[-1] if events else None, "stderr": error,
                  "pausedSeconds": 6, "receiverTimeoutSeconds": 5}
        actual["passed"] = process.returncode == expected and not error and bool(events)
        if expected == 0:
            target = directory / "buffered.bin"
            actual["contentVerified"] = target.is_file() and target.read_bytes() == b"arrived before resume"
            actual["passed"] = actual["passed"] and actual["contentVerified"]
        else:
            actual["passed"] = actual["passed"] and events[-1].get("stage") == "receive"
        return actual
    finally:
        if paused:
            native.resume()
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


# 日期：2026-11-05；对端保持连接而不补齐帧时，原五秒期限必须继续生效。
def stalled(executable, root, partial):
    name = "partial-stall" if partial else "silent-stall"
    directory = root / name
    directory.mkdir()
    port = free_port()
    process = receiver(executable, directory, port)
    started = time.monotonic()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
            if partial:
                client.sendall(b"\x01\x00\x00")
            output, error = process.communicate(timeout=15)
        events = [json.loads(line) for line in output.splitlines()]
        seconds = time.monotonic() - started
        return {"name": name, "exitCode": process.returncode, "seconds": round(seconds, 3),
                "lastEvent": events[-1] if events else None, "stderr": error,
                "receiverTimeoutSeconds": 5,
                "passed": (process.returncode == 3 and not error and 4.5 <= seconds < 10
                           and events[-1].get("stage") == "transfer")}
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)


# 日期：2026-11-05；失败也写完整证据，不把暂停造成的调度间隙解释为网络超时通过。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    assert not args.report.exists()
    report = {"date": "2026-11-05", "passed": False,
              "executableSha256": hashlib.sha256(Path(executable).read_bytes()).hexdigest(),
              "scriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "cases": []}
    with tempfile.TemporaryDirectory(prefix="dukto-r6-timeout-") as temporary:
        root = Path(temporary)
        report["cases"].append(buffered(executable, root, "buffered-valid",
                                        frame([("buffered.bin", b"arrived before resume")]), 0))
        report["cases"].append(buffered(executable, root, "buffered-invalid-text",
                                        frame([("___DUKTO___TEXT___", b"\xff\xfe")]), 6))
        report["cases"].extend(stalled(executable, root, partial) for partial in (False, True))
    report["passed"] = all(case["passed"] for case in report["cases"])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
