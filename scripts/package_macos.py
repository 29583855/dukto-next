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
from package_build import refresh_build, verify_build
from macos_compatibility import audit_app, is_macho


# 日期：2026-11-05；仅执行显式工具参数，原生部署/签名/依赖检查任一失败都中止。
def checked(command, timeout=300, log=None):
    try:
        result = subprocess.run([str(value) for value in command], capture_output=True,
                                encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as error:
        # 日期：2026-11-05；部署工具超时仍失败并保存真实部分输出，不能丢弃工具运行到的阶段。
        if log is not None:
            parts = [value.decode("utf-8", "replace") if isinstance(value, bytes) else value or ""
                     for value in (error.stdout, error.stderr)]
            log.write_text("".join(parts), encoding="utf-8")
        raise
    output = result.stdout + result.stderr
    if log is not None:
        log.write_text(output, encoding="utf-8")
    if result.returncode:
        raise RuntimeError((command, result.returncode, result.stdout, result.stderr))
    return output


# 日期：2026-11-05；只检查真实Mach-O文件，框架符号链接由最终归档清单单列。
def native_file(path):
    return is_macho(path)


# 日期：2026-11-05；展开loader/executable相对路径，绝对非系统依赖必须位于包中。
def expand_path(value, image, executable):
    for prefix, location in (("@loader_path", image.parent), ("@executable_path", executable.parent)):
        if value == prefix or value.startswith(prefix + "/"):
            return (location / value[len(prefix):].lstrip("/")).resolve()
    return Path(value).resolve() if value.startswith("/") else None


# 日期：2026-11-09；直接按加载命令类型识别依赖，裸文件名形式的库自身ID也不能误当外部依赖。
def parse_dylib_loads(commands):
    names = []
    for block in re.split(r"^Load command \d+\s*$", commands, flags=re.M):
        command = re.search(r"^\s*cmd (LC_\w+)\s*$", block, re.M)
        if command is None or command.group(1) not in (
                "LC_LOAD_DYLIB", "LC_LOAD_WEAK_DYLIB", "LC_REEXPORT_DYLIB",
                "LC_LAZY_LOAD_DYLIB", "LC_LOAD_UPWARD_DYLIB"):
            continue
        name = re.search(r"^\s*name (.+?) \(offset \d+\)\s*$", block, re.M)
        if name is None:
            raise ValueError("Dylib load command has no install name")
        names.append(name.group(1))
    return list(dict.fromkeys(names))


# 日期：2026-11-09；读取实际LC_LOAD命令，避免otool -L将LC_ID_DYLIB混入依赖列表导致无效重写循环。
def load_names(image):
    return parse_dylib_loads(checked(["otool", "-l", image]))


# 日期：2026-11-09；只从明确的依赖源码安装根或旧Cellar复制精确匹配的传递库。
def deploy_transitive(app, roots):
    roots = [path.resolve(strict=True) for path in roots]
    framework = app / "Contents/Frameworks"
    framework.mkdir(exist_ok=True)
    executable = app / "Contents/MacOS/dukto-gui"
    for image in (executable, app / "Contents/MacOS/dukto-cli"):
        commands = checked(["otool", "-l", image])
        if "path @executable_path/../Frameworks (offset" not in commands:
            checked(["install_name_tool", "-add_rpath", "@executable_path/../Frameworks", image])
    index, copied = None, []
    for attempt in range(64):
        changed = False
        images = sorted(path for path in app.rglob("*")
                        if path.is_file() and not path.is_symlink() and native_file(path))
        for image in images:
            names = load_names(image)
            for name in names:
                if name.startswith(("/System/Library/", "/usr/lib/")):
                    continue
                direct = expand_path(name, image, executable)
                bundled = framework / name[len("@rpath/"):] if name.startswith("@rpath/") else direct
                if bundled is not None and bundled.is_file() and bundled.resolve().is_relative_to(app):
                    continue
                if ".framework/" in name:
                    position = name.index(".framework/")
                    relative = name[name.rfind("/", 0, position) + 1:]
                    target = framework / relative
                    if not target.is_file():
                        source = direct
                        if source is None:
                            source = Path(checked(["qmake", "-query", "QT_INSTALL_LIBS"]).strip()) / relative
                        source = source.resolve(strict=True)
                        assert any(source.is_relative_to(root) for root in roots), ("Framework outside declared dependency roots", source)
                        index_part = next(index for index, part in enumerate(source.parts) if part.endswith(".framework"))
                        source_root = Path(*source.parts[:index_part + 1])
                        destination = framework / source_root.name
                        assert not destination.exists(), ("Partial framework cannot be overwritten", destination)
                        shutil.copytree(source_root, destination, symlinks=True)
                        target.chmod(target.stat().st_mode | 0o200)
                        checked(["install_name_tool", "-id", "@rpath/" + relative, target])
                        copied.append({"path": target.relative_to(app).as_posix(), "source": str(source),
                                       "originalSha256": sha256(source)})
                    checked(["install_name_tool", "-change", name,
                             "@executable_path/../Frameworks/" + relative, image])
                    if name in load_names(image):
                        raise RuntimeError(("Framework load name did not change", image, name))
                    print(json.dumps({"pass": attempt, "image": str(image), "rewritten": name}), flush=True)
                    changed = True
                    continue
                filename = Path(name).name
                if direct is not None and direct.is_file():
                    candidates = {direct.resolve()}
                else:
                    if index is None:
                        index = {}
                        for root in roots:
                            for path in root.rglob("*.dylib"):
                                if path.is_file():
                                    index.setdefault(path.name, set()).add(path.resolve())
                    candidates = index.get(filename, set())
                assert candidates and all(any(path.is_relative_to(root) for root in roots) for path in candidates), (image, name, candidates)
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
                if name in load_names(image):
                    raise RuntimeError(("Dylib load name did not change", image, name, replacement))
                print(json.dumps({"pass": attempt, "image": str(image), "rewritten": name}), flush=True)
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
        names = load_names(image)
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
    parser.add_argument("--minimum-macos", default="12.0")
    parser.add_argument("--dependency-root", type=Path, action="append", default=[])
    parser.add_argument("--dependency-manifest", type=Path)
    args = parser.parse_args()
    assert platform.system() == "Darwin" and platform.machine() in ("arm64", "x86_64")
    root = Path(__file__).resolve().parents[1]
    build, output = args.build_directory.resolve(), args.output.resolve()
    assert not output.exists()
    output.mkdir(parents=True)
    build_provenance = refresh_build(root, build, ["dukto-cli", "dukto-gui.app/Contents/MacOS/dukto-gui"],
                                     output / "build-refresh.log")
    stage = output / ("DuktoNext-macos-" + platform.machine() + "-preview")
    stage.mkdir()
    original = build / "dukto-gui.app"
    app = stage / "Dukto Next.app"
    shutil.copytree(original, app, symlinks=True)
    cli = app / "Contents/MacOS/dukto-cli"
    shutil.copy2(build / "dukto-cli", cli)
    qt = Path(checked(["qmake", "-query", "QT_HOST_BINS"]).strip())
    # 日期：2026-11-05；Intel原生部署曾超过工具300秒预算，改为有界900秒；业务测试原时限保持。
    checked([qt / "macdeployqt", app, "-executable=" + str(cli),
             "-qmldir=" + str(root / "ui"), "-always-overwrite", "-verbose=2"],
            timeout=900, log=output / "macdeployqt.log")
    roots = args.dependency_root or [Path(checked(["brew", "--cellar"]).strip())]
    roots = [path.resolve(strict=True) for path in roots]
    transitive = deploy_transitive(app, roots)
    bindings = dependencies(app)
    compatibility = audit_app(app, args.minimum_macos, platform.machine())
    (output / "macos-compatibility.json").write_text(
        json.dumps(compatibility, indent=2) + "\n", encoding="utf-8")
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
    if args.dependency_manifest:
        metadata = json.loads(args.dependency_manifest.read_text(encoding="utf-8"))
        if metadata["minimumMacOS"] != args.minimum_macos:
            raise ValueError("Dependency build baseline differs from application baseline")
        metadata_name = "SOURCE-DEPENDENCIES.json"
    else:
        metadata = json.loads(checked(["brew", "info", "--json=v2", "--installed"]))
        metadata_name = "HOMEBREW-DEPENDENCIES.json"
    (stage / metadata_name).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # 日期：2026-11-05；保存安装包附带的原始许可及其真实来源，完整对应源码/独立重建仍另行验收。
    licenses = []
    for dependency_root in roots:
        for path in sorted(dependency_root.rglob("*")):
            if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024**2:
                continue
            if not re.match(r"^(?:LICENSE|COPYING|COPYRIGHT|NOTICE)(?:[._-].*)?$", path.name, re.I):
                continue
            relative = Path(dependency_root.name) / path.relative_to(dependency_root)
            target = stage / "third-party-licenses" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            licenses.append({"path": target.relative_to(stage).as_posix(), "source": str(path), "sha256": sha256(path)})
    source_files = source_archive(root, stage / "DuktoNext-application-source.zip")
    (stage / "README.txt").write_text(
        "Dukto Next macOS development preview\n\n"
        "Open Dukto Next.app for the GUI; run ./dukto-cli for the independent CLI.\n"
        "Qt5 runtime libraries and QML plugins are deployed inside the app.\n"
        f"Minimum macOS: {args.minimum_macos}; architecture: {platform.machine()}.\n"
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
    verify_build(root, build, build_provenance)
    manifest = {"date": datetime.now(timezone.utc).isoformat(), "architecture": platform.machine(),
                "buildProvenance": build_provenance,
                "minimumMacOS": args.minimum_macos, "compatibilityAudit": compatibility,
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
