"""日期：2026-11-06；真实CLI完整收发最大文本，核对JSON转义、Unicode段边界与有界进程内存。"""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time

from legacy_integration import free_port
from process_sampling import sample


# 日期：2026-11-06； stdout落盘避免大JSON堵塞管道；只等明确的监听事件，进程退出立即报告原错误。
def await_listener(process, output):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if output.stat().st_size:
            with output.open("rb") as stream:
                line = stream.readline()
            if line.endswith(b"\n"):
                event = json.loads(line)
                assert event["event"] == "listening", event
                return
        assert process.poll() is None, (process.returncode, output.read_bytes())
        time.sleep(0.01)
    raise AssertionError("receiver did not publish listening event within 10 seconds")


# 日期：2026-11-06；监控线程只采样，所有异常回传主线程；复用项目既有512MiB资源门槛。
def monitor(processes, stopped, peaks, errors):
    try:
        while not stopped.wait(0.005):
            for name, process in list(processes.items()):
                sample(process, peaks.setdefault(name, {}))
    except Exception as error:
        errors.append(error)


# 日期：2026-11-06；逐行校验所有JSONL，最后正文必须逐字节/摘要一致，不能只核对长度或退出码。
def verify_output(path, payload):
    result = None
    lines = 0
    with path.open("rb") as stream:
        for line in stream:
            assert line.endswith(b"\n")
            result = json.loads(line)
            lines += 1
    assert result is not None and result["event"] == "result" and result["stage"] == "received", list(result or {})
    actual = result["text"].encode("utf-8")
    assert actual == payload
    digest = hashlib.sha256(actual).hexdigest()
    assert digest == hashlib.sha256(payload).hexdigest()
    assert int(result["bytes"]) == len(payload), result.keys()
    return {"jsonLines": lines, "jsonBytes": path.stat().st_size, "bytes": len(payload),
            "sha256": digest, "completeTextVerified": True}


# 日期：2026-11-06；真实发送与接收进程独立配置，资源采样贯穿正文传输和JSON输出直至退出。
def roundtrip(executable, root, name, payload):
    case = root / name
    case.mkdir()
    source = case / "source.txt"
    source.write_bytes(payload)
    received = case / "received"
    received.mkdir()
    port = free_port()
    processes, peaks, errors = {}, {}, []
    stopped = threading.Event()
    observer = threading.Thread(target=monitor, args=(processes, stopped, peaks, errors))
    observer.start()
    try:
        with (case / "receive.jsonl").open("wb") as output, (case / "receive.err").open("wb") as error:
            receiver = subprocess.Popen(
                [executable, "receive", "--bind", "127.0.0.1", "--port", str(port),
                 "--output", str(received), "--state-directory", str(case / "state"),
                 "--once", "--json", "--timeout", "10"], stdout=output, stderr=error)
            processes["receiver"] = receiver
            await_listener(receiver, case / "receive.jsonl")
            with (case / "send.jsonl").open("wb") as sent, (case / "send.err").open("wb") as send_error:
                sender = subprocess.Popen(
                    [executable, "send-text", "--to", "127.0.0.1", "--port", str(port),
                     "--file", str(source), "--json", "--timeout", "10"], stdout=sent, stderr=send_error)
                processes["sender"] = sender
                assert sender.wait(timeout=30) == 0, (case / "send.jsonl").read_bytes()
            assert receiver.wait(timeout=30) == 0, (case / "receive.err").read_bytes()
        assert not (case / "receive.err").read_bytes()
        assert not (case / "send.err").read_bytes()
        sent = [json.loads(line) for line in (case / "send.jsonl").read_bytes().splitlines()]
        assert sent[-1]["event"] == "result" and sent[-1]["receiverVerified"] is False, sent
        result = verify_output(case / "receive.jsonl", payload)
        assert not list(received.iterdir()), "text must not become a truncated file"
    finally:
        stopped.set()
        observer.join(timeout=5)
        assert not observer.is_alive()
        for process in processes.values():
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    assert not errors, errors
    assert peaks.get("receiver") and peaks.get("sender"), peaks
    return {"name": name, **result, "peaks": peaks, "passed": True}


# 日期：2026-11-06；独立恶意对端只声明超限文本，不发送正文；拒绝必须在网络等待和正文分配前。
def oversized_declaration(executable, root):
    case = root / "oversized"
    case.mkdir()
    port = free_port()
    with (case / "receive.jsonl").open("wb") as output, (case / "receive.err").open("wb") as error:
        process = subprocess.Popen(
            [executable, "receive", "--bind", "127.0.0.1", "--port", str(port),
             "--output", str(case), "--state-directory", str(case / "state"), "--once", "--json"],
            stdout=output, stderr=error)
        try:
            await_listener(process, case / "receive.jsonl")
            with socket.create_connection(("127.0.0.1", port), timeout=5) as peer:
                size = 8 * 1024**2 + 1
                peer.sendall(struct.pack("<qq", 1, size) + b"___DUKTO___TEXT___\0" + struct.pack("<q", size))
                assert process.wait(timeout=5) == 2
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    result = json.loads((case / "receive.jsonl").read_bytes().splitlines()[-1])
    assert result["event"] == "error" and "text" not in result, result
    return {"name": "oversized-declaration", "exitCode": 2, "bodySent": False, "passed": True}


# 日期：2026-11-06；输出设备真实写失败必须返回磁盘错误5，JSON及普通文本都不能误报成功。
def failed_output(executable):
    results = []
    with tempfile.TemporaryDirectory(prefix="dukto-output-failure-") as temporary:
        path = Path(temporary) / "read-only-handle"
        path.touch()
        for extra in [[], ["--json"]]:
            # 日期：2026-11-06；只读句柄作为stdout产生真实写失败，三平台均无需特殊设备或信号假设。
            with path.open("rb") as destination:
                result = subprocess.run([executable, "doctor", *extra], stdout=destination,
                                        stderr=subprocess.PIPE, timeout=10)
            assert result.returncode == 5, (extra, result.returncode, result.stderr)
            assert path.stat().st_size == 0
            results.append({"mode": "json" if extra else "text", "exitCode": 5})
    return results


# 日期：2026-11-06；覆盖六倍JSON转义、4096码元处代理对、空文本及超限拒绝；报告仅保存摘要。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert not args.report.exists(), args.report
    report = {"passed": False, "completed": False, "cases": [], "memoryLimitBytes": 512 * 1024**2}
    try:
        with tempfile.TemporaryDirectory(prefix="dukto-text-credit-") as temporary:
            root = Path(temporary)
            controls = bytes([0, 1, 2, 3, 4, 5, 6, 7]) * 1024**2
            unicode = ("x" * 4095 + "🚀\"\\\r\n中文é").encode("utf-8")
            for name, payload in [("maximum-controls", controls), ("unicode-segment", unicode), ("empty", b"")]:
                report["cases"].append(roundtrip(args.executable, root, name, payload))
            report["cases"].append(oversized_declaration(args.executable, root))
            report["outputErrors"] = failed_output(args.executable)
        report.update(passed=True, completed=True)
    finally:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
