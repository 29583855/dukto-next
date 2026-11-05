"""日期：2026-11-04；真实接收期间替换 POSIX 目录，验证不跟随链接且在原目录清理临时项。"""

import argparse
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

from legacy_integration import finish, free_port, frame


# 日期：2026-11-04；状态库位于接收根之外，目录改名不会改变被测任务的所有权记录。
def receiver(executable, output, state, port):
    process = subprocess.Popen([executable, "receive", "--bind", "127.0.0.1", "--port", str(port),
                                "--output", str(output), "--state-directory", str(state),
                                "--once", "--timeout", "5", "--json"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding="utf-8")
    assert json.loads(process.stdout.readline())["event"] == "listening"
    return process


# 日期：2026-11-04；只在可观察的已写片段出现后进行替换，不能用尚未开始的接收充当竞争测试。
def wait_partial(directory):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if any(path.stat().st_size >= 256 * 1024 for path in directory.glob(".dukto-*.part")):
            return
        time.sleep(0.02)
    raise AssertionError("receiver did not write the first fragment")


# 日期：2026-11-04；分别替换整个输出根和批次子目录，外部目标及已存在文件必须保持原样。
def replace_during_receive(executable, root, nested):
    output = root / "output"
    outside = root / "outside"
    state = root / "state"
    output.mkdir()
    outside.mkdir()
    (outside / "preserved.txt").write_bytes(b"must survive")
    port = free_port()
    process = receiver(executable, output, state, port)
    parent = output / "tree" if nested else output
    moved = root / "moved"
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            size = 2 * 1024**2
            name = b"tree/payload.bin" if nested else b"payload.bin"
            directory = b"tree\0" + struct.pack("<q", -1) if nested else b""
            sender.sendall(struct.pack("<qq", 2 if nested else 1, size) + directory + name +
                           b"\0" + struct.pack("<q", size) + b"p" * (256 * 1024))
            wait_partial(parent)
            parent.rename(moved)
            parent.symlink_to(outside, target_is_directory=True)
            try:
                sender.sendall(b"p" * (size - 256 * 1024))
            except (BrokenPipeError, ConnectionResetError):
                pass
        result = finish(process, 4)[-1]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert result["stage"] == "path", result
    assert sorted(path.name for path in outside.iterdir()) == ["preserved.txt"]
    assert (outside / "preserved.txt").read_bytes() == b"must survive"
    assert not list(moved.iterdir()), list(moved.iterdir())
    parent.unlink()
    moved.rename(parent)
    port = free_port()
    process = receiver(executable, output, state, port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            sender.sendall(frame([("after-replacement.txt", b"recovered")]))
        finish(process, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert (output / "after-replacement.txt").read_bytes() == b"recovered"
    return {"passed": True, "receiverExitCode": 4, "outsidePreserved": True,
            "temporaryCleanedInMovedDirectory": True, "nextReceivePassed": True}


# 日期：2026-11-04；输出根本身为符号链接时也必须明确拒绝，不能在 canonicalize 后绕过边界。
def reject_link_root(executable, root):
    outside = root / "outside"
    outside.mkdir()
    output = root / "link"
    output.symlink_to(outside, target_is_directory=True)
    port = free_port()
    process = receiver(executable, output, root / "state", port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            sender.sendall(frame([("forbidden.txt", b"not allowed")]))
        result = finish(process, 4)[-1]
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert result["stage"] == "path", result
    assert not list(outside.iterdir())
    return {"passed": True, "receiverExitCode": 4, "outsideUntouched": True}


# 日期：2026-11-04；所有链接与改名只发生在新建临时目录内，不操作用户已有目录。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if os.name != "posix":
        raise RuntimeError("this test requires a POSIX platform")
    executable = str(Path(args.executable).resolve())
    with tempfile.TemporaryDirectory(prefix="dukto-posix-path-") as temporary:
        root = Path(temporary).resolve()
        report = {"date": "2026-11-04", "passed": True}
        for name, nested in [("outputRootReplacement", False), ("subdirectoryReplacement", True)]:
            case = root / name
            case.mkdir()
            report[name] = replace_during_receive(executable, case, nested)
        case = root / "symlinkRoot"
        case.mkdir()
        report["symlinkRoot"] = reject_link_root(executable, case)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
