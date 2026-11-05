"""日期：2026-11-04；验证独立 CLI 配置生效、参数边界和发现输出，不依赖桌面。"""

import argparse
import json
import os
from pathlib import Path
import socket
import signal
import sqlite3
import struct
import subprocess
import tempfile
import time

from legacy_integration import finish, free_port, frame


# 日期：2026-11-04；Unix 信号实际停止空闲监听和部分接收，检查退出/JSON/临时清理及状态落库。
def receive_signal_contracts(executable, root):
    if os.name == "nt":
        return "not exercised on Windows"
    results = []
    for active, requested in [(False, signal.SIGTERM), (True, signal.SIGINT)]:
        case = root / ("signal-active" if active else "signal-idle")
        output = case / "received"
        output.mkdir(parents=True)
        state = case / "state"
        port = free_port()
        process = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", str(port),
                                    "--output", str(output), "--state-directory", str(state),
                                    "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding="utf-8")
        sender = None
        try:
            assert json.loads(process.stdout.readline())["event"] == "listening"
            if active:
                sender = socket.create_connection(("127.0.0.1", port), timeout=5)
                sender.sendall(struct.pack("<qq", 1, 1024**2) + b"cancelled.bin\0" +
                               struct.pack("<q", 1024**2) + b"x" * (256 * 1024))
                deadline = time.monotonic() + 5
                while not any(p.stat().st_size > 0 for p in output.glob(".dukto-*.part")):
                    if time.monotonic() > deadline:
                        raise AssertionError("receive did not start before cancellation")
                    time.sleep(0.02)
            started = time.monotonic()
            process.send_signal(requested)
            process.wait(timeout=3)
            result = finish(process, 7)[-1]
            assert result["event"] == "error" and result["code"] == 7, result
            assert result["stage"] == "listen", result
            assert not list(output.iterdir())
            if active:
                with sqlite3.connect(state / "receipts.sqlite") as database:
                    rows = database.execute("SELECT state,error FROM tasks").fetchall()
                assert len(rows) == 1 and rows[0][0] == "failed" and "取消" in rows[0][1], rows
            results.append({"activeReceive": active, "signal": requested.name,
                            "seconds": round(time.monotonic() - started, 3),
                            "exitCode": 7, "jsonCancellation": True, "temporaryCleaned": True})
        finally:
            if sender:
                sender.close()
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
        # 日期：2026-11-04；同一状态库的新接收必须可用，不能遗留活任务锁或损坏记录。
        port = free_port()
        process = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", str(port),
                                    "--output", str(output), "--state-directory", str(state),
                                    "--once", "--json"], stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            assert json.loads(process.stdout.readline())["event"] == "listening"
            with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
                sender.sendall(frame([("after-signal.txt", b"restarted correctly")]))
            finish(process, 0)
            assert (output / "after-signal.txt").read_bytes() == b"restarted correctly"
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)
    return results


