"""日期：2026-11-05；独立小型挂载点上的新版 TLS 中途 ENOSPC，验证文件保护及释放空间后继续使用。"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from limited_filesystem import exhaust
from service_integration import free_port, run
from transfer_faults_integration import failure
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_checkpoint, wait_state


# 日期：2026-11-05；每方向独立元数据、身份与目标，首次已同步块后才填盘，不能把预检查拒绝当作中途故障。
def exercise(executable, mount, capacity, channels, direction, policy):
    with tempfile.TemporaryDirectory(prefix="dukto-parallel-enospc-", dir=mount) as limited, \
            tempfile.TemporaryDirectory(prefix="dukto-parallel-enospc-state-") as temporary:
        root, target = Path(temporary).resolve(), Path(limited).resolve()
        source_directory = root / "source"
        source_directory.mkdir()
        source = source_directory / "preserved.bin"
        size = capacity // 2 + 37
        with source.open("wb") as output:
            remaining = size
            while remaining:
                count = min(256 * 1024, remaining)
                output.write(b"d" * count)
                remaining -= count
        expected = digest(source)
        original = target / source.name
        original.write_bytes(b"existing user data must survive")
        state, client = root / "server", root / "client"
        shared = target if direction == "upload" else source_directory
        identity, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, state, ["serve", "pairing", *rights])
        port = free_port()
        active = None
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as service_events, \
                tempfile.TemporaryFile(mode="w+", encoding="utf-8") as errors:
            server = subprocess.Popen([executable, "serve", "start", "--bind", "127.0.0.1", "--port", str(port),
                                       "--state-directory", str(state), "--json"], stdout=service_events, stderr=errors)
            proxy = SlowProxy(port)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    service_events.seek(0)
                    line = service_events.readline()
                    if line:
                        assert json.loads(line)["event"] == "service-listening"
                        break
                    assert server.poll() is None
                    time.sleep(0.02)
                else:
                    raise AssertionError("Service startup deadline")
                run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}", "--fingerprint", identity["fingerprint"],
                                         "--credential-file", offer["credentialFile"]])
                # 日期：2026-11-05；检查点后冻结有限在途密文，确保填盘早于正文完成；仍由真实内核返回ENOSPC。
                gate = proxy.arm_checkpoint(direction)
                arguments = [direction, "--share", "data", "--threads", str(channels), "--on-conflict", policy]
                arguments += (["--path", str(source)] if direction == "upload" else
                              ["--remote-path", source.name, "--output", str(target)])
                active = TransferProcess(executable, client, arguments)
                task = active.task(120)
                receive_state = state / "service" if direction == "upload" else client / "transfers"
                confirmed = wait_checkpoint(receive_state, task, gate=gate)
                assert active.process.poll() is None and 0 < confirmed < size
                filler = target / "filler"
                print(f"{direction}: durable {confirmed}, exhausting dedicated filesystem", flush=True)
                exhausted = exhaust(filler, capacity)
                filled = exhausted["fillerBytes"]
                assert active.process.poll() is None, "Transfer finished before the disk fault was injected"
                barrier = gate.evidence()
                gate.release()
                failed = failure(active)
                assert failed["code"] == 5, failed
                print(f"{direction}: actual ENOSPC refused publication; releasing filler", flush=True)
                assert original.read_bytes() == b"existing user data must survive"
                assert sorted(path.name for path in target.iterdir() if not path.name.startswith(".dukto-")) == ["filler", source.name]
                retained = list(target.glob(".dukto-*.part"))
                assert len(retained) == 1 and retained[0].stat().st_size > 0
                filler.unlink()
                if direction == "upload":
                    stopped = wait_state(executable, client, task, "failed")
                    assert stopped["error"] == 5, stopped
                    result = transfer(executable, client, arguments)
                    assert result["taskId"] != task
                    recovery = "new request after explicit failed upload"
                else:
                    wait_state(executable, client, task, "interrupted")
                    result = transfer(executable, client, ["resume", "--task", task, "--output", str(target),
                                                           "--threads", str(channels)])
                    assert result["taskId"] == task
                    recovery = "same download task resumed"
                assert result["state"] == "completed" and result["total"] == str(size)
                files = [path for path in target.iterdir() if path.is_file() and not path.name.startswith(".dukto-")]
                if policy == "overwrite":
                    assert files == [original] and digest(original) == expected
                else:
                    copied = [path for path in files if path != original]
                    assert len(files) == 2 and len(copied) == 1 and digest(copied[0]) == expected
                    assert original.read_bytes() == b"existing user data must survive"
                print(f"{direction}: content, original protection and recovery passed", flush=True)
                return {"direction": direction, "channels": channels, "passed": True, "bytes": str(size),
                        "confirmedBeforeFull": confirmed, "fillerBytes": filled, "kernelError": "ENOSPC", "failure": failed,
                        "checkpointGateBeforeRelease": barrier, "exhaustion": exhausted,
                        "retainedPartCountAfterFailure": len(retained), "recovery": recovery, "sha256": expected,
                        "originalPreservedBeforePublication": True, "sameNameOriginalPreserved": policy == "rename",
                        "originalReplacedAfterRecovery": policy == "overwrite", "conflictPolicy": policy}
            finally:
                if active and active.process.poll() is None:
                    active.finish(kill=True)
                proxy.close()
                server.kill()
                server.wait(10)
                errors.seek(0)
                assert not errors.read()


# 日期：2026-11-05；默认保持64MiB；APFS可显式绑定至多512MiB的实际独立挂载容量，不填普通用户盘。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--limited-directory", type=Path, required=True)
    parser.add_argument("--threads", type=int, choices=(1, 4, 16), default=4)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--filesystem-bytes", type=int, default=64 * 1024**2)
    parser.add_argument("--on-conflict", choices=("rename", "overwrite"), default="rename")
    args = parser.parse_args()
    assert os.name == "posix"
    mount = args.limited_directory.resolve()
    filesystem = os.statvfs(mount)
    capacity = filesystem.f_blocks * filesystem.f_frsize
    assert os.path.ismount(mount) and capacity == args.filesystem_bytes
    assert 32 * 1024**2 <= capacity <= 512 * 1024**2
    executable = str(Path(args.executable).resolve())
    cases = [exercise(executable, mount, capacity, args.threads, direction, args.on_conflict) for direction in ("upload", "download")]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps({"date": "2026-11-05", "passed": True, "filesystemBytes": capacity,
        "cases": cases, "platform": os.uname().sysname, "conflictPolicy": args.on_conflict,
        "executableSha256": digest(Path(executable)), "scriptSha256": digest(Path(__file__)),
        "scope": "newer TLS real data and isolated actual ENOSPC on the reported native filesystem; no power-loss or untested operating-system qualification"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Parallel TLS disk-full and recovery passed")


if __name__ == "__main__":
    main()
