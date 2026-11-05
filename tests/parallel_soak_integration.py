"""日期：2026-11-05；新版真实多通道双向连续/长时传输，持续采样常驻服务并按已知任务额度限制测试轮数。"""

import argparse
import csv
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import time
import uuid

import psutil

from service_integration import free_port, run
from soak_transfer import digest, metrics, save_report
from transfer_integration import transfer


# 日期：2026-11-05；Windows 查询真实线程起始地址所属模块，区分传输工作者与系统线程池，诊断结果不包含地址。
def thread_inventory(process):
    if os.name != "nt":
        return [{"id": item.id, "name": Path(f"/proc/{process.pid}/task/{item.id}/comm").read_text().strip()}
                for item in psutil.Process(process.pid).threads()]
    import ctypes
    from ctypes import wintypes
    kernel, psapi, native = ctypes.windll.kernel32, ctypes.windll.psapi, ctypes.windll.ntdll
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenThread.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    class ModuleInfo(ctypes.Structure):
        _fields_ = [("base", ctypes.c_void_p), ("size", wintypes.DWORD), ("entry", ctypes.c_void_p)]
    psapi.EnumProcessModulesEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.DWORD]
    psapi.GetModuleInformation.argtypes = [wintypes.HANDLE, wintypes.HMODULE, ctypes.POINTER(ModuleInfo), wintypes.DWORD]
    psapi.GetModuleFileNameExW.argtypes = [wintypes.HANDLE, wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    native.NtQueryInformationThread.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    handle = kernel.OpenProcess(0x0410, False, process.pid)
    assert handle
    ranges, result = [], []
    try:
        modules = (wintypes.HMODULE * 1024)()
        needed = wintypes.DWORD()
        assert psapi.EnumProcessModulesEx(handle, modules, ctypes.sizeof(modules), ctypes.byref(needed), 3)
        assert needed.value <= ctypes.sizeof(modules)
        for module in modules[:needed.value // ctypes.sizeof(wintypes.HMODULE)]:
            info = ModuleInfo()
            name = ctypes.create_unicode_buffer(32768)
            assert psapi.GetModuleInformation(handle, module, ctypes.byref(info), ctypes.sizeof(info))
            assert psapi.GetModuleFileNameExW(handle, module, name, len(name))
            ranges.append((info.base, info.base + info.size, Path(name.value).name))
        for item in psutil.Process(process.pid).threads():
            thread = kernel.OpenThread(0x0040, False, item.id)
            assert thread
            try:
                start = ctypes.c_void_p()
                assert native.NtQueryInformationThread(thread, 9, ctypes.byref(start), ctypes.sizeof(start), None) == 0
                owner = next((name for low, high, name in ranges if low <= start.value < high), "unmapped")
                result.append({"id": item.id, "startModule": owner})
            finally:
                kernel.CloseHandle(thread)
    finally:
        kernel.CloseHandle(handle)
    return result


# 日期：2026-11-05；双端采样使用固定累计峰值；短命客户退出竞态仅在已确认退出后忽略。
def sample(process, peak):
    try:
        current = metrics(psutil.Process(process.pid))
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        if process.poll() is None:
            raise
        return
    for key, value in current.items():
        peak[key] = max(peak.get(key, 0), value)
    assert current["rss"] < 512 * 1024**2 and current["private"] < 512 * 1024**2, current


# 日期：2026-11-05；完整命令含清单与落盘确认，stdout 写有界磁盘文件，不使读事件队列随时长增长。
def measured(executable, client, arguments, service, peaks, root):
    started = time.monotonic()
    with (root / "client-events.jsonl").open("w+b") as output, (root / "client-stderr.log").open("w+b") as errors:
        operation = subprocess.Popen([executable, *arguments, "--state-directory", str(client), "--json"], stdout=output, stderr=errors)
        try:
            while operation.poll() is None:
                assert time.monotonic() - started < 600, "full transfer deadline"
                sample(operation, peaks["client"])
                sample(service, peaks["server"])
                time.sleep(0.05)
            if operation.returncode != 0:
                output.seek(max(0, os.fstat(output.fileno()).st_size - 16384))
                errors.seek(0)
                raise AssertionError((operation.returncode, output.read(), errors.read(16384)))
            assert os.fstat(output.fileno()).st_size < 4 * 1024**2 and os.fstat(errors.fileno()).st_size == 0
            output.seek(0)
            events = [json.loads(line) for line in output]
            assert events and events[-1]["event"] == "transfer-completed" and events[-1]["state"] == "completed", events[-2:]
            assert events[-1]["bytes"] == events[-1]["total"]
            paths = [event["path"] for event in events if event.get("event") == "file-completed"]
            assert len(paths) == 1, paths
            return events[-1], paths[0], round(time.monotonic() - started, 3)
        finally:
            if operation.poll() is None:
                operation.kill()
                operation.wait(10)


# 日期：2026-11-05；在已验证的测试根中逐个删除本轮摘要正确的副本，保留历史及同名原文件证据到本轮结束。
def clear_round(root, directory, original, final):
    assert directory.resolve().is_relative_to(root) and final.parent == directory and original.parent == directory
    assert sorted(path.name for path in directory.iterdir()) == sorted([original.name, final.name])
    final.unlink()
    original.unlink()
    directory.rmdir()


# 日期：2026-11-05；常驻同一服务 PID，最多 500 轮/1000 任务；每 48 轮换测试主体，不绕过应用任务硬限额。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable")
    parser.add_argument("--report", required=True)
    parser.add_argument("--rounds", type=int, default=0)
    parser.add_argument("--duration", type=int, default=0)
    parser.add_argument("--interval", type=float, default=0)
    parser.add_argument("--threads", type=int, choices=(1, 2, 4, 8, 16), default=16)
    parser.add_argument("--payload-mib", type=int, default=8)
    args = parser.parse_args()
    assert (1 <= args.rounds <= 500 and args.duration == 0) or (args.rounds == 0 and 1 <= args.duration <= 86400 and args.interval > 0)
    maximum_rounds = args.rounds or math.ceil(args.duration / args.interval) + 1
    assert maximum_rounds <= 500 and args.interval >= 0 and 1 <= args.payload_mib <= 4096
    report_path = Path(args.report).resolve()
    assert not report_path.exists(), "Use a new report path"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    executable = str(Path(args.executable).resolve())
    report = {"date": "2026-11-05", "status": "running", "passed": False, "rounds": 0,
              "platform": platform.platform(), "durationRequestedSeconds": args.duration,
              "roundsRequested": args.rounds, "intervalSeconds": args.interval, "requestedChannels": args.threads,
              "maximumTasksPlanned": maximum_rounds * 2, "rotateTestPrincipalEveryRounds": 48,
              "testScriptSha256": digest(Path(__file__).resolve()), "executableSha256": digest(Path(executable)),
              "peaks": {"client": {}, "server": {}}, "scope": "persistent newer TLS service, actual bidirectional data per round, fixed test data and bounded task count; no disk GC or arbitrary growth qualification"}
    save_report(report_path, report)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="dukto-parallel-soak-") as temporary:
        root = Path(temporary).resolve()
        if os.name == "nt":
            local = root / "dukto-cli.exe"
            shutil.copyfile(executable, local)
            executable = str(local)
        state, shared = root / "server", root / "shared"
        shared.mkdir()
        source = root / "payload.bin"
        with source.open("wb") as output:
            for index in range(args.payload_mib * 4):
                output.write(bytes([index % 251]) * (256 * 1024))
            output.write(b"parallel-soak-tail")
        expected = digest(source)
        report.update(payloadBytes=source.stat().st_size, payloadSha256=expected)
        info, _ = run(executable, state, ["serve", "init", "--server-name", "127.0.0.1"])
        rights = ["--share", "data", "--allow-upload", "--allow-download", "--allow-browse"]
        run(executable, state, ["serve", "share", "add", "--path", str(shared), *rights])
        port = free_port()
        service = None
        baseline = None
        warm_peaks = {}
        with (root / "service-events.jsonl").open("w+b") as output, (root / "service-stderr.log").open("w+b") as errors, \
                (report_path.parent / (report_path.stem + "-samples.csv")).open("w", encoding="utf-8", newline="") as samples:
            writer = csv.DictWriter(samples, fieldnames=["round", "elapsedSeconds", "phase", "rss", "private", "threads", "handles"])
            writer.writeheader()
            try:
                service = subprocess.Popen([executable, "serve", "start", "--state-directory", str(state), "--bind", "127.0.0.1",
                                            "--port", str(port), "--json"], stdout=output, stderr=errors)
                report["servicePid"] = service.pid
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    output.seek(0)
                    first = output.readline()
                    if first:
                        assert json.loads(first)["event"] == "service-listening"
                        break
                    assert service.poll() is None
                    time.sleep(0.02)
                else:
                    raise AssertionError("service startup deadline")
                while (report["rounds"] < args.rounds if args.rounds else time.monotonic() - started < args.duration):
                    round_number = report["rounds"]
                    if round_number % 48 == 0:
                        client = root / f"client-{round_number // 48}"
                        offer, _ = run(executable, state, ["serve", "pairing", *rights])
                        run(executable, client, ["pair", "--to", f"127.0.0.1:{port}", "--fingerprint", info["fingerprint"],
                                                 "--credential-file", offer["credentialFile"]])
                    remote = shared / f"round-{round_number:04}"
                    remote.mkdir()
                    original = remote / source.name
                    original.write_bytes(b"preserve original")
                    upload = ["upload", "--share", "data", "--path", str(source), "--remote-path", remote.name,
                              "--threads", str(args.threads), "--request-id", str(uuid.uuid4())]
                    sent, uploaded_path, upload_seconds = measured(executable, client, upload, service, report["peaks"], root)
                    uploaded = (remote / uploaded_path).resolve()
                    assert uploaded.parent == remote and uploaded != original and digest(uploaded) == expected
                    assert sent["channels"] == str(args.threads) and original.read_bytes() == b"preserve original"
                    assert transfer(executable, client, upload)["taskId"] == sent["taskId"]
                    destination = root / "received"
                    destination.mkdir()
                    local_original = destination / uploaded.name
                    local_original.write_bytes(b"preserve local")
                    download = ["download", "--share", "data", "--remote-path", remote.name + "/" + uploaded.name,
                                "--output", str(destination), "--threads", str(args.threads), "--request-id", str(uuid.uuid4())]
                    received, downloaded_path, download_seconds = measured(executable, client, download, service, report["peaks"], root)
                    downloaded = (destination / downloaded_path).resolve()
                    assert downloaded.parent == destination and downloaded != local_original and digest(downloaded) == expected
                    assert received["channels"] == str(args.threads) and local_original.read_bytes() == b"preserve local"
                    assert transfer(executable, client, download)["taskId"] == received["taskId"]
                    clear_round(root, destination, local_original, downloaded)
                    clear_round(root, remote, original, uploaded)
                    assert list(shared.iterdir()) == [] and os.fstat(errors.fileno()).st_size == 0 and os.fstat(output.fileno()).st_size < 16 * 1024**2
                    time.sleep(0.3)
                    current = metrics(psutil.Process(service.pid))
                    report["rounds"] += 1
                    if report["rounds"] <= 10:
                        for key, value in current.items():
                            warm_peaks[key] = max(warm_peaks.get(key, 0), value)
                    if report["rounds"] == 10:
                        # 日期：2026-11-05；首十轮空闲峰值覆盖正常分配器波动，不以恰好收缩的单个采样作为暖机基线。
                        baseline = dict(warm_peaks)
                        report["warmBaselineKind"] = "per-metric idle maximum of rounds 1 through 10"
                        report["warmBaseline"] = baseline
                        report["warmThreads"] = thread_inventory(service)
                        if os.name == "nt":
                            report["warmApplicationThreads"] = sum(item["startModule"].lower() not in ("ntdll.dll", "mswsock.dll", "kernel32.dll") for item in report["warmThreads"])
                            report["threadGate"] = {"applicationGrowth": 1, "windowsSystemPoolMaximum": 16}
                    if baseline and report["rounds"] >= 20:
                        assert current["rss"] <= baseline["rss"] + 16 * 1024**2, current
                        assert current["private"] <= baseline["private"] + 16 * 1024**2, current
                        if os.name == "nt":
                            inventory = thread_inventory(service)
                            application = sum(item["startModule"].lower() not in ("ntdll.dll", "mswsock.dll", "kernel32.dll") for item in inventory)
                            system = len(inventory) - application
                            report["lastThreads"] = inventory
                            assert application <= report["warmApplicationThreads"] + 1, inventory
                            assert system <= 16, inventory
                        else:
                            assert current["threads"] <= baseline["threads"] + 1, current
                        assert current["handles"] <= baseline["handles"] + 8, current
                    elapsed = round(time.monotonic() - started, 3)
                    writer.writerow({"round": report["rounds"], "elapsedSeconds": elapsed, "phase": "idle-after-duplex", **current})
                    samples.flush()
                    report.update(elapsedSeconds=elapsed, lastIdle=current, lastUploadSeconds=upload_seconds, lastDownloadSeconds=download_seconds)
                    save_report(report_path, report)
                    print(f"round {report['rounds']}: upload {upload_seconds}s, download {download_seconds}s", flush=True)
                    remaining = args.interval
                    while remaining > 0 and (not args.duration or time.monotonic() - started < args.duration):
                        delay = min(1.0, remaining)
                        time.sleep(delay)
                        remaining -= delay
                        sample(service, report["peaks"]["server"])
                assert report["rounds"] >= 20 and baseline, "insufficient steady workload"
                report.update(status="passed", passed=True, elapsedSeconds=round(time.monotonic() - started, 3))
            except BaseException as error:
                report.update(status="failed", passed=False, failure=type(error).__name__ + ": " + str(error))
                raise
            finally:
                if service and service.poll() is None:
                    service.kill()
                    service.wait(10)
                report["finishedUtc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                save_report(report_path, report)


if __name__ == "__main__":
    main()