# 日期：2026-11-04；管道输入验证 EOF、UTF-8、上限、空闲超时及 Unix 的真实中断信号。
def stdin_contracts(executable, config, root):
    for data in [b"", "管道 UTF-8 café 🚀\r\n第二行".encode("utf-8")]:
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = str(reservation.getsockname()[1])
        receiver = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", port,
                                     "--once", "--json", "--output", str(root / "received"),
                                     "--state-directory", str(root / "stdin-state")],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            assert json.loads(receiver.stdout.readline())["event"] == "listening"
            sent = subprocess.run([executable, "send-text", "--config-file", str(config), "--to",
                                   "127.0.0.1", "--port", port, "--file", "-", "--json",
                                   "--non-interactive"], input=data, capture_output=True, timeout=10)
            assert sent.returncode == 0 and not sent.stderr, sent.stdout
            received, error = receiver.communicate(timeout=10)
            assert receiver.returncode == 0 and not error, received
            assert json.loads(received.splitlines()[-1])["text"] == data.decode("utf-8")
        finally:
            if receiver.poll() is None:
                receiver.terminate()
                receiver.wait(timeout=5)
    for data in [b"\xff", b"x" * (8 * 1024**2 + 1)]:
        result = subprocess.run([executable, "send-text", "--to", "127.0.0.1", "--file", "-",
                                 "--json"], input=data, capture_output=True, timeout=10)
        assert result.returncode == 2, result.stdout
    process = subprocess.Popen([executable, "send-text", "--to", "127.0.0.1", "--file", "-",
                                "--timeout", "1", "--json"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        started = time.monotonic()
        process.wait(timeout=4)
        assert process.returncode == 3 and time.monotonic() - started < 3
        assert json.loads(process.stdout.read())["stage"] == "stdin"
        assert not process.stderr.read()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()
        process.stderr.close()
    if os.name != "nt":
        process = subprocess.Popen([executable, "send-text", "--to", "127.0.0.1", "--file", "-",
                                    "--json"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        try:
            time.sleep(0.2)
            process.send_signal(signal.SIGINT)
            process.wait(timeout=3)
            assert process.returncode == 7
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)
            process.stdin.close()
            process.stdout.close()
            process.stderr.close()


# 日期：2026-11-04；命令使用任务独立配置，不改用户已有注册表或 INI。
def run(executable, config, arguments, expected=0):
    result = subprocess.run([executable, "--config-file", str(config), "--json", *arguments],
                            capture_output=True, encoding="utf-8", timeout=15)
    assert result.returncode == expected, (result.returncode, result.stdout, result.stderr)
    assert not result.stderr, result.stderr
    return [json.loads(line) for line in result.stdout.splitlines()]


# 日期：2026-11-04；配置的目录/目标/端口被两个独立进程实际使用，显式错误均返回非零。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    with tempfile.TemporaryDirectory(prefix="dukto-cli-") as temporary:
        root = Path(temporary)
        config = root / "settings.ini"
        output = root / "received"
        output.mkdir()
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = str(reservation.getsockname()[1])
        for key, value in {"output": str(output), "server": "127.0.0.1", "port": port, "timeout": "5", "bind": "127.0.0.1"}.items():
            run(executable, config, ["config", "set", key, value])
        values = run(executable, config, ["config", "show"])[0]["values"]
        assert values["port"] == port
        for key, value in [("port", "65536"), ("timeout", "86401"), ("server", "host:0"), ("bind", "bad"), ("threads", "3")]:
            run(executable, config, ["config", "set", key, value], 2)
        receiver = subprocess.Popen([executable, "receive", "--once", "--json", "--config-file", str(config), "--state-directory", str(root / "state")],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            event = json.loads(receiver.stdout.readline())
            assert event["event"] == "listening" and event["port"] == int(port), event
            source = root / "configured.bin"
            source.write_bytes(b"configuration actually used")
            run(executable, config, ["send", "--path", str(source)])
            text, error = receiver.communicate(timeout=15)
            assert receiver.returncode == 0 and not error, (text, error)
            assert source.read_bytes() == (output / source.name).read_bytes()
            task = json.loads(text.splitlines()[-1])["taskId"]
            receipt = run(executable, config, ["receipts", "show", "--task", task, "--state-directory", str(root / "state")])[0]
            assert receipt["state"] == "completed"
            assert receipt["files"][0]["source"] == "configured.bin"
            assert len(receipt["files"][0]["sha256"]) == 64
        finally:
            if receiver.poll() is None:
                receiver.terminate()
                receiver.wait(timeout=5)
        discovered = run(executable, config, ["discover", "--duration", "1"])
        assert discovered[-1]["event"] == "devices"
        assert isinstance(discovered[-1]["peers"], list)
        run(executable, config, ["discover", "--duration", "0"], 2)
        stdin_contracts(executable, config, root)
        signal_results = receive_signal_contracts(executable, root)
    result = {"date": "2026-11-04", "passed": True,
              "checks": ["isolated INI", "persistent configuration used by send/receive", "port and timeout bounds", "bad endpoint rejection", "discovery JSON", "receipt query", "UTF-8/empty stdin roundtrip", "invalid/oversized stdin rejected", "open stdin idle timeout"],
              "stdinSignalCancellation": "not exercised on Windows" if os.name == "nt" else "SIGINT passed",
              "receiveSignalCancellation": signal_results}
    Path(args.report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
