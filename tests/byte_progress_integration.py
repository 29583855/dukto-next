"""日期：2026-11-05；真实限速 TLS 双向字节进度、任务查询、暂停后变更通道恢复及摘要专项。"""

import argparse
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

from service_integration import free_port, run
from transfer_integration import digest
from transfer_recovery_integration import SlowProxy, TransferProcess, wait_state


# 日期：2026-11-05；冷传输强制部分字节/查询；恢复已全部落盘时按全量复用与最终查询严格核对。
def observe(executable, state, operation, pause=False, allow_fully_restored=False):
    initial = []
    while True:
        event = operation.events.get(timeout=60)
        assert event is not None, initial
        initial.append(event)
        if event.get("state") == "transferring":
            task = event["taskId"]
            break
    reports = []
    file_done = False
    queried = None
    started = time.monotonic()
    try:
        while True:
            value = operation.events.get(timeout=60)
            if value is None:
                break
            assert not any(key in value for key in ("token", "credential", "parallel")), value
            if value.get("event") == "file-completed":
                file_done = True
            if value.get("event") == "byte-progress":
                received, confirmed, restored, total = [int(value[key]) for key in
                    ("receivedBytes", "bytes", "restoredBytes", "total")]
                assert 0 <= restored <= confirmed <= received <= total, value
                assert value["taskId"] == task and value["state"] == "transferring", value
                assert math.isfinite(value["bytesPerSecond"]) and value["bytesPerSecond"] >= 0, value
                assert value["etaSeconds"] is None or value["etaSeconds"] >= 0, value
                if reports:
                    assert all(int(value[key]) >= int(reports[-1][key]) for key in
                               ("receivedBytes", "bytes", "restoredBytes")), (reports[-1], value)
                reports.append(value)
                if queried is None and 0 < confirmed < total and not file_done:
                    deadline = time.monotonic() + 5
                    while True:
                        queried, _ = run(executable, state, ["task", "--task", task])
                        assert queried["errorMessage"] == "", queried
                        if int(queried["bytes"]) > 0 or time.monotonic() >= deadline:
                            break
                        # 日期：2026-11-05；发送方在块确认读取期间消费对端进度，独立查询允许短暂观察到旧快照。
                        time.sleep(0.05)
                    assert 0 < int(queried["bytes"]) <= total, queried
                    if pause:
                        run(executable, state, ["pause", "--task", task])
                        operation.finish()
                        stopped = wait_state(executable, state, task, "paused")
                        assert 0 < int(stopped["bytes"]) < total, stopped
                        return {"taskId": task, "paused": True, "reports": reports,
                                "persisted": stopped["bytes"]}
            if value.get("event") == "transfer-completed":
                final = value
        assert operation.process.wait(10) == 0 and not operation.process.stderr.read()
        assert reports and file_done, (queried, reports, file_done)
        fully_restored = queried is None
        if fully_restored:
            # 日期：2026-11-05；暂停前后在途块可全部同步；这种合法恢复没有新部分正文，但每条恢复事件必须确为全量复用。
            assert allow_fully_restored and not pause, reports
            assert all(int(value["restoredBytes"]) == int(value["total"]) for value in reports), reports
            queried, _ = run(executable, state, ["task", "--task", task])
            assert queried["taskId"] == task and queried["state"] == "completed" and not queried["executionActive"], queried
            assert queried["errorMessage"] == "" and int(queried["bytes"]) == int(reports[-1]["total"]), queried
        assert int(reports[-1]["bytes"]) == int(reports[-1]["total"]), reports[-1]
        assert final["taskId"] == task and final["state"] == "completed", final
        assert len(reports) <= (time.monotonic() - started) * 4 + 3, len(reports)
        return {"taskId": task, "paused": False, "reports": reports,
                "final": final, "queried": queried, "fullyRestored": fully_restored}
    finally:
        if operation.process.poll() is None:
            operation.process.kill()
            operation.process.wait(10)


# 日期：2026-11-05；独立身份、服务和本机代理，旧版长时测试及用户共享均不受影响。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    executable = str(Path(args.executable).resolve())
    cases = []
    binary_sha, script_sha = digest(Path(executable)), digest(Path(__file__))
    with tempfile.TemporaryDirectory(prefix="dukto-byte-progress-") as temporary:
        root = Path(temporary)
        if os.name == "nt":
            local = root / "dukto-cli.exe"
            shutil.copyfile(executable, local)
            executable = str(local)
        shared, source = root / "shared", root / "source.bin"
        shared.mkdir()
        with source.open("wb") as output:
            for index in range(128):
                output.write(bytes([index]) * (256 * 1024))
            output.write(b"independent-tail")
        expected = digest(source)
        state, client = root / "server", root / "client"
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        permissions = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *permissions])
        offer, _ = run(executable, state, ["serve", "pairing", *permissions])
        port = free_port()
        server = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state),
                                   "--bind", "127.0.0.1", "--port", str(port), "--json"],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        proxy = SlowProxy(port)
        try:
            assert json.loads(server.stdout.readline())["event"] == "service-listening"
            run(executable, client, ["pair", "--to", f"127.0.0.1:{proxy.port}",
                                     "--fingerprint", info["fingerprint"],
                                     "--credential-file", offer["credentialFile"]])
            for channels in (1, 4, 16):
                destination = shared / f"channels-{channels}"
                destination.mkdir()
                for direction in ("upload", "download"):
                    output = root / f"output-{channels}"
                    output.mkdir(exist_ok=True)
                    request = str(uuid.uuid4())
                    arguments = [direction, "--share", "data", "--threads", str(channels),
                                 "--request-id", request]
                    if direction == "upload":
                        arguments += ["--path", str(source), "--remote-path", destination.name]
                    else:
                        arguments += ["--remote-path", destination.name + "/source.bin", "--output", str(output)]
                    pause = channels == 4
                    operation = TransferProcess(executable, client, arguments)
                    first = observe(executable, client, operation, pause)
                    result = first
                    if pause:
                        resume = ["resume", "--task", first["taskId"], "--threads", "8"]
                        resume += ["--path", str(source)] if direction == "upload" else ["--output", str(output)]
                        result = observe(executable, client, TransferProcess(executable, client, resume), allow_fully_restored=True)
                        assert result["taskId"] == first["taskId"]
                        assert max(int(value["restoredBytes"]) for value in result["reports"]) >= 4 * 1024 * 1024
                    target = destination / source.name if direction == "upload" else output / source.name
                    assert digest(target) == expected
                    assert len(list(target.parent.glob("source*"))) == 1
                    cases.append({"direction": direction, "channels": channels,
                                  "first": first, "resumed": result if pause else None})
                    print(f"{direction}/{channels}: byte progress and SHA passed", flush=True)
            human_target = shared / "human"
            human_target.mkdir()
            human = subprocess.run([executable, "upload", "--state-directory", str(client),
                                    "--share", "data", "--path", str(source), "--remote-path", "human",
                                    "--threads", "4"], capture_output=True, encoding="utf-8", timeout=60)
            assert human.returncode == 0 and not human.stderr, (human.returncode, human.stderr)
            assert "MiB/s" in human.stdout and "已校验落盘" in human.stdout and "ETA=" in human.stdout
            assert digest(human_target / source.name) == expected
        finally:
            proxy.close()
            server.kill()
            _, error = server.communicate(timeout=15)
            assert not error, error
    Path(args.report).write_text(json.dumps({"date": "2026-11-05", "passed": True,
                                           "binarySha256": binary_sha, "scriptSha256": script_sha,
                                           "sha256": expected, "cases": cases},
                                          ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
