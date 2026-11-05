"""日期：2026-11-04；独立管理/服务/客户端进程验证实际上传、下载、目录映射及请求幂等。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import tempfile
import time
import uuid

from process_output import timeout_evidence
from service_integration import free_port, run


# 日期：2026-11-04；流式散列真实文件，校验不依赖应用报告的摘要或成功状态。
def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        while part := source.read(256 * 1024):
            result.update(part)
    return result.hexdigest()


# 日期：2026-11-05；默认 90 秒不变；超时保留有界事件证据，完成仍要求真实退出和最终确认。
def transfer(executable, state, arguments, expected=0, timeout=90):
    started = time.monotonic()
    try:
        result = subprocess.run([executable, *arguments, "--state-directory", str(state), "--json"],
                                capture_output=True, encoding="utf-8", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise AssertionError(json.dumps(timeout_evidence(error, timeout, time.monotonic() - started),
                                        ensure_ascii=False)) from error
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == expected and not result.stderr, (result.returncode, events, result.stderr)
    assert events and events[0]["event"] == "transfer-started", events
    if expected == 0:
        assert events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed", events
        assert events[-1]["bytes"] == events[-1]["total"], events
    else:
        assert not any(event.get("event") == "transfer-completed" for event in events), events
    return events[-1]


# 日期：2026-11-04；测试目录仅包含自有状态/样本，端口只监听回环，凭据不写入验证报告。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--threads", type=int, default=1)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    with tempfile.TemporaryDirectory(prefix="dukto-transfer-") as temporary:
        root = Path(temporary).resolve()
        server, client = root / "server", root / "client"
        shared = root / "shared"
        shared.mkdir()
        bundle = root / "bundle"
        (bundle / "资料/empty-dir").mkdir(parents=True)
        (bundle / "资料/empty-file").touch()
        (bundle / "资料/text.txt").write_text("跨平台传输\n", encoding="utf-8")
        payload = bundle / "data.bin"
        payload.write_bytes(b"x" * (8 * 1024 * 1024) + b"tail" * 9 + b"!")
        expected = digest(payload)
        # 日期：2026-11-04；跨越三个 16 项窗口，含零字节项和不同尾块，逐文件核对窗口切换没有串号。
        for index in range(35):
            (bundle / f"window-{index:02}.bin").write_bytes(bytes([index]) * (index * 71))
        window_files = {path.name: digest(path) for path in bundle.glob("window-*.bin")}
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        run(executable, server, ["serve", "share", "add", "--share", "data", "--path", str(shared),
                                 "--allow-browse", "--allow-download", "--allow-upload"])
        offer, _ = run(executable, server, ["serve", "pairing", "--share", "data", "--allow-browse",
                                           "--allow-download", "--allow-upload"])
        port = free_port()
        process = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                    "--state-directory", str(server), "--timeout", "10", "--json"],
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            assert json.loads(process.stdout.readline())["event"] == "service-listening"
            paired, _ = run(executable, client, ["pair", "--to", f"127.0.0.1:{port}",
                                                 "--fingerprint", info["fingerprint"],
                                                 "--credential-file", offer["credentialFile"]])
            upload_request = str(uuid.uuid4())
            upload = ["upload", "--share", "data", "--path", str(bundle), "--request-id", upload_request, "--threads", str(args.threads)]
            sent = transfer(executable, client, upload)
            assert digest(shared / "bundle/data.bin") == expected
            assert (shared / "bundle/资料/empty-dir").is_dir()
            assert (shared / "bundle/资料/empty-file").stat().st_size == 0
            assert (shared / "bundle/资料/text.txt").read_bytes() == (bundle / "资料/text.txt").read_bytes()
            assert all(digest(shared / "bundle" / name) == sha for name, sha in window_files.items())
            repeated = transfer(executable, client, upload)
            assert repeated["taskId"] == sent["taskId"] and sorted(p.name for p in shared.iterdir()) == ["bundle"]
            with payload.open("r+b") as changed:
                changed.write(b"changed")
            transfer(executable, client, upload, 6)
            assert digest(shared / "bundle/data.bin") == expected
            output = root / "output"
            (output / "bundle/original").mkdir(parents=True)
            download_request = str(uuid.uuid4())
            download = ["download", "--share", "data", "--remote-path", "bundle", "--output", str(output),
                        "--request-id", download_request, "--threads", str(args.threads)]
            received = transfer(executable, client, download)
            assert digest(output / "bundle (2)/data.bin") == expected
            assert (output / "bundle (2)/资料/empty-dir").is_dir() and (output / "bundle/original").is_dir()
            assert all(digest(output / "bundle (2)" / name) == sha for name, sha in window_files.items())
            again = transfer(executable, client, download)
            assert again["taskId"] == received["taskId"]
            assert sorted(p.name for p in output.iterdir()) == ["bundle", "bundle (2)"]
            # 日期：2026-11-04；完成重试缺少日志必须拒绝，不能重建接收日志或生成新的空目录/副本。
            for prefix in ("receive", "download"):
                log = client / "transfers" / f"{prefix}-{received['taskId']}.sqlite"
                saved = log.with_suffix(".saved")
                log.rename(saved)
                try:
                    transfer(executable, client, download, 6)
                    assert not log.exists()
                    assert sorted(p.name for p in output.iterdir()) == ["bundle", "bundle (2)"]
                    assert digest(output / "bundle (2)/data.bin") == expected
                finally:
                    saved.rename(log)
            other = root / "other-output"
            other.mkdir()
            transfer(executable, client, [*download, "--output", str(other)], 6)
            page, _ = run(executable, client, ["tasks"])
            assert {task["taskId"] for task in page["tasks"]} == {sent["taskId"], received["taskId"]}
            assert not page["more"] and all("root" not in task for task in page["tasks"])
            run(executable, server, ["serve", "grant", "--client", paired["client"], "--share", "data", "--allow-browse"])
            transfer(executable, client, ["upload", "--share", "data", "--path", str(bundle)], 4)
            transfer(executable, client, ["download", "--share", "data", "--output", str(other)], 4)
            page, _ = run(executable, client, ["tasks"])
            assert page["tasks"] == []
            # 日期：2026-11-06；只匹配TemporaryManifest的UUID名称及SQLite附属文件，持久处置日志必须保留。
            temporary_name = re.compile(r"upload-[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\.sqlite(?:-wal|-shm|-journal)?")
            assert not [path for path in (client / "transfers").glob("upload-*.sqlite*")
                        if temporary_name.fullmatch(path.name)], "source scan libraries accumulated"
            assert (client / "transfers" / f"upload-disposition-{sent['taskId']}.sqlite").is_file()
            assert process.poll() is None
        finally:
            if process.poll() is None:
                if os.name == "nt":
                    process.kill()
                else:
                    process.send_signal(signal.SIGTERM)
            out, err = process.communicate(timeout=10)
            assert not err, err
        report = {"date": "2026-11-04", "passed": True, "payloadSha256": expected,
                  "checks": ["real authenticated upload and download", "8MiB+37 bytes", "Unicode and empty files/directories",
                             "35 additional files cross three bounded receive windows with per-file hashes",
                             "directory keep-both mapping", "same request does not duplicate", "changed upload content refused",
                             "completed retry without local manifest/log refused without new files",
                             "download destination rebinding refused", "read/upload grants enforced", "owned task list and revoked filtering", "normal upload scan libraries reclaimed"],
                  "channelsRequested": args.threads, "scope": "authenticated CLI with selected channels; GUI, restart/fault and full platform matrix require separate validation"}
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    Path(args.report).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
