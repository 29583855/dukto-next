"""日期：2026-11-05；原生macOS部署Qt5应用及独立CLI，生成可审计的开发预览包。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile

from package_windows import sha256, source_archive


# 日期：2026-11-05；仅执行显式工具参数，原生部署/签名/依赖检查任一失败都中止。
def checked(command):
    result = subprocess.run([str(value) for value in command], capture_output=True,
                            encoding="utf-8", errors="replace", timeout=300)
    if result.returncode:
        raise RuntimeError((command, result.returncode, result.stdout, result.stderr))
    return result.stdout + result.stderr


# 日期：2026-11-05；只检查真实Mach-O文件，框架符号链接由最终归档清单单列。
def native_file(path):
    with path.open("rb") as stream:
        return stream.read(4) in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                                  b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca")


# 日期：2026-11-05；展开loader/executable相对路径，绝对非系统依赖必须位于包中。
def expand_path(value, image, executable):
    for prefix, location in (("@loader_path", image.parent), ("@executable_path", executable.parent)):
        if value == prefix or value.startswith(prefix + "/"):
            return (location / value[len(prefix):].lstrip("/")).resolve()
    return Path(value).resolve() if value.startswith("/") else None


# 日期：2026-11-05；Qt部署工具可能漏掉brotli等rpath传递库，只从本机已安装Cellar复制精确匹配文件。
def deploy_transitive(app):
    cellar = Path(checked(["brew", "--cellar"]).strip()).resolve()
    framework = app / "Contents/Frameworks"
    framework.mkdir(exist_ok=True)
    executable = app / "Contents/MacOS/dukto-gui"
    for image in (executable, app / "Contents/MacOS/dukto-cli"):
        commands = checked(["otool", "-l", image])
        if "path @executable_path/../Frameworks (offset" not in commands:
            checked(["install_name_tool", "-add_rpath", "@executable_path/../Frameworks", image])
    index, copied = None, []
    for _ in range(64):
        changed = False
        images = sorted(path for path in app.rglob("*")
                        if path.is_file() and not path.is_symlink() and native_file(path))
        for image in images:
            names = re.findall(r"^\s+(\S+) \(compatibility version", checked(["otool", "-L", image]), re.M)
            for name in names:
                if name.startswith(("/System/Library/", "/usr/lib/")):
                    continue
                direct = expand_path(name, image, executable)
                bundled = framework / name[len("@rpath/"):] if name.startswith("@rpath/") else direct
                if bundled is not None and bundled.is_file() and bundled.resolve().is_relative_to(app):
                    continue
                assert ".framework/" not in name, ("Qt framework deployment incomplete", image, name)
                filename = Path(name).name
                if direct is not None and direct.is_file():
                    candidates = {direct.resolve()}
                else:
                    if index is None:
                        index = {}
                        for path in cellar.rglob("*.dylib"):
                            if path.is_file():
                                index.setdefault(path.name, set()).add(path.resolve())
                    candidates = index.get(filename, set())
                assert candidates and all(path.is_relative_to(cellar) for path in candidates), (image, name, candidates)
                hashes = {sha256(path) for path in candidates}
                assert len(hashes) == 1, ("Ambiguous installed dependency", image, name, candidates)
                source = sorted(candidates)[0]
                target = framework / filename
                if not target.exists():
                    shutil.copy2(source, target)
                    target.chmod(target.stat().st_mode | 0o200)
                    checked(["install_name_tool", "-id", "@rpath/" + filename, target])
                    copied.append({"path": target.relative_to(app).as_posix(), "source": str(source),
                                   "originalSha256": sha256(source)})
                replacement = "@executable_path/../Frameworks/" + filename
                checked(["install_name_tool", "-change", name, replacement, image])
                changed = True
        if not changed:
            return copied
    raise RuntimeError("Native dependency closure exceeded64 passes")


# 日期：2026-11-05；逐个Mach-O解析实际加载命令，拒绝Homebrew/构建目录残留和无法解析的rpath。
def dependencies(app):
    executable = app / "Contents/MacOS/dukto-gui"
    framework = app / "Contents/Frameworks"
    images = sorted(path for path in app.rglob("*")
                    if path.is_file() and not path.is_symlink() and native_file(path))
    result = []
    for image in images:
        names = re.findall(r"^\s+(\S+) \(compatibility version", checked(["otool", "-L", image]), re.M)
        commands = checked(["otool", "-l", image])
        rpaths = re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset", commands)
        search = [framework]
        search.extend(value for value in (expand_path(item, image, executable) for item in rpaths)
                      if value is not None)
        records = []
        for name in names:
            if name.startswith(("/System/Library/", "/usr/lib/")):
                records.append({"loadName": name, "system": True})
                continue
            if name.startswith("@rpath/"):
                candidates = [location / name[len("@rpath/"):] for location in search]
            else:
                candidates = [expand_path(name, image, executable)]
            matched = [path.resolve() for path in candidates if path is not None and path.is_file()
                       and path.resolve().is_relative_to(app.resolve())]
            assert matched, ("External or unresolved packaged dependency", image, name, rpaths)
            records.append({"loadName": name, "resolved": matched[0].relative_to(app).as_posix()})
        result.append({"image": image.relative_to(app).as_posix(), "dependencies": records})
    assert result
    return result


# 日期：2026-11-05；新目录打包，不修改编译原件；预览只用本地adhoc签名，不冒称开发者签名或公证。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-directory", type=Path, default=Path("build"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert platform.system() == "Darwin" and platform.machine() in ("arm64", "x86_64")
    root = Path(__file__).resolve().parents[1]
    build, output = args.build_directory.resolve(), args.output.resolve()
    assert not output.exists()
    output.mkdir(parents=True)
    stage = output / ("DuktoNext-macos-" + platform.machine() + "-preview")
    stage.mkdir()
    original = build / "dukto-gui.app"
    app = stage / "Dukto Next.app"
    shutil.copytree(original, app, symlinks=True)
    cli = app / "Contents/MacOS/dukto-cli"
    shutil.copy2(build / "dukto-cli", cli)
    qt = Path(checked(["qmake", "-query", "QT_HOST_BINS"]).strip())
    deployed = checked([qt / "macdeployqt", app, "-executable=" + str(cli),
                        "-qmldir=" + str(root / "ui"), "-always-overwrite", "-verbose=2"])
    (output / "macdeployqt.log").write_text(deployed, encoding="utf-8")
    transitive = deploy_transitive(app)
    bindings = dependencies(app)
    # 日期：2026-11-05；所有bundle写入结束后再签名，重定位的库和CLI必须一起通过严格签名检查。
    checked(["codesign", "--force", "--deep", "--sign", "-", app])
    signature = checked(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    (output / "codesign.log").write_text(signature, encoding="utf-8")
    launcher = stage / "dukto-cli"
    launcher.write_text('#!/bin/sh\n# 日期：2026-11-05；保留所有参数与退出码，支持中文和空格路径。\n'
                        'base=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd) || exit 1\n'
                        'exec "$base/Dukto Next.app/Contents/MacOS/dukto-cli" "$@"\n', encoding="utf-8")
    launcher.chmod(0o755)
    shutil.copy2(root / "LICENSE", stage / "LICENSE")
    metadata = json.loads(checked(["brew", "info", "--json=v2", "--installed"]))
    (stage / "HOMEBREW-DEPENDENCIES.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 日期：2026-11-05；保存安装包附带的原始许可及其真实来源，完整对应源码/独立重建仍另行验收。
    licenses = []
    cellar = Path(checked(["brew", "--cellar"]).strip())
    for path in sorted(cellar.rglob("*")):
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024**2:
            continue
        if not re.match(r"^(?:LICENSE|COPYING|COPYRIGHT|NOTICE)(?:[._-].*)?$", path.name, re.I):
            continue
        relative = path.relative_to(cellar)
        target = stage / "third-party-licenses" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        licenses.append({"path": target.relative_to(stage).as_posix(), "source": str(path), "sha256": sha256(path)})
    source_files = source_archive(root, stage / "DuktoNext-application-source.zip")
    (stage / "README.txt").write_text(
        "Dukto Next macOS development preview\n\n"
        "Open Dukto Next.app for the GUI; run ./dukto-cli for the independent CLI.\n"
        "Qt5 runtime libraries and QML plugins are deployed inside the app.\n"
        "This preview uses a local adhoc signature. Developer ID signing, notarization,\n"
        "clean-system qualification and complete corresponding third-party sources remain pending.\n"
        "Source: https://github.com/29583855/dukto-next\n", encoding="utf-8")
    files, links = [], []
    for path in sorted(stage.rglob("*")):
        relative = path.relative_to(stage).as_posix()
        if path.is_symlink():
            assert path.resolve(strict=True).is_relative_to(stage)
            links.append({"path": relative, "target": os.readlink(path)})
        elif path.is_file():
            files.append({"path": relative, "sha256": sha256(path), "bytes": path.stat().st_size})
    manifest = {"date": datetime.now(timezone.utc).isoformat(), "architecture": platform.machine(),
                "sourceCommit": os.environ.get("GITHUB_SHA"), "files": files, "links": links,
                "dependencies": bindings, "transitiveSources": transitive,
                "licenses": licenses, "applicationSources": source_files,
                "inputCliSha256": sha256(build / "dukto-cli"),
                "inputGuiSha256": sha256(original / "Contents/MacOS/dukto-gui"),
                "signature": "adhoc", "developerIdSigned": False, "notarized": False,
                "cleanSystemQualified": False, "completeCorrespondingSourceQualified": False,
                "runtimeMigrationQualified": False, "releaseQualified": False}
    (stage / "package-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / (stage.name + ".tar.gz")
    with tarfile.open(archive, "x:gz") as target:
        target.add(stage, arcname=stage.name)
    (output / (archive.name + ".sha256")).write_text(sha256(archive) + "  " + archive.name + "\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "sha256": sha256(archive), "files": len(files),
                      "nativeImages": len(bindings), "releaseQualified": False}))


if __name__ == "__main__":
    main()
