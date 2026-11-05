"""日期：2026-11-05；解压 Linux 预览包并核验迁移后的原生桌面渲染、独立 CLI、模块来源和 16 通道 TLS。"""

import argparse
import json
import os
from pathlib import Path
import queue
import struct
import subprocess
import sys
import tarfile
import tempfile
import threading
import time

import psutil

from service_integration import free_port
from transfer_integration import digest


# 日期：2026-11-05；测试进程的动态库若属于包内依赖，必须实际从迁移目录加载，CLI 禁止加载 GUI 模块。
def modules(process, stage, libraries, cli=False):
    paths = sorted(set(item.path for item in psutil.Process(process.pid).memory_maps()
                       if item.path.startswith("/") and ".so" in Path(item.path).name))
    assert paths
    for value in paths:
        path = Path(value).resolve()
        if path.name in libraries or path.name.startswith(("libQt5", "libssl.so", "libcrypto.so")):
            assert path.is_relative_to(stage), ("External dependency", value)
        if cli:
            assert not path.name.startswith(("libQt5Gui", "libQt5Widgets", "libQt5Qml", "libQt5Quick",
                                             "libEGL", "libGL", "libgallium", "libLLVM")), value
    return [str(Path(value).relative_to(stage)) if Path(value).is_relative_to(stage) else value for value in paths]


# 日期：2026-11-05；无 shell 执行独立启动器，非零退出、缺库、QML 警告或其他标准错误均失败。
def checked(command, environment, working, timeout=30):
    result = subprocess.run([str(value) for value in command], cwd=working, env=environment,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=timeout)
    assert result.returncode == 0 and not result.stderr, (command, result.returncode, result.stdout, result.stderr)
    return result.stdout


# 日期：2026-11-05；只读取服务的首条事件，主线程就绪截止时间不因 stdout 阻塞而失效。
def first_line(stream, result):
    result.put(stream.readline())


