"""日期：2026-11-05；真实 TLS 双向验证 fail，包含批次原样保存、幂等身份及旧服务能力拒绝。"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import uuid
import zipfile

from service_integration import free_port, run
from transfer_integration import digest, transfer
from process_output import JsonOutputDrain


# 日期：2026-11-05；每种方向和并发用独立目录，外部摘要验证不能依赖程序声称成功。
def cases(executable, root, client, shared, channels):
    source = root / f"source-{channels}"
    (source / "资料/empty-dir").mkdir(parents=True)
    (source / "资料/empty-file").touch()
    payload = source / "资料/content.bin"
    payload.write_bytes(bytes(range(251)) * 4099 + b"tail")
    expected = digest(payload)
    result = []
    for direction in ("upload", "download"):
        destination = shared / f"target-{channels}" if direction == "upload" else root / f"output-{channels}"
        destination.mkdir()
        base = (["upload", "--share", "data", "--path", str(source), "--remote-path", destination.name]
                if direction == "upload" else
                ["download", "--share", "data", "--remote-path", source.name, "--output", str(destination)])
        # 日期：2026-11-05；下载源来自共享，和上行源逐字节一致，但名称冲突只在接收端制造。
        if direction == "download":
            import shutil
            shutil.copytree(source, shared / source.name)
        request = str(uuid.uuid4())
        operation = [*base, "--threads", str(channels), "--request-id", request, "--on-conflict", "fail"]
        completed = transfer(executable, client, operation)
        assert completed["conflict"] == "fail" and digest(destination / source.name / "资料/content.bin") == expected
        assert (destination / source.name / "资料/empty-dir").is_dir()
        assert (destination / source.name / "资料/empty-file").stat().st_size == 0
        repeated = transfer(executable, client, operation)
        assert repeated["taskId"] == completed["taskId"] and repeated["conflict"] == "fail"
        changed = operation[:-2]  # 同一请求改回默认策略必须在正文前拒绝。
        assert transfer(executable, client, changed, 6)["code"] == 6
        assert sorted(path.name for path in destination.iterdir()) == [source.name]
        # 日期：2026-11-05；新的同名目录请求必须报冲突，不合并、不添加后缀、不破坏原内容。
        conflicting = [*base, "--threads", str(channels), "--request-id", str(uuid.uuid4()), "--on-conflict", "fail"]
        failure = transfer(executable, client, conflicting, 4)
        assert failure["stage"] == "conflict", failure
        assert digest(destination / source.name / "资料/content.bin") == expected
        assert sorted(path.name for path in destination.iterdir()) == [source.name]
        # 日期：2026-11-05；独立普通文件检查同名文件与同名目录两种类型冲突，始终保护原目标。
        for directory in (False, True):
            leaf_target = destination / ("leaf-dir" if directory else "leaf-file")
            leaf_target.mkdir()
            original = leaf_target / payload.name
            if directory:
                original.mkdir()
                (original / "preserved").write_bytes(b"original")
            else:
                original.write_bytes(b"original")
            leaf = (["upload", "--share", "data", "--path", str(payload), "--remote-path", destination.name + "/" + leaf_target.name]
                    if direction == "upload" else
                    ["download", "--share", "data", "--remote-path", source.name + "/资料/content.bin", "--output", str(leaf_target)])
            failure = transfer(executable, client, [*leaf, "--threads", str(channels), "--on-conflict", "fail"], 4)
            assert failure["stage"] == "conflict"
            assert ((original / "preserved").read_bytes() if directory else original.read_bytes()) == b"original"
            assert sorted(path.name for path in leaf_target.iterdir()) == [payload.name]
        result.append({"direction": direction, "channels": channels, "taskId": completed["taskId"],
                       "sha256": expected, "idempotent": True, "policyChangeRejected": True,
                       "directoryConflict": True, "fileAndTypeConflict": True})
    return result


# 日期：2026-11-05；启动的服务只监听回环，退出时检查 stderr，不把应用失败吞入测试结果。
def start(executable, server, port):
    process = subprocess.Popen([executable, "serve", "start", "--state-directory", str(server),
                                "--bind", "127.0.0.1", "--port", str(port), "--json"],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
    assert json.loads(process.stdout.readline())["event"] == "service-listening"
    process.output_drain = JsonOutputDrain(process.stdout)
    return process


# 日期：2026-11-05；独立新旧服务分别配对，非默认策略不能在旧端静默降级为保留双方。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--old-package")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    report_path = Path(args.report)
    assert not report_path.exists()
    with tempfile.TemporaryDirectory(prefix="dukto-conflict-fail-") as temporary:
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
            error = process.stderr.read()
            assert not error
        invalid = 0
        for command in (["upload", "--on-conflict", "Skip"], ["download", "--on-conflict", "Overwrite"],
                        ["upload", "--on-conflict", "Fail"], ["send", "--on-conflict", "fail"],
                        ["resume", "--on-conflict", "fail"],
                        ["upload", "--on-conflict", "fail", "--on-conflict", "rename"]):
            run(executable, client, command, 2)
            invalid += 1
        old_checked = False
        if args.old_package:
            old = root / "old-cli.exe"
            with zipfile.ZipFile(args.old_package) as archive:
                names = [name for name in archive.namelist() if name.endswith("/dukto-cli.exe")]
                assert len(names) == 1
                old.write_bytes(archive.read(names[0]))
            process = start(str(old), server, port)
            try:
                output = root / "old-output"
                output.mkdir()
                request = ["download", "--share", "data", "--remote-path", "source-1", "--output", str(output), "--on-conflict", "fail"]
                failure = transfer(executable, client, request, 2)
                assert failure["stage"] == "conflict" and not list(output.iterdir())
                old_checked = True
            finally:
                process.kill()
                process.wait(timeout=10)
                process.output_drain.finish()
                error = process.stderr.read()
                assert not error
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps({"date": "2026-11-05", "passed": True,
            "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
            "cases": results, "invalidOptionsRejected": invalid, "oldPeerRefusedBeforeBody": old_checked,
            "scope": "real loopback TLS fail strategy; rename default remains; skip/overwrite/GUI selection and full platform qualification open"}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
