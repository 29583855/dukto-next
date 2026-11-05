"""日期：2026-11-05；新版 TLS 的超大文件与十万文件专项，事件和样本流式处理，双端资源固定上限。"""

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
import uuid

import psutil

from large_transfer import digest, sample
from service_integration import free_port, run


# 日期：2026-11-05；独立公式重建每个小文件的期望内容，不保存十万项名称或摘要列表。
def content(index):
    return f"{index}:中文\n".encode("utf-8") if index % 3 else b""


# 日期：2026-11-05；按有界目录分组逐项核验，检查非空/空文件、Unicode 路径和额外项。
def verify_tree(directory, count):
    checked, total = 0, 0
    assert (directory / "空目录").is_dir()
    for index in range(count):
        value = content(index)
        path = directory / f"group-{index // 1000:04d}" / f"文件-{index:06d}.bin"
        assert path.read_bytes() == value, path
        total += len(value)
        checked += 1
    actual = 0
    for parent, _, files in os.walk(directory):
        for name in files:
            assert not name.startswith(".dukto-"), name
            actual += 1
    assert actual == checked == count
    return total


# 日期：2026-11-05；逐行消费固定大小事件片段，只保留最后事件和文件计数；正文、历史和采样不进入增长数组。
def consume(reader, state):
    for _ in range(4):
        data = reader.read(65536)
        if not data:
            return
        state["pending"] += data
        assert len(state["pending"]) <= 131072
        while b"\n" in state["pending"]:
            line, state["pending"] = state["pending"].split(b"\n", 1)
            value = json.loads(line)
            state["last"] = value
            if value["event"] == "file-completed":
                state["fileEvents"] += 1


# 日期：2026-11-05；完整任务有 2 小时总截止，双端以 50ms 采样；大量 stdout 直接落盘并增量读取。
def measured(executable, client, arguments, service, root, label):
    log = root / (label + ".jsonl")
    errors = root / (label + "-stderr.log")
    peaks = {"client": {}, "server": {}}
    state = {"pending": b"", "fileEvents": 0, "last": None}
    started = time.monotonic()
    with log.open("wb") as output, log.open("rb", buffering=0) as reader, errors.open("wb") as error:
        operation = subprocess.Popen([executable, *arguments, "--state-directory", str(client), "--json"], stdout=output, stderr=error)
        try:
            while operation.poll() is None:
                assert time.monotonic() - started < 7200, "scale transfer deadline"
                consume(reader, state)
                sample(operation, peaks["client"])
                sample(service, peaks["server"])
                assert os.fstat(output.fileno()).st_size < 128 * 1024**2
                time.sleep(0.05)
            while reader.tell() < os.fstat(output.fileno()).st_size:
                consume(reader, state)
            assert not state["pending"] and operation.returncode == 0 and os.fstat(error.fileno()).st_size == 0, (operation.returncode, state["last"])
            final = state["last"]
            assert final["event"] == "transfer-completed" and final["state"] == "completed", final
            assert final["bytes"] == final["total"]
            for peak in peaks.values():
                assert peak["rss"] < 512 * 1024**2 and peak["private"] < 512 * 1024**2, peak
                assert peak["threads"] <= 48 and peak["handles"] <= 1024, peak
            return {"result": final, "fileEvents": state["fileEvents"], "seconds": round(time.monotonic() - started, 3),
                    "logBytes": os.fstat(output.fileno()).st_size, "peaks": peaks}
        finally:
            if operation.poll() is None:
                operation.kill()
                operation.wait(10)


