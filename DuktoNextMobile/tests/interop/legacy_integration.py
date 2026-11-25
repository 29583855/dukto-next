"""日期：2026-11-04；使用独立 socket 样本与真实子进程验证 R6 线格式和异常行为。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time


# 日期：2026-11-04；为本机测试分配空闲端口，避免占用原版 4644。
def free_port():
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        return server.getsockname()[1]


# 日期：2026-11-04；精确读取独立协议样本，发现提前关闭立即失败。
def read_exact(stream, count):
    data = bytearray()
    while len(data) < count:
        block = stream.recv(count - len(data))
        if not block:
            raise RuntimeError("unexpected EOF")
        data.extend(block)
    return bytes(data)


# 日期：2026-11-04；启动真正的接收程序，并等待其明确发布监听事件。
def receiver(executable, directory, port, address="127.0.0.1"):
    process = subprocess.Popen(
        [executable, "receive", "--bind", address, "--port", str(port),
         "--output", str(directory), "--once", "--json", "--timeout", "5", "--state-directory", str(directory / ".state")],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
    )
    event = json.loads(process.stdout.readline())
    if event.get("event") != "listening":
        raise RuntimeError(event)
    return process


# 日期：2026-11-04；收集最终退出码与 JSON 行，不以文件存在代替成功结果。
def finish(process, expected, case=None):
    output, error = process.communicate(timeout=30)
    if process.returncode != expected:
        raise AssertionError((case, process.returncode, output, error))
    events = [json.loads(line) for line in output.splitlines()]
    if error.strip():
        raise AssertionError(error)
    return events


# 日期：2026-11-04；独立构造 R6 帧，不复用被测 C++ 的序列化实现。
def frame(entries):
    total = sum(len(data) for _, data in entries if data is not None)
    result = struct.pack("<qq", len(entries), total)
    for name, data in entries:
        result += name.encode("utf-8") + b"\0" + struct.pack("<q", -1 if data is None else len(data))
        if data is not None:
            result += data
    return result


# 日期：2026-11-04；验证发送端与独立解码器兼容，包括小端长度和 UTF-8 文件名。
def sender_fixture(executable, root):
    path = root / "中文 sample.bin"
    payload = os.urandom(1024 * 1024 + 19)
    path.write_bytes(payload)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(10)
        process = subprocess.Popen(
            [executable, "send", "--to", "127.0.0.1", "--port", str(server.getsockname()[1]),
             "--path", str(path), "--json"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
        )
        with server.accept()[0] as client:
            client.settimeout(10)
            assert struct.unpack("<qq", read_exact(client, 16)) == (1, len(payload))
            name = bytearray()
            while True:
                byte = read_exact(client, 1)
                if byte == b"\0":
                    break
                name.extend(byte)
            assert name.decode("utf-8") == path.name
            assert struct.unpack("<q", read_exact(client, 8))[0] == len(payload)
            assert hashlib.sha256(read_exact(client, len(payload))).digest() == hashlib.sha256(payload).digest()
            assert client.recv(1) == b""
        events = finish(process, 0)
        assert events[-1]["receiverVerified"] is False


# 日期：2026-11-04；故意把包头拆成单字节，覆盖空文件和目录以及不覆盖已有文件。
def receiver_fixtures(executable, root):
    out = root / "received"
    out.mkdir()
    (out / "keep.txt").write_bytes(b"old")
    entries = [("keep.txt", b"new"), ("目录", None), ("目录/empty", None), ("目录/zero", b"")]
    port = free_port()
    process = receiver(executable, out, port)
    with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
        for byte in frame(entries):
            client.sendall(bytes([byte]))
    finish(process, 0)
    assert (out / "keep.txt").read_bytes() == b"old"
    assert (out / "keep (2).txt").read_bytes() == b"new"
    assert (out / "目录/empty").is_dir()
    assert (out / "目录/zero").read_bytes() == b""
    for name, packet, expected in [
        ("truncated", frame([("partial.bin", b"abcdef")])[:-3], 3),
        ("traversal", frame([("../escaped", b"data")]), 4),
        ("negative", struct.pack("<qq", -1, 10), 2),
        ("wrong-total", struct.pack("<qq", 1, 9) + b"x\0" + struct.pack("<q", 10), 2),
        ("duplicate", frame([("duplicate.txt", b"one"), ("duplicate.txt", b"two")]), 2),
        ("case-collision", frame([("Case", None), ("case", None)]), 2),
        ("invalid-text", frame([("___DUKTO___TEXT___", b"\xff\xfe")]), 6),
    ]:
        port = free_port()
        process = receiver(executable, out, port)
        with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
            client.sendall(packet)
        finish(process, expected, name)
        assert not (out / "partial.bin").exists(), name
        assert not list(out.glob("*.part")), name
        assert not (root / "escaped").exists(), name


# 日期：2026-11-04；独立验证文本哨兵必须包含第 19 字节的 NUL，覆盖中文与空文本。
def text_wire_roundtrip(executable, root):
    for payload in ["中文\nUnicode café 🚀".encode("utf-8"), b""]:
        source = root / "text.txt"
        source.write_bytes(payload)
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            server.settimeout(10)
            process = subprocess.Popen([executable, "send-text", "--to", "127.0.0.1", "--port", str(server.getsockname()[1]), "--file", str(source), "--json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            with server.accept()[0] as client:
                client.settimeout(10)
                assert struct.unpack("<qq", read_exact(client, 16)) == (1, len(payload))
                assert read_exact(client, 19) == b"___DUKTO___TEXT___\0"
                assert struct.unpack("<q", read_exact(client, 8))[0] == len(payload)
                assert read_exact(client, len(payload)) == payload
                assert client.recv(1) == b""
            finish(process, 0)
        port = free_port()
        received = receiver(executable, root, port)
        with socket.create_connection(("127.0.0.1", port), timeout=10) as client:
            client.sendall(frame([("___DUKTO___TEXT___", payload)]))
        events = finish(received, 0)
        assert events[-1]["text"] == payload.decode("utf-8")


# 日期：2026-11-04；两个独立 CLI 完成真实目录传输，测试双方工作线程与进程退出。
def cli_roundtrip(executable, root):
    source = root / "source"
    source.mkdir()
    (source / "empty").mkdir()
    (source / "a.bin").write_bytes(os.urandom(2 * 1024 * 1024 + 3))
    (source / "zero").touch()
    output = root / "roundtrip"
    output.mkdir()
    port = free_port()
    process = receiver(executable, output, port)
    sender = subprocess.run(
        [executable, "send", "--to", "127.0.0.1", "--port", str(port), "--path", str(source), "--json"],
        capture_output=True, encoding="utf-8", timeout=30
    )
    assert sender.returncode == 0, (sender.stdout, sender.stderr)
    finish(process, 0)
    assert (output / "source/empty").is_dir()
    for file in source.iterdir():
        if file.is_file():
            assert file.read_bytes() == (output / "source" / file.name).read_bytes()


# 日期：2026-11-04；使用真实 IPv6 回环监听和括号目标地址，核对传输内容及来源地址。
def ipv6_roundtrip(executable, root):
    with socket.socket(socket.AF_INET6) as reservation:
        reservation.bind(("::1", 0))
        port = reservation.getsockname()[1]
    source = root / "ipv6.bin"
    source.write_bytes(os.urandom(256 * 1024 + 7))
    output = root / "ipv6-received"
    output.mkdir()
    process = receiver(executable, output, port, "::1")
    try:
        sender = subprocess.run([executable, "send", "--to", f"[::1]:{port}", "--path",
                                 str(source), "--json"], capture_output=True, timeout=10)
        assert sender.returncode == 0 and not sender.stderr, sender.stdout
        result = finish(process, 0)[-1]
        assert result["peer"] == "::1"
        assert source.read_bytes() == (output / source.name).read_bytes()
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


# 日期：2026-11-04；每个场景使用独立临时目录并留下可追溯结果。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report")
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="dukto-integration-") as temporary:
        root = Path(temporary)
        for test in [sender_fixture, receiver_fixtures, text_wire_roundtrip, cli_roundtrip, ipv6_roundtrip]:
            start = time.monotonic()
            test(args.executable, root)
            results.append({"test": test.__name__, "passed": True, "seconds": round(time.monotonic() - start, 3)})
    report = json.dumps(results, ensure_ascii=False, indent=2)
    print(report)
    if args.report:
        Path(args.report).write_text(report + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
