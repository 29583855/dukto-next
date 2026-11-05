"""日期：2026-11-05；验证macOS预览包在中文空格新目录中的原生GUI、独立CLI和真实TLS迁移。"""

import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile

from service_integration import free_port
from transfer_integration import digest


# 日期：2026-11-05；Cryptex实体文件验证Apple签名；仅在系统dyld共享缓存中的无实体系统镜像可通过缓存成员核验。
def verify_apple_image(path, cryptex):
    if path.is_file():
        signed = subprocess.run(["/usr/bin/codesign", "--verify", "--strict", "-R", "=anchor apple", str(path)],
                                capture_output=True, timeout=30)
        assert signed.returncode == 0, ("Unverified Apple Cryptex image", path, signed.stderr)
        return {"loadPath": str(path), "verification": "codesign Apple anchor"}
    contains = ctypes.CDLL(None)._dyld_shared_cache_contains_path
    contains.argtypes, contains.restype = [ctypes.c_char_p], ctypes.c_bool
    canonical = "/" + path.relative_to(cryptex).as_posix()
    for candidate in (str(path), canonical):
        if contains(candidate.encode("utf-8")):
            return {"loadPath": str(path), "verification": "system dyld shared-cache membership",
                    "cachePath": candidate}
    raise AssertionError(("Cryptex image has neither Apple-verified file nor system-cache membership", path))