# 日期：2026-11-05；只使用测试自有源/共享/目标；大文件上传重试校验后删除源，下载阶段最多保留两份实际数据。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--case", choices=("large", "many"), required=True)
    parser.add_argument("--size", type=int, default=4 * 1024**3 + 131)
    parser.add_argument("--files", type=int, default=100000)
    parser.add_argument("--threads", type=int, choices=(1, 2, 4, 8, 16), default=16)
    parser.add_argument("--require-larger-than-ram", action="store_true")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    assert 1 <= args.files <= 100000 and 1 <= args.size <= 8 * 1024**3
    script_sha = digest(Path(__file__).resolve())
    physical = psutil.virtual_memory().total
    assert not args.require_larger_than_ram or (args.case == "large" and args.size > physical)
    report_path = Path(args.report).resolve()
    assert not report_path.exists(), "Use a new report path"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    executable = str(Path(args.executable).resolve())
    executable_sha = digest(Path(executable))
    # 日期：2026-11-05；长测启动即登记实际二进制/驱动摘要，最终报告保留同一身份，不能事后归给新构建。
    report_path.with_suffix(".inputs.json").write_text(json.dumps({
        "date": "2026-11-05", "executableSha256": executable_sha, "testScriptSha256": script_sha,
        "case": args.case, "files": args.files, "bytesRequested": str(args.size),
        "requestedChannels": args.threads, "physicalMemoryBytes": physical,
        "status": "started", "passed": False}, indent=2) + "\n", encoding="utf-8")
    cache = Path(__file__).resolve().parents[1] / ".cache"
    cache.mkdir(exist_ok=True)
    reserve = 2 * args.size + 2 * 1024**3 if args.case == "large" else 2 * 1024**3
    assert shutil.disk_usage(cache).free >= reserve, "Insufficient two-copy space plus reserve"
    with tempfile.TemporaryDirectory(prefix="parallel-scale-", dir=cache) as temporary:
        root = Path(temporary).resolve()
        assert root.is_relative_to(cache.resolve())
        if os.name == "nt":
            copied = root / "dukto-cli.exe"
            shutil.copyfile(executable, copied)
            executable = str(copied)
        source = root / ("payload.bin" if args.case == "large" else "资料集")
        if args.case == "large":
            with source.open("wb") as output:
                output.truncate(args.size)
                for offset in {0, 2 * 1024**3 - 11, 4 * 1024**3 - 13, args.size - 32}:
                    if 0 <= offset <= args.size - 32:
                        output.seek(offset)
                        output.write(b"dukto-new-protocol-boundary!\n")
            expected = digest(source)
            total = args.size
        else:
            source.mkdir()
            (source / "空目录").mkdir()
            total = 0
            for index in range(args.files):
                directory = source / f"group-{index // 1000:04d}"
                directory.mkdir(exist_ok=True)
                value = content(index)
                (directory / f"文件-{index:06d}.bin").write_bytes(value)
                total += len(value)
            expected = None
        print(f"fixture ready: {args.case}, {total} bytes", flush=True)
        state, client, shared, destination = root / "server", root / "client", root / "shared", root / "received"
        shared.mkdir()
        destination.mkdir()
        original = shared / source.name
        if args.case == "large":
            original.write_bytes(b"preserve server original")
            remote_name, local_name = "payload (2).bin", "payload (2) (2).bin"
            local_original = destination / remote_name
            local_original.write_bytes(b"preserve local original")
        else:
            original.mkdir()
            (original / "original").write_bytes(b"preserve server original")
            remote_name, local_name = "资料集 (2)", "资料集 (2) (2)"
            local_original = destination / remote_name
            local_original.mkdir()
            (local_original / "original").write_bytes(b"preserve local original")
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, state, ["serve", "pairing", *rights])
        port = free_port()
        with (root / "service.jsonl").open("w+b") as output, (root / "service-stderr.log").open("w+b") as errors:
            service = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state), "--bind", "127.0.0.1",
                                        "--port", str(port), "--json"], stdout=output, stderr=errors)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    output.seek(0)
                    line = output.readline()
                    if line:
                        assert json.loads(line)["event"] == "service-listening"
                        break
                    assert service.poll() is None
                    time.sleep(0.02)
                else:
                    raise AssertionError("service startup deadline")
                run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                         "--credential-file", offer["credentialFile"]])
                upload = ["upload", "--share", "data", "--path", str(source), "--threads", str(args.threads), "--request-id", str(uuid.uuid4())]
                sent = measured(executable, client, upload, service, root, "upload")
                remote = shared / remote_name
                assert sent["result"]["channels"] == str(args.threads) and sent["result"]["total"] == str(total)
                if args.case == "large":
                    assert remote.stat().st_size == args.size and digest(remote) == expected
                else:
                    assert verify_tree(remote, args.files) == total
                print("upload and independent content verification passed", flush=True)
                # 日期：2026-11-05；同请求重试包含清单扫描或本地完成重验，使用同一有界驱动和总截止时间。
                retry = measured(executable, client, upload, service, root, "upload-retry")
                assert retry["result"]["taskId"] == sent["result"]["taskId"] and retry["fileEvents"] == 0
                assert sorted(path.name for path in shared.iterdir()) == sorted([source.name, remote_name])
                if args.case == "large":
                    source.unlink()
                download = ["download", "--share", "data", "--remote-path", remote_name, "--output", str(destination),
                            "--threads", str(args.threads), "--request-id", str(uuid.uuid4())]
                received = measured(executable, client, download, service, root, "download")
                local = destination / local_name
                if args.case == "large":
                    assert local.stat().st_size == args.size and digest(local) == expected
                    assert original.read_bytes() == b"preserve server original" and local_original.read_bytes() == b"preserve local original"
                else:
                    assert verify_tree(local, args.files) == total
                    assert (original / "original").read_bytes() == b"preserve server original"
                    assert (local_original / "original").read_bytes() == b"preserve local original"
                assert received["result"]["channels"] == str(args.threads) and received["result"]["total"] == str(total)
                retried = measured(executable, client, download, service, root, "download-retry")
                assert retried["result"]["taskId"] == received["result"]["taskId"] and retried["fileEvents"] == 0
                assert sorted(path.name for path in destination.iterdir()) == sorted([remote_name, local_name])
                assert os.fstat(errors.fileno()).st_size == 0
            finally:
                service.kill()
                service.wait(10)
    report_path.write_text(json.dumps({"date": "2026-11-05", "passed": True, "case": args.case, "bytes": str(total),
        "testScriptSha256": script_sha, "executableSha256": executable_sha,
        "regularFiles": 1 if args.case == "large" else args.files, "sha256": expected, "physicalMemoryBytes": physical,
        "fileLargerThanPhysicalMemory": args.case == "large" and args.size > physical, "requestedChannels": args.threads,
        "sourceRemovedBeforeDownload": args.case == "large", "upload": sent, "uploadRetry": retry,
        "download": received, "downloadRetry": retried, "platform": platform.platform(),
        "scope": "real newer TLS data, selected scale and channel count; loopback and sampled resource bounds, not physical LAN or 24-hour acceptance"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("scale transfer passed", flush=True)


if __name__ == "__main__":
    main()