# 日期：2026-11-05；实际 tar 包在中文和空格目录迁移；X11/Wayland 会话由调用方提供，不用离屏代替桌面。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--report", required=True)
    parser.add_argument("--platform", choices=("xcb", "wayland"), required=True)
    args = parser.parse_args()
    assert sys.platform.startswith("linux")
    root = Path(__file__).resolve().parents[1]
    archive, report = Path(args.archive).resolve(), Path(args.report).resolve()
    with tempfile.TemporaryDirectory(prefix="dukto-linux-package-") as temporary:
        working = Path(temporary).resolve() / "中文路径 with spaces"
        working.mkdir()
        with tarfile.open(archive) as source:
            aliases = {"lib/libcrypto.so": "libcrypto.so.3", "lib/libssl.so": "libssl.so.3"}
            # 日期：2026-11-05；只放行打包器约定的两个同目录 OpenSSL 别名，其余链接和全部硬链接拒绝。
            for item in source.getmembers():
                assert (working / item.name).resolve().is_relative_to(working) and not item.islnk()
                if item.issym():
                    relative = Path(item.name).relative_to("DuktoNext-linux-glibc-x64-preview").as_posix()
                    assert aliases.get(relative) == item.linkname, (item.name, item.linkname)
            source.extractall(working, filter="data")
        stage = working / "DuktoNext-linux-glibc-x64-preview"
        manifest = json.loads((stage / "package-manifest.json").read_text(encoding="utf-8"))
        assert manifest["libraryAliases"] == aliases
        assert manifest["guiRuntimePolicy"] == {
            "LIBGL_ALWAYS_SOFTWARE": "default 1, user override supported",
            "waylandDecorationPlugins": True, "hostGraphicsDriverRequired": True}
        decorations = list((stage / "plugins/wayland-decoration-client").glob("*.so"))
        assert decorations, "Window decoration plugins must be deployed"
        for relative, target in aliases.items():
            alias = stage / relative
            assert alias.is_symlink() and os.readlink(alias) == target
            assert alias.resolve(strict=True).parent == stage / "lib"
        expected = set()
        for item in manifest["files"]:
            path = stage / item["path"]
            assert path.resolve().is_relative_to(stage) and path.stat().st_size == item["bytes"]
            assert digest(path) == item["sha256"], item["path"]
            expected.add(item["path"])
        actual = {path.relative_to(stage).as_posix() for path in stage.rglob("*") if path.is_file()}
        assert actual == expected | {"package-manifest.json"}
        environment = {key: value for key, value in os.environ.items()
                       if key in ("DISPLAY", "WAYLAND_DISPLAY", "XAUTHORITY", "XDG_RUNTIME_DIR", "LANG", "LC_ALL")}
        runtime = working / "runtime"
        runtime.mkdir(mode=0o700)
        environment.setdefault("XDG_RUNTIME_DIR", str(runtime))
        environment.update({"PATH": "/usr/bin:/bin", "HOME": str(working), "XDG_CONFIG_HOME": str(working / "config"),
                            "XDG_CACHE_HOME": str(working / "cache"), "XDG_DATA_HOME": str(working / "data"),
                            "QT_QPA_PLATFORM": args.platform, "QML_DISABLE_DISK_CACHE": "1", "PYTHONUTF8": "1"})
        libraries = {Path(item["path"]).name for item in manifest["files"] if item["path"].startswith("lib/")}
        executable = stage / "dukto-cli"
        help_text = checked([executable, "--help"], environment, working)
        assert all(command in help_text for command in ("upload", "download", "resume", "serve", "--threads"))
        doctor = json.loads(checked([executable, "doctor", "--json"], environment, working))
        assert doctor["sqlite"] and doctor["tls"] and doctor["cxxStandard"] == "C++14"
        state = working / "service-state"
        checked([executable, "serve", "init", "--state-directory", state, "--server-name", "127.0.0.1", "--json"], environment, working)
        service = subprocess.Popen([str(executable), "serve", "start", "--state-directory", str(state), "--bind", "127.0.0.1",
                                    "--port", str(free_port()), "--json"], cwd=working, env=environment,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
        try:
            ready = queue.Queue()
            reader = threading.Thread(target=first_line, args=(service.stdout, ready), daemon=True)
            reader.start()
            assert json.loads(ready.get(timeout=20))["event"] == "service-listening"
            cli_modules = modules(service, stage, libraries, cli=True)
            tls_modules = [value for value in cli_modules if Path(value).name.startswith(("libssl.so", "libcrypto.so"))]
            assert sorted(tls_modules) == ["lib/libcrypto.so.3", "lib/libssl.so.3"], tls_modules
        finally:
            service.kill()
            _, error = service.communicate(timeout=10)
            assert not error, error
        screenshot = working / "desktop.png"
        gui = subprocess.Popen([str(stage / "dukto-gui"), "--self-test", "--screenshot", str(screenshot),
                                "--data-directory", str(working / "gui-state"), "--port", str(free_port())],
                               cwd=working, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        gui_modules = set()
        try:
            deadline = time.monotonic() + 30
            while gui.poll() is None and time.monotonic() < deadline:
                try:
                    gui_modules.update(modules(gui, stage, libraries))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    if gui.poll() is None:
                        raise
                time.sleep(0.03)
            output, error = gui.communicate(timeout=2)
            assert gui.returncode == 0 and not output and not error, (gui.returncode, output, error)
            assert any("plugins/platforms/libq" in value and ("xcb" if args.platform == "xcb" else "wayland") in value
                       for value in gui_modules), sorted(gui_modules)
            if args.platform == "wayland":
                assert any(value.startswith("plugins/wayland-decoration-client/") for value in gui_modules), sorted(gui_modules)
            image = screenshot.read_bytes()
            assert image[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", image[16:24]) == (430, 700)
            report.parent.mkdir(parents=True, exist_ok=True)
            report.with_suffix(".png").write_bytes(image)
        finally:
            if gui.poll() is None:
                gui.kill()
                gui.communicate(timeout=10)
        # 日期：2026-11-05；业务超时不丢失真实界面/模块证据；整包状态保持失败直到所有传输通过。
        result = {"date": "2026-11-05", "passed": False, "phase": "transfer-pending",
                  "runtimeChecksPassed": True, "transferChecksPassed": False,
                  "archiveSha256": digest(archive), "platform": args.platform,
                  "manifestFilesVerified": len(expected), "workingPathUnicodeAndSpaces": True,
                  "developerEnvironmentRemoved": True, "guiRuntimePolicy": manifest["guiRuntimePolicy"],
                  "hostGraphicsModules": sorted(value for value in gui_modules if value.startswith("/")),
                  "libraryAliases": aliases, "tlsModules": tls_modules, "doctor": doctor,
                  "cliModules": cli_modules, "guiModules": sorted(gui_modules),
                  "scope": "relocated glibc package on Ubuntu build VM in an actual X11/Wayland session",
                  "cleanSystemQualified": False}
        report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        transfer_report = working / "transfer.json"
        try:
            checked([sys.executable, "-X", "utf8", root / "tests/transfer_integration.py", executable,
                     "--threads", "16", "--report", transfer_report], environment, working, timeout=240)
        except Exception as error:
            result.update(phase="transfer-failed", failure=(type(error).__name__ + ": " + str(error))[-8192:])
            report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            raise
        transfers = json.loads(transfer_report.read_text(encoding="utf-8"))
    result.update(passed=True, phase="completed", transferChecksPassed=True, transfer=transfers)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Linux relocated " + args.platform + " GUI/CLI/16-channel TLS package validation passed")


if __name__ == "__main__":
    main()
