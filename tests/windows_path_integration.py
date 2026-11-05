"""日期：2026-11-04；验证真实 Windows 目录固定及 junction 拒绝，不操作用户目录。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import time

from legacy_integration import finish, free_port, frame, receiver


# 日期：2026-11-04；传输暂停在中间片段时尝试改名父目录，完成后同一改名必须恢复可用。
def pinned_receive(executable, root):
    output = root / "received"
    output.mkdir()
    port = free_port()
    process = receiver(executable, output, port)
    payload = bytes(range(256)) * 8193
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            sender.sendall(struct.pack("<qq", 2, len(payload)) + b"tree\0" + struct.pack("<q", -1) +
                           b"tree/payload.bin\0" + struct.pack("<q", len(payload)) + payload[:262144])
            parent = output / "tree"
            deadline = time.monotonic() + 5
            while not any(path.stat().st_size > 0 for path in parent.glob("*.part")):
                if time.monotonic() > deadline:
                    raise AssertionError("receiver did not create a partial file")
                time.sleep(0.02)
            try:
                parent.rename(root / "moved")
            except PermissionError:
                pass
            else:
                raise AssertionError("active receive directory was replaced")
            sender.sendall(payload[262144:])
        finish(process, 0)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert (parent / "payload.bin").read_bytes() == payload
    assert not list(parent.glob("*.part"))
    parent.rename(root / "moved")
    assert (root / "moved/payload.bin").read_bytes() == payload
    return {"passed": True, "renameDuringReceiveDenied": True, "renameAfterReceiveAllowed": True,
            "sha256": hashlib.sha256(payload).hexdigest()}


# 日期：2026-11-04；仅在专用临时目录创建 junction，接收根经过它时必须明确拒绝。
def rejects_junction(executable, root):
    outside = root / "outside"
    outside.mkdir()
    marker = outside / "marker"
    marker.write_bytes(b"do not change")
    junction = root / "junction"
    # 日期：2026-11-04；PowerShell 字符串按单引号规则转义，不将路径拼成可执行表达式。
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = ("$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path " + quote(junction) +
               " -Target " + quote(outside) + " | Out-Null")
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                   capture_output=True, check=True, timeout=15)
    port = free_port()
    process = receiver(executable, junction, port)
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sender:
            sender.sendall(frame([("escaped.bin", b"must not escape")]))
        events = finish(process, 4)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
    assert events[-1]["stage"] == "path", events
    assert marker.read_bytes() == b"do not change"
    assert not (outside / "escaped.bin").exists()
    assert not list(outside.glob("*.part"))
    source_checks = []
    for label, selected in [("junctionRoot", junction), ("nestedJunction", root),
                            ("pathThroughJunction", junction / "marker")]:
        sent = subprocess.run([executable, "send", "--to", "127.0.0.1:" + str(free_port()),
                               "--path", str(selected), "--timeout", "1", "--json"],
                              capture_output=True, encoding="utf-8", timeout=10)
        assert sent.returncode == 4 and not sent.stderr, (label, sent.returncode, sent.stdout, sent.stderr)
        result = json.loads(sent.stdout.splitlines()[-1])
        assert result["stage"] in ("scan", "path"), result
        source_checks.append({"case": label, "exitCode": 4, "stage": result["stage"],
                              "rejectedBeforeConnect": True})
    junction.rmdir()
    return {"passed": True, "receiverExitCode": 4, "outsidePreserved": True,
            "sourceReparseChecks": source_checks}


# 日期：2026-11-04；Windows 专项只建立自己拥有的数据，junction 在递归清理前显式移除。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise RuntimeError("Windows native path validation requires Windows")
    executable = str(Path(args.executable).resolve())
    with tempfile.TemporaryDirectory(prefix="dukto-windows-path-") as temporary:
        root = Path(temporary)
        report = {"date": "2026-11-04", "pinnedReceive": pinned_receive(executable, root),
                  "junction": rejects_junction(executable, root), "passed": True}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
