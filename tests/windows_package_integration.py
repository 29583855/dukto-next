"""日期：2026-11-05；解压实际 Windows 预览包，用仅含系统路径的环境验证 GUI、独立 CLI、TLS 和多通道互传。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tempfile
import threading
import time
import zipfile

import psutil

from service_integration import free_port


# 日期：2026-11-05；哈希使用固定大小块，逐文件核验打包清单，不依赖解压过程声称完整。
def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


# 日期：2026-11-05；包内程序仅可加载包目录或 Windows 系统模块；CLI 还必须保持无图形模块。
def modules(process, stage, cli=False):
    paths = sorted(set(item.path for item in psutil.Process(process.pid).memory_maps()
                       if item.path.lower().endswith((".dll", ".exe"))))
    # 日期：2026-11-05；GUI 刚创建/即将退出时枚举可暂为空，最终仍强制取得 qwindows 模块证据。
    if cli:
        assert paths, "No native module evidence"
    windows = Path(os.environ["SystemRoot"]).resolve()
    for value in paths:
        path = Path(value).resolve()
        assert path.is_relative_to(stage) or path.is_relative_to(windows), ("External module", value)
    if cli:
        assert not any(Path(value).name.lower() in ("qt5gui.dll", "qt5widgets.dll", "qt5qml.dll", "qt5quick.dll")
                       for value in paths), paths
    return [str(Path(value).resolve().relative_to(stage)) if Path(value).resolve().is_relative_to(stage)
            else "Windows/" + str(Path(value).resolve().relative_to(windows)) for value in paths]


# 日期：2026-11-05；短命令有明确退出码/标准错误断言，运行目录为独立空目录，避免源码目录补足依赖。
def checked(command, environment, working, timeout=30):
    result = subprocess.run([str(value) for value in command], env=environment, cwd=working,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    assert result.returncode == 0 and not result.stderr, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout


# 日期：2026-11-05；后台读取就绪事件，主线程能对加载失败或阻塞设置独立截止时间。
def first_line(stream, result):
    result.put(stream.readline())


# 日期：2026-11-05；验证实际 ZIP，而非构建目录；隔离环境不包含 Qt、OpenSSL、编译器或源码插件搜索路径。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    assert os.name == "nt"
    root = Path(__file__).resolve().parents[1]
    report = Path(args.report).resolve()
    archive = Path(args.archive).resolve()
    with tempfile.TemporaryDirectory(prefix="dukto-package-") as temporary:
        working = Path(temporary).resolve() / "中文路径 with spaces"
        working.mkdir()
        with zipfile.ZipFile(archive) as source:
            for item in source.infolist():
                target = (working / item.filename).resolve()
                assert target.is_relative_to(working) and not ((item.external_attr >> 16) & 0o170000) == 0o120000
            source.extractall(working)
        stage = working / "DuktoNext-windows-x64-preview"
        manifest = json.loads((stage / "package-manifest.json").read_text(encoding="utf-8"))
        expected = set()
        for item in manifest["files"]:
            path = stage / item["path"]
            assert path.resolve().is_relative_to(stage) and path.stat().st_size == item["bytes"]
            assert digest(path) == item["sha256"], item["path"]
            expected.add(item["path"])
        actual = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()}
        assert actual == expected | {"package-manifest.json"}, (actual - expected, expected - actual)
        # 日期：2026-11-05；ICU 许可位于非标准目录，要求显式部署来源，不把已有 share/licenses 目录当作完整证明。
        dependency_packages = json.loads((stage / "dependency-packages.json").read_text(encoding="utf-8"))
        icu = "mingw-w64-ucrt-x86_64-icu"
        assert icu in dependency_packages
        version = dependency_packages[icu]["VERSION"][0].split("-", 1)[0].rsplit(":", 1)[-1]
        extra_licenses = manifest["additionalLicenseFiles"]
        assert len(extra_licenses) == 1 and extra_licenses[0] == {
            "path": "licenses/dependencies/icu/LICENSE", "installedPath": "ucrt64/share/icu/" + version + "/LICENSE",
            "package": icu, "sha256": digest(stage / "licenses/dependencies/icu/LICENSE")}
        assert (stage / extra_licenses[0]["path"]).stat().st_size > 100
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in ("SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "SYSTEMDRIVE", "NUMBER_OF_PROCESSORS")}
        environment.update({"PATH": str(Path(os.environ["SystemRoot"]) / "System32"),
                            "QT_QPA_PLATFORM": "windows", "QML_DISABLE_DISK_CACHE": "1", "PYTHONUTF8": "1"})
        for variable in ("APPDATA", "LOCALAPPDATA", "USERPROFILE", "HOME", "XDG_CONFIG_HOME", "XDG_CACHE_HOME"):
            directory = working / variable
            directory.mkdir()
            environment[variable] = str(directory)
        executable = stage / "dukto-cli.exe"
        help_text = checked([executable, "--help"], environment, working)
        assert all(command in help_text for command in ("upload", "download", "resume", "serve", "--threads", "--retries", "--deadline-seconds", "--on-conflict"))
        doctor = json.loads(checked([executable, "doctor", "--json"], environment, working))
        assert doctor["sqlite"] and doctor["tls"] and doctor["cxxStandard"] == "C++14"
        state = working / "server-state"
        checked([executable, "serve", "init", "--state-directory", state, "--server-name", "127.0.0.1", "--json"], environment, working)
        service = subprocess.Popen([str(executable), "serve", "start", "--state-directory", str(state), "--bind", "127.0.0.1",
                                    "--port", str(free_port()), "--json"], cwd=working, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            ready = queue.Queue()
            reader = threading.Thread(target=first_line, args=(service.stdout, ready), daemon=True)
            reader.start()
            assert json.loads(ready.get(timeout=20))["event"] == "service-listening"
            cli_modules = modules(service, stage, cli=True)
        finally:
            service.kill()
            _, error = service.communicate(timeout=10)
            assert not error, error
        screenshot = working / "desktop.png"
        gui = subprocess.Popen([str(stage / "dukto-gui.exe"), "--self-test", "--screenshot", str(screenshot),
                                "--data-directory", str(working / "gui-state"), "--port", str(free_port())],
                               cwd=working, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        gui_modules = set()
        try:
            deadline = time.monotonic() + 20
            while gui.poll() is None and time.monotonic() < deadline:
                try:
                    gui_modules.update(modules(gui, stage))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    if gui.poll() is None:
                        raise
                time.sleep(0.03)
            output, error = gui.communicate(timeout=2)
            assert gui.returncode == 0 and not output and not error, (gui.returncode, output, error)
            assert any(value.lower() == "platforms\\qwindows.dll" for value in gui_modules), sorted(gui_modules)
            image = screenshot.read_bytes()
            assert image[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", image[16:24]) == (430, 700)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.with_suffix(".png").write_bytes(image)
        finally:
            if gui.poll() is None:
                gui.kill()
                gui.communicate(timeout=10)
        transfer_report = working / "transfer.json"
        checked([sys.executable, "-X", "utf8", root / "tests/transfer_integration.py", executable,
                 "--threads", "16", "--report", transfer_report], environment, working, timeout=180)
        transfers = json.loads(transfer_report.read_text(encoding="utf-8"))
        client_report = working / "clients.json"
        checked([sys.executable, "-X", "utf8", root / "tests/client_list_integration.py", executable,
                 "--report", client_report], environment, working, timeout=90)
        clients = json.loads(client_report.read_text(encoding="utf-8"))
        # 日期：2026-11-05；同一包内二进制在系统 PATH 下验证协商、本机策略及四通道到期后原任务恢复。
        session_report = working / "session-expiry.json"
        checked([sys.executable, "-X", "utf8", root / "tests/session_expiry_integration.py", executable,
                 "--channels", "4", "--report", session_report], environment, working, timeout=240)
        sessions = json.loads(session_report.read_text(encoding="utf-8"))
        # 日期：2026-11-05；包内同一二进制在系统 PATH 下进行真实上传/下载混合等待和原任务恢复。
        admission_report = working / "task-admission-mixed.json"
        checked([sys.executable, "-X", "utf8", root / "tests/task_admission_integration.py", executable,
                 "--mode", "mixed", "--report", admission_report], environment, working, timeout=300)
        admission = json.loads(admission_report.read_text(encoding="utf-8"))
        # 日期：2026-11-05；只执行解压包内 CLI，系统 PATH 下验证十四组网络故障/权限/远程停止和总时限。
        retry_report = working / "transfer-retry.json"
        checked([sys.executable, "-X", "utf8", root / "tests/transfer_retry_integration.py", executable,
                 "--in-place", "--report", retry_report], environment, working, timeout=600)
        retries = json.loads(retry_report.read_text(encoding="utf-8"))
        assert retries["executableSha256"] == digest(executable)
        # 日期：2026-11-05；最终确认丢失由同一进程自动恢复，六组双向/三档通道结果仍绑定该包二进制。
        ack_report = working / "final-ack-auto.json"
        checked([sys.executable, "-X", "utf8", root / "tests/final_ack_integration.py", executable,
                 "--auto-retries", "3", "--in-place", "--report", ack_report], environment, working, timeout=300)
        acknowledgements = json.loads(ack_report.read_text(encoding="utf-8"))
        assert acknowledgements["executableSha256"] == digest(executable)
        # 日期：2026-11-05；同一解压包内程序在系统 PATH 下执行严格冲突保护及持久原策略恢复。
        conflict_report = working / "conflict-fail.json"
        checked([sys.executable, "-X", "utf8", root / "tests/conflict_fail_integration.py", executable,
                 "--report", conflict_report], environment, working, timeout=180)
        conflicts = json.loads(conflict_report.read_text(encoding="utf-8"))
        assert conflicts["passed"] and conflicts["executableSha256"] == digest(executable)
        conflict_recovery_report = working / "conflict-fail-recovery.json"
        checked([sys.executable, "-X", "utf8", root / "tests/transfer_recovery_integration.py", executable,
                 "--in-place", "--on-conflict", "fail", "--threads", "4", "--resume-threads", "8", "--files", "4",
                 "--payload-mib", "8", "--checkpoint-percent", "50", "--report", conflict_recovery_report],
                environment, working, timeout=300)
        conflict_recovery = json.loads(conflict_recovery_report.read_text(encoding="utf-8"))
        assert conflict_recovery["passed"] and conflict_recovery["conflictPolicy"] == "fail"
        assert conflict_recovery["inPlaceExecution"]
        assert conflict_recovery["binarySha256"] == digest(executable)
        overwrite_report = working / "conflict-overwrite.json"
        checked([sys.executable, "-X", "utf8", root / "tests/conflict_overwrite_integration.py", executable,
                 "--report", overwrite_report], environment, working, timeout=300)
        overwrite = json.loads(overwrite_report.read_text(encoding="utf-8"))
        assert overwrite["passed"] and overwrite["executableSha256"] == digest(executable)
        overwrite_recovery_report = working / "conflict-overwrite-recovery.json"
        checked([sys.executable, "-X", "utf8", root / "tests/transfer_recovery_integration.py", executable,
                 "--in-place", "--on-conflict", "overwrite", "--threads", "4", "--resume-threads", "8", "--files", "4",
                 "--payload-mib", "8", "--checkpoint-percent", "50", "--report", overwrite_recovery_report],
                environment, working, timeout=600)
        overwrite_recovery = json.loads(overwrite_recovery_report.read_text(encoding="utf-8"))
        assert overwrite_recovery["passed"] and overwrite_recovery["conflictPolicy"] == "overwrite"
        assert overwrite_recovery["inPlaceExecution"] and overwrite_recovery["binarySha256"] == digest(executable)
    report.write_text(json.dumps({"date": "2026-11-05", "passed": True, "archiveSha256": digest(archive),
        "manifestFilesVerified": len(expected), "workingPathUnicodeAndSpaces": True, "developerPathsRemoved": True,
        "doctor": doctor, "cliModules": cli_modules, "guiModules": sorted(gui_modules), "transfer": transfers,
        "clients": clients, "sessions": sessions, "taskAdmission": admission,
        "transferRetry": retries, "automaticFinalAck": acknowledgements, "additionalLicenseFiles": extra_licenses,
        "conflictFail": conflicts, "conflictFailRecovery": conflict_recovery,
        "conflictOverwrite": overwrite, "conflictOverwriteRecovery": overwrite_recovery,
        "scope": "relocated archive with system-only PATH on development Windows host; clean OS validation remains open",
        "cleanSystemQualified": False}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Windows relocated GUI/CLI/16-channel TLS package validation passed")


if __name__ == "__main__":
    main()
