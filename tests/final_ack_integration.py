"""日期：2026-11-05；真实 TLS 最终任务确认丢失后重试，按服务已同步完成状态切断不透明代理。"""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import threading
import time
import uuid

from service_integration import free_port, run
from disposition_transfer_integration import verify_journal
from transfer_integration import digest, transfer
from transfer_recovery_integration import SlowProxy, TransferProcess
from transfer_faults_integration import failure
from transfer_retry_integration import finish


class FinalAckProxy(SlowProxy):
    # 日期：2026-11-05；仅依据测试自有任务库和目标文件触发；不解密 TLS，也不修改应用的生产提交顺序。
    def __init__(self, target, database):
        self.database = database
        self.final = None
        self.task = None
        self.dropped = threading.Event()
        self.dropped_bytes = 0
        self.completed_snapshot = None
        self.armed = False
        super().__init__(target)

    # 日期：2026-11-05；父类按固定次序建立双向转发，目标服务 socket 的远端端口用于识别响应方向。
    def completed(self, source):
        if not self.armed or not self.final or not self.final.exists() or not self.task:
            return False
        try:
            if source.getpeername()[1] != self.target:
                return False
            with closing(sqlite3.connect(f"{self.database.as_uri()}?mode=ro", uri=True, timeout=0.1)) as database:
                row = database.execute("SELECT state,processed,total FROM tasks WHERE id=?", (self.task,)).fetchone()
            if row and row[0] == "completed" and row[1] == row[2]:
                self.completed_snapshot = {"state": row[0], "bytes": row[1], "total": row[2]}
                return True
        except (OSError, sqlite3.OperationalError):
            return False
        return False

    # 日期：2026-11-05；服务完成事务先于最终响应发送；响应转发前重读事务并丢弃该加密片段，确保客户未获确认。
    def pump(self, source, destination):
        try:
            while not self.stopped.is_set():
                data = source.recv(16384)
                if not data:
                    break
                if self.completed(source):
                    self.armed = False
                    self.dropped_bytes += len(data)
                    self.dropped.set()
                    try:
                        source.shutdown(socket.SHUT_RDWR)
                        destination.shutdown(socket.SHUT_RDWR)
                    except OSError:
                        pass
                    return
                destination.sendall(data)
        except OSError:
            pass
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass


