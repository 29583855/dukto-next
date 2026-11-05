"""日期：2026-11-05；真实 TLS 双向覆盖已存在的文件/目录，离线核对内容、幂等和安全边界。"""

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid
import zipfile

from conflict_fail_integration import start
from service_integration import free_port, run
from transfer_integration import digest, transfer


# 日期：2026-11-05；每个方向和通道用独立目录，跨两个16项窗口并包含空项/Unicode/多块大文件。
def cases(executable, root, client, shared, channels):
    source = root / f"source-{channels}"
    (source / "资料/空目录").mkdir(parents=True)
    (source / "资料/空文件").touch()
    payload = source / "资料/content.bin"
    with payload.open("wb") as output:
        for index in range(33):
            output.write(bytes([index]) * (256 * 1024))
        output.write(b"tail")
    for index in range(35):
        (source / f"file-{index:02}.bin").write_bytes(bytes([index + 1]) * (index * 137 + 1))
    expected = {path.relative_to(source): digest(path) for path in source.rglob("*") if path.is_file()}
    shutil.copytree(source, shared / source.name)
    results = []
    for direction in ("upload", "download"):
        destination = shared / f"target-{channels}" if direction == "upload" else root / f"output-{channels}"
        destination.mkdir()
        received = destination / source.name
        (received / "资料/空目录").mkdir(parents=True)
        (received / "unrelated").write_bytes(b"preserve unrelated target")
        for relative in expected:
            (received / relative).write_bytes(b"original:" + str(relative).encode("utf-8"))
        base = (["upload", "--share", "data", "--path", str(source), "--remote-path", destination.name]
                if direction == "upload" else
                ["download", "--share", "data", "--remote-path", source.name, "--output", str(destination)])
        operation = [*base, "--threads", str(channels), "--request-id", str(uuid.uuid4()),
                     "--on-conflict", "overwrite"]
        completed = transfer(executable, client, operation)
        assert completed["conflict"] == "overwrite"
        assert all(digest(received / path) == sha for path, sha in expected.items())
        assert (received / "unrelated").read_bytes() == b"preserve unrelated target"
        assert (received / "资料/空目录").is_dir()
        repeated = transfer(executable, client, operation)
        assert repeated["taskId"] == completed["taskId"] and repeated["conflict"] == "overwrite"
        assert transfer(executable, client, operation[:-1] + ["fail"], 6)["code"] == 6
        assert sorted(path.name for path in destination.iterdir()) == [source.name]
        assert not [path for path in received.rglob("*") if path.name.startswith(".dukto-")]
        for target_type in ("directory", "readonly", "link"):
            if target_type == "link" and os.name == "nt":
                continue  # 原生重解析点由 Windows 路径专项核验；不要求提升权限创建 symlink。
            leaf = destination / ("leaf-" + target_type)
            leaf.mkdir()
            original = leaf / payload.name
            outside = root / f"outside-{channels}-{direction}"
            if target_type == "directory":
                original.mkdir()
                (original / "preserved").write_bytes(b"original")
            elif target_type == "link":
                outside.write_bytes(b"original")
                original.symlink_to(outside)
            else:
                original.write_bytes(b"original")
                original.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
            arguments = (["upload", "--share", "data", "--path", str(payload),
                          "--remote-path", destination.name + "/" + leaf.name]
                         if direction == "upload" else
                         ["download", "--share", "data", "--remote-path", source.name + "/资料/content.bin",
                          "--output", str(leaf)])
            try:
                failure = transfer(executable, client,
                                   [*arguments, "--threads", str(channels), "--on-conflict", "overwrite"], 4)
                assert failure["stage"] in ("conflict", "path"), failure
                assert ((original / "preserved").read_bytes() if original.is_dir() else original.read_bytes()) == b"original"
                assert sorted(path.name for path in leaf.iterdir()) == [payload.name]
            finally:
                if target_type == "readonly":
                    original.chmod(stat.S_IRUSR | stat.S_IWUSR)
        results.append({"direction": direction, "channels": channels, "taskId": completed["taskId"],
                        "files": len(expected), "payloadSha256": expected[Path("资料/content.bin")],
                        "existingDirectoryMerged": True, "unrelatedPreserved": True,
                        "idempotent": True, "policyChangeRejected": True,
                        "typeAndReadonlyRefused": True, "symlinkRefused": os.name != "nt"})
    return results


# 日期：2026-11-05；只监听回环，服务持续排空输出；可选真实旧包必须在任何正文之前拒绝覆盖。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--old-package")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report = Path(args.report)
    assert not report.exists()
    with tempfile.TemporaryDirectory(prefix="dukto-overwrite-") as temporary:
        root = Path(temporary)
        server, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        info, _ = run(executable, server, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, server, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, server, ["serve", "pairing", *rights])
        port = free_port()
        process = start(executable, server, port)
        results = []
        try:
            run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels in (1, 4, 16):
                results.extend(cases(executable, root, client, shared, channels))
        finally:
            process.kill()
            process.wait(timeout=10)
            process.output_drain.finish()
            assert not process.stderr.read()
        old_checked = False
        if args.old_package:
            old = root / "old-cli.exe"
            with zipfile.ZipFile(args.old_package) as archive:
                name, = [name for name in archive.namelist() if name.endswith("/dukto-cli.exe")]
                old.write_bytes(archive.read(name))
            process = start(str(old), server, port)
            try:
                output = root / "old-output"
                output.mkdir()
                for direction in ("upload", "download"):
                    arguments = (["upload", "--share", "data", "--path", str(root / "source-1")]
                                 if direction == "upload" else
                                 ["download", "--share", "data", "--remote-path", "source-1", "--output", str(output)])
                    failure = transfer(executable, client, [*arguments, "--on-conflict", "overwrite"], 2)
                    assert failure["stage"] == "conflict" and not list(output.iterdir())
                old_checked = True
            finally:
                process.kill()
                process.wait(timeout=10)
                process.output_drain.finish()
                assert not process.stderr.read()
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"date": "2026-11-05", "passed": True,
            "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
            "cases": results, "oldPeerRefusedBeforeBody": old_checked,
            "scope": "real TLS loopback overwrite; native crash/reservation tests separate; physical LAN, disk-full, R6 policy and complete product qualification remain open"},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