# 日期：2026-11-05；从实际dyld日志核对加载来源，CLI不得加载QtGUI/Widgets/QML/Quick框架。
def loaded(command, environment, working, stage, log, cli=False):
    diagnostic = {**environment, "DYLD_PRINT_LIBRARIES": "1"}
    result = subprocess.run([str(value) for value in command], cwd=working, env=diagnostic,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    paths, apple_cryptex = [], []
    for line in result.stderr.splitlines():
        assert line.startswith(("dyld[", "dyld:")), line
        if "/" not in line:
            continue
        path = Path(line[line.index("/"):]).resolve()
        if str(path).startswith(("/System/Library/", "/usr/lib/")):
            continue
        # 日期：2026-11-05；系统更新的Cryptex只通过Apple签名或系统共享缓存核验，不放行任意外部库。
        cryptex = Path("/System/Volumes/Preboot/Cryptexes/OS")
        if any(path.is_relative_to(cryptex / suffix) for suffix in ("System/Library", "usr/lib")):
            apple_cryptex.append(verify_apple_image(path, cryptex))
            continue
        assert path.is_relative_to(stage), ("Dependency loaded outside relocated package", path)
        paths.append(path.relative_to(stage).as_posix())
    assert paths and any("QtCore.framework" in value for value in paths), result.stderr
    assert any("libcrypto" in value for value in paths), paths
    if cli:
        assert not any(any(name in value for name in ("QtGui.framework", "QtWidgets.framework",
                                                       "QtQml.framework", "QtQuick.framework")) for value in paths), paths
    return sorted(set(paths)), list({item["loadPath"]: item for item in apple_cryptex}.values())


# 日期：2026-11-05；真实归档核对后迁移，环境不含Homebrew路径；独立专项使用包内CLI。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assert platform.system() == "Darwin"
    root = Path(__file__).resolve().parents[1]
    archive, report = args.archive.resolve(strict=True), args.report.resolve()
    assert not report.exists()
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("QT_", "QML", "DYLD_"))}
    environment.update(PATH="/usr/bin:/bin:/usr/sbin:/sbin", QT_QPA_PLATFORM="cocoa",
                       QT_QUICK_BACKEND="software", QML_DISABLE_DISK_CACHE="1")
    with tempfile.TemporaryDirectory(prefix="dukto-macos-package-") as temporary:
        working = Path(temporary).resolve() / "中文路径 with spaces"
        working.mkdir()
        with tarfile.open(archive) as source:
            for item in source.getmembers():
                assert (working / item.name).resolve().is_relative_to(working) and not item.islnk(), item.name
                if item.issym():
                    target = Path(item.linkname)
                    assert not target.is_absolute()
                    assert ((working / item.name).parent / target).resolve().is_relative_to(working)
            source.extractall(working, filter="data")
        stages = list(working.iterdir())
        assert len(stages) == 1
        stage, = stages
        manifest = json.loads((stage / "package-manifest.json").read_text(encoding="utf-8"))
        assert manifest["architecture"] == platform.machine()
        for item in manifest["files"]:
            path = stage / item["path"]
            assert path.resolve().is_relative_to(stage) and not path.is_symlink()
            assert path.stat().st_size == item["bytes"] and digest(path) == item["sha256"], item["path"]
        for item in manifest["links"]:
            path = stage / item["path"]
            assert path.is_symlink() and os.readlink(path) == item["target"]
            assert path.resolve(strict=True).is_relative_to(stage)
        app = stage / "Dukto Next.app"
        cli = stage / "dukto-cli"
        native_cli = app / "Contents/MacOS/dukto-cli"
        gui = app / "Contents/MacOS/dukto-gui"
        assert os.access(cli, os.X_OK) and os.access(native_cli, os.X_OK) and os.access(gui, os.X_OK)
        signed = subprocess.run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
                                capture_output=True, timeout=30)
        assert signed.returncode == 0, signed.stderr
        report.parent.mkdir(parents=True, exist_ok=True)
        cli_modules, cli_apple = loaded([native_cli, "--help"], environment, working, stage,
                                        report.with_name(report.stem + "-cli-dyld.log"), cli=True)
        screenshot, geometry = working / "native.png", working / "geometry.json"
        gui_modules, gui_apple = loaded([gui, "--self-test", "--data-directory", working / "gui-state",
                              "--port", str(free_port()), "--screenshot", screenshot,
                              "--render-report", geometry], environment, working, stage,
                                        report.with_name(report.stem + "-gui-dyld.log"))
        layout = json.loads(geometry.read_text(encoding="utf-8"))
        assert layout["platform"] == "cocoa" and layout["logicalSize"] == layout["rootSize"]
        assert layout["logicalSize"][0] == 430 and 560 <= layout["logicalSize"][1] <= 700
        assert screenshot.stat().st_size > 1000
        report.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(screenshot, report.with_suffix(".png"))
        cases = []
        for name, script, extra in (("cli", "cli_contracts", []),
                                    ("transfer16", "transfer_integration", ["--threads", "16"]),
                                    ("recovery4to8", "transfer_recovery_integration",
                                     ["--threads", "4", "--resume-threads", "8", "--files", "4",
                                      "--payload-mib", "8", "--checkpoint-percent", "50"])):
            destination = report.with_name(report.stem + "-" + name + ".json")
            result = subprocess.run([sys.executable, "-X", "utf8", str(root / "tests" / (script + ".py")),
                                     str(cli), *extra, "--report", str(destination)],
                                    cwd=working, env=environment, timeout=600)
            assert result.returncode == 0 and destination.is_file(), (name, result.returncode)
            value = json.loads(destination.read_text(encoding="utf-8"))
            assert value["passed"], name
            cases.append({"name": name, "passed": True, "reportSha256": digest(destination)})
        value = {"date": "2026-11-05", "passed": True, "archiveSha256": digest(archive),
                 "sourceCommit": manifest["sourceCommit"], "architecture": platform.machine(),
                 "verifiedFiles": len(manifest["files"]), "verifiedLinks": len(manifest["links"]),
                 "cliModules": cli_modules, "guiModules": gui_modules,
                 "verifiedAppleSystemImages": list({item["loadPath"]: item for item in cli_apple + gui_apple}.values()),
                 "geometry": layout, "cases": cases,
                 "systemPathOnly": True, "runtimeMigrationQualified": True,
                 "developerIdSigned": False, "notarized": False, "cleanSystemQualified": False,
                 "releaseQualified": False,
                 "scope": "native runner migration and observed module sources; separate clean Mac, Gatekeeper, notarization and complete product qualification remain pending"}
        report.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": True, "archiveSha256": value["archiveSha256"],
                          "architecture": value["architecture"], "releaseQualified": False}))


if __name__ == "__main__":
    main()