# 日期：2026-11-05；六个用例均执行真实首次传输和同请求重试，按原策略验证同名保护或原子覆盖及无重复副本。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--auto-retries", type=int, choices=(0, 3), default=0)
    # 日期：2026-11-05；包内运行保持 EXE 与依赖相邻，开发目录默认复制避免构建文件占用。
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--on-conflict", choices=("rename", "overwrite"), default="rename")
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    executable_sha = digest(Path(executable))
    cases = []
    with tempfile.TemporaryDirectory(prefix="dukto-final-ack-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt" and not args.in_place:
            local = root / "dukto-cli.exe"
            shutil.copyfile(executable, local)
            executable = str(local)
        state, client, shared = root / "server", root / "client", root / "shared"
        shared.mkdir()
        sample = root / "source.bin"
        with sample.open("wb") as output:
            for index in range(32):
                output.write(bytes([index]) * (256 * 1024))
            output.write(b"final-confirmation-tail")
        expected = digest(sample)
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *rights])
        offer, _ = run(executable, state, ["serve", "pairing", *rights])
        port = free_port()
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as service_output, tempfile.TemporaryFile(mode="w+", encoding="utf-8") as service_error:
            service = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state), "--bind", "127.0.0.1",
                                        "--port", str(port), "--json"], stdout=service_output, stderr=service_error)
            proxy = FinalAckProxy(port, state / "service/tasks.sqlite")
            active = None
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    service_output.seek(0)
                    line = service_output.readline()
                    if line:
                        assert json.loads(line)["event"] == "service-listening"
                        break
                    assert service.poll() is None
                    time.sleep(0.02)
                else:
                    raise AssertionError("service startup deadline")
                run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}", "--fingerprint", info["fingerprint"],
                                         "--credential-file", offer["credentialFile"]])
                for channels in (1, 4, 16):
                    for direction in ("upload", "download"):
                        key = f"{direction}-{channels}"
                        remote = shared / key
                        remote.mkdir()
                        destination = remote if direction == "upload" else root / key
                        destination.mkdir(exist_ok=True)
                        if direction == "download":
                            shutil.copyfile(sample, remote / sample.name)
                        original = destination / sample.name
                        original.write_bytes(b"original user data")
                        original_sha = digest(original)
                        final = original if args.on_conflict == "overwrite" else destination / "source (2).bin"
                        request = str(uuid.uuid4())
                        arguments = [direction, "--share", "data", "--threads", str(channels), "--request-id", request,
                                     "--retries", str(args.auto_retries), "--on-conflict", args.on_conflict]
                        arguments += (["--path", str(sample), "--remote-path", key] if direction == "upload" else
                                      ["--remote-path", key + "/source.bin", "--output", str(destination)])
                        proxy.final, proxy.task = final, None
                        proxy.dropped.clear()
                        proxy.dropped_bytes = 0
                        proxy.armed = True
                        active = TransferProcess(executable, client, arguments)
                        # 日期：2026-11-05；任务 ID 只取公共就绪事件；数据传输之前已设置丢确认的绑定条件。
                        proxy.task = active.task()
                        if args.auto_retries:
                            # 日期：2026-11-05；同一客户端进程自行重连，必须看到真实网络重试及最终持久确认。
                            events = finish(active, 0, 60)
                            retries = [event for event in events if event.get("event") == "transfer-retrying"]
                            assert len(retries) == 1 and retries[0]["retry"] == 1, events
                            error = retries[0]
                            assert events[-1]["taskId"] == proxy.task and events[-1]["requestId"] == request
                        else:
                            error = failure(active)
                        active = None
                        assert proxy.dropped.is_set() and proxy.dropped_bytes > 0, error
                        assert error["code"] == 3, error
                        proxy.armed = False
                        status, _ = run(executable, client, ["task", "--task", proxy.task])
                        assert status["state"] == "completed" and status["bytes"] == status["total"], status
                        if args.on_conflict == "overwrite":
                            assert status["conflict"] == "overwrite", status
                        else:
                            assert "conflict" not in status, status
                        assert digest(final) == expected
                        assert digest(original) == (expected if args.on_conflict == "overwrite" else original_sha)
                        # 日期：2026-11-06；最终确认丢失时实际接收已完成，双端处置必须与目标和清单相符。
                        journal = verify_journal(state / "service", f"manifest-{proxy.task}.sqlite", proxy.task,
                                                 destination, args.on_conflict)
                        legacy_rebuilt = channels == 4 and args.auto_retries == 0
                        if direction == "download":
                            local = verify_journal(client / "transfers", f"download-{proxy.task}.sqlite", proxy.task,
                                                   destination, args.on_conflict)
                            assert local["records"] == journal["records"]
                        else:
                            # 日期：2026-11-06；丢弃的片段可能包含最后条目确认，发送端只允许保留真实连续前缀。
                            local = verify_journal(client / "transfers", state / "service" / f"manifest-{proxy.task}.sqlite",
                                                   proxy.task, destination, args.on_conflict, False, sender=True)
                            assert local["records"] == journal["records"][:local["recordedEntries"]]
                        if legacy_rebuilt:
                            # 日期：2026-11-06；双向分别模拟旧版本没有本机日志，须从实际接收证据补齐。
                            receipt = client / "transfers" / f"{'disposition' if direction == 'download' else 'upload-disposition'}-{proxy.task}.sqlite"
                            receipt.rename(root / f"saved-disposition-{proxy.task}.sqlite")
                        result = transfer(executable, client, arguments)
                        assert result["taskId"] == proxy.task and result["requestId"] == request
                        assert result["state"] == "completed"
                        if args.on_conflict == "overwrite":
                            assert result["conflict"] == "overwrite", result
                        else:
                            assert "conflict" not in result, result
                        expected_names = ["source.bin"] if args.on_conflict == "overwrite" else ["source (2).bin", "source.bin"]
                        assert sorted(path.name for path in destination.iterdir() if not path.name.startswith(".")) == expected_names
                        assert digest(final) == expected
                        assert digest(original) == (expected if args.on_conflict == "overwrite" else original_sha)
                        after = verify_journal(state / "service", f"manifest-{proxy.task}.sqlite", proxy.task,
                                               destination, args.on_conflict)
                        assert after == journal
                        if direction == "download":
                            rebuilt = verify_journal(client / "transfers", f"download-{proxy.task}.sqlite", proxy.task,
                                                     destination, args.on_conflict)
                            assert rebuilt["records"] == journal["records"]
                        else:
                            rebuilt = verify_journal(client / "transfers", state / "service" / f"manifest-{proxy.task}.sqlite",
                                                     proxy.task, destination, args.on_conflict, sender=True)
                            assert rebuilt["records"] == journal["records"]
                        if args.on_conflict == "overwrite":
                            # 日期：2026-11-06；上传和下载均拒绝被后来替换的目标，保留用户文件和原历史终态。
                            replacement = destination / "later-user-edit.tmp"
                            replacement.write_bytes(b"later independent user replacement")
                            later_sha = digest(replacement)
                            os.replace(replacement, final)
                            later = transfer(executable, client, arguments, 6)
                            assert digest(final) == later_sha and later["code"] == 6, later
                            unchanged, _ = run(executable, client, ["task", "--task", proxy.task])
                            assert unchanged == status, (unchanged, status)
                            assert [path.name for path in destination.iterdir() if not path.name.startswith(".")] == ["source.bin"]
                        cases.append({"direction": direction, "channels": channels, "taskId": proxy.task, "requestId": request,
                                      "droppedEncryptedBytes": proxy.dropped_bytes,
                                      "serverCompletedBeforeDrop": proxy.completed_snapshot, "clientFirstError": error,
                                      "dispositionJournalVerified": True, "legacyLocalJournalRebuilt": legacy_rebuilt,
                                      "automaticRetries": args.auto_retries, "retrySameTask": True, "sha256": expected, "originalPreserved": args.on_conflict == "rename", "originalReplaced": args.on_conflict == "overwrite", "noDuplicateCopy": True, "laterUserReplacementProtected": args.on_conflict == "overwrite"})
                        print(key + ": final confirmation lost; same task retry verified", flush=True)
            finally:
                if active and active.process.poll() is None:
                    active.process.kill()
                    active.process.wait(10)
                proxy.close()
                service.kill()
                service.wait(10)
                service_error.seek(0)
                assert not service_error.read()
    Path(args.report).write_text(json.dumps({"date": "2026-11-05", "passed": True, "cases": cases, "executableSha256": executable_sha,
        "scriptSha256": digest(Path(__file__)), "inPlaceRequested": args.in_place, "conflictPolicy": args.on_conflict,
        "scope": "actual final task response loss after durable server completion, real opaque TLS proxy, same-request retries; arbitrary power-loss offsets remain open"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
