"""日期：2026-11-05；在原生 Ubuntu glibc 环境构建 GUI/独立 CLI 预览包并记录 ELF、QML 和发行版来源。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile

from package_windows import sha256, source_archive
from package_build import refresh_build, verify_build


# 日期：2026-11-05；仅执行显式工具及参数列表，工具失败或依赖缺失均中止生成。
def checked(command):
    result = subprocess.run([str(value) for value in command], capture_output=True,
                            encoding="utf-8", errors="replace", timeout=180)
    if result.returncode:
        raise RuntimeError((command, result.returncode, result.stdout, result.stderr))
    return result.stdout


# 日期：2026-11-05；文件复制绑定真实来源与摘要；同名 ELF 不同内容明确拒绝，不靠覆盖先后选择版本。
def copy_file(source, target, stage, mapping):
    source = source.resolve(strict=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        assert sha256(source) == sha256(target), ("Conflicting dependency", source, target)
    else:
        shutil.copyfile(source, target)
        shutil.copymode(source, target)
    mapping[target.relative_to(stage).as_posix()] = source


# 日期：2026-11-05；只枚举 Qt 工具报告的导入和显式运行插件；复制时展开发行版内部符号链接。
def copy_directory(source, target, stage, mapping):
    assert source.is_dir(), source
    for path in sorted(source.rglob("*")):
        if path.is_file():
            copy_file(path, target / path.relative_to(source), stage, mapping)


# 日期：2026-11-09；只读取ELF需求节，定义节的导出版本不能被误认成应用实际需要的glibc版本。
def required_glibc(text):
    needs = False
    versions = set()
    features = {}
    for line in text.splitlines():
        if re.match(r"^Version .* section ", line):
            needs = line.startswith("Version needs section ")
        if not needs:
            continue
        for name in re.findall(r"\bName:\s+(GLIBC_[A-Za-z0-9_.]+)\b", line):
            numeric = re.fullmatch(r"GLIBC_(\d+\.\d+(?:\.\d+)?)", name)
            if numeric:
                versions.add(numeric.group(1))
            elif name == "GLIBC_ABI_DT_RELR":
                # 日期：2026-11-09；此加载器能力从glibc2.36提供，不是可忽略的普通非数字标签。
                features[name] = "2.36"
            else:
                raise RuntimeError("Unsupported required glibc ABI: " + name)
    return {"versions": sorted(versions, key=version_tuple), "features": features}


# 日期：2026-11-09；按数值比较2.9、2.35和2.2.5，不使用字符串排序推断最低加载器版本。
def version_tuple(value):
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise ValueError("Invalid glibc version: " + value)
    return tuple(int(part) for part in value.split('.'))


# 日期：2026-11-09；每个实际部署ELF逐项取证；未知私有ABI拒绝，宿主版本不替代载荷需求观察。
def glibc_abi(stage, elf_paths):
    versions, features, files = set(), {}, []
    for relative in sorted(elf_paths):
        observed = required_glibc(checked(["env", "LC_ALL=C", "readelf", "--version-info", "--wide", stage / relative]))
        versions.update(observed["versions"])
        features.update(observed["features"])
        files.append(dict(path=relative, **observed))
    candidates = versions | set(features.values())
    if not candidates:
        raise RuntimeError("No glibc version requirement found in deployed ELF payload")
    return {"minimumVersion": max(candidates, key=version_tuple),
            "requiredVersions": sorted(versions, key=version_tuple),
            "featureMinimumVersions": features, "elfFiles": files,
            "scope": "ELF symbol and loader ABI requirements; complete OS compatibility requires runtime validation"}


# 日期：2026-11-09；生成当前原生系统的glibc预览并记录实际ABI，不把musl或未测发行版记为兼容通过。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-directory", default="build")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    assert os.name == "posix" and os.uname().sysname == "Linux" and os.uname().machine == "x86_64"
    build_glibc = checked(["getconf", "GNU_LIBC_VERSION"]).strip()
    assert re.fullmatch(r"glibc \d+\.\d+(?:\.\d+)?", build_glibc), build_glibc
    root = Path(__file__).resolve().parents[1]
    build, output = Path(args.build_directory).resolve(), Path(args.output).resolve()
    assert not output.exists(), "Output must be a new directory"
    output.mkdir(parents=True)
    build_provenance = refresh_build(root, build, ["dukto-cli", "dukto-gui"],
                                     output / "build-refresh.log")
    stage = output / "DuktoNext-linux-glibc-x64-preview"
    stage.mkdir()
    mapping = {}
    for name in ("dukto-cli", "dukto-gui"):
        copy_file(build / name, stage / "bin" / name, stage, mapping)
    qml = Path(checked(["qmake", "-query", "QT_INSTALL_QML"]).strip())
    plugins = Path(checked(["qmake", "-query", "QT_INSTALL_PLUGINS"]).strip())
    host_bins = Path(checked(["qmake", "-query", "QT_HOST_BINS"]).strip())
    imports = json.loads(checked([host_bins / "qmlimportscanner", "-rootPath", root / "ui", "-importPath", qml]))
    for item in imports:
        if item.get("type") != "module":
            continue
        assert item.get("path"), ("Unresolved QML import", item)
        source = Path(item["path"])
        assert source.is_relative_to(qml), source
        copy_directory(source, stage / "qml" / source.relative_to(qml), stage, mapping)
    plugin_files = ["platforms/libqxcb.so", "platforms/libqoffscreen.so", "platforms/libqminimal.so",
                    "platforms/libqwayland-egl.so", "platforms/libqwayland-generic.so", "sqldrivers/libqsqlite.so"]
    for name in plugin_files:
        copy_file(plugins / name, stage / "plugins" / name, stage, mapping)
    for folder in ("imageformats", "wayland-shell-integration", "wayland-graphics-integration-client",
                   "wayland-decoration-client", "xcbglintegrations"):
        copy_directory(plugins / folder, stage / "plugins" / folder, stage, mapping)
    ldconfig = checked(["/sbin/ldconfig", "-p"])
    for name in ("libssl.so.3", "libcrypto.so.3"):
        match = re.search(r"^\s*" + re.escape(name) + r"\s.*=>\s*(\S+)", ldconfig, re.M)
        assert match, name
        copy_file(Path(match[1]), stage / "lib" / name, stage, mapping)
    # 日期：2026-11-05；Qt 先尝试 libssl.so/libcrypto.so；显式同目录别名防止误载系统开发库。
    aliases = {"lib/libcrypto.so": "libcrypto.so.3", "lib/libssl.so": "libssl.so.3"}
    for relative, target in aliases.items():
        alias = stage / relative
        assert alias.parent == stage / "lib" and (alias.parent / target).is_file()
        alias.symlink_to(target)
    system_names = {"libc.so.6", "libm.so.6", "libpthread.so.0", "libdl.so.2", "librt.so.1", "libresolv.so.2", "libutil.so.1"}
    scanned, dependencies, system = set(), {}, set()
    while True:
        pending = []
        for relative, source in mapping.items():
            target = stage / relative
            if relative not in scanned:
                with target.open("rb") as stream:
                    if stream.read(4) == b"\x7fELF":
                        pending.append((relative, source))
        if not pending:
            break
        for relative, source in pending:
            scanned.add(relative)
            text = checked(["ldd", source])
            assert "not found" not in text, (source, text)
            names = []
            for name, location in re.findall(r"^\s*(\S+)\s+=>\s+(\S+)\s+\(", text, re.M):
                names.append(name)
                path = Path(location)
                assert path.is_absolute() and path.is_file(), (name, location)
                if name in system_names:
                    system.add(name)
                else:
                    copy_file(path, stage / "lib" / name, stage, mapping)
            dependencies[relative] = names
    abi = glibc_abi(stage, scanned)
    assert version_tuple(abi["minimumVersion"]) <= version_tuple(build_glibc.split()[1]), abi
    (stage / "bin/qt.conf").write_text("[Paths]\nPrefix=..\nPlugins=plugins\nQml2Imports=qml\n", encoding="utf-8")
    for name in ("dukto-cli", "dukto-gui"):
        launcher = stage / name
        # 日期：2026-11-05；仅 GUI 默认软件 EGL，避免无硬件驱动主机初始化失败；用户可显式选择硬件。
        graphics_environment = 'export LIBGL_ALWAYS_SOFTWARE="${LIBGL_ALWAYS_SOFTWARE:-1}"\n' if name == "dukto-gui" else ""
        launcher.write_text('#!/bin/sh\nset -eu\nbase=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                            'export LD_LIBRARY_PATH="$base/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"\n'
                            'export QT_PLUGIN_PATH="$base/plugins"\nexport QML2_IMPORT_PATH="$base/qml"\n'
                            + graphics_environment + f'exec "$base/bin/{name}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    packages, provenance = {}, []
    for relative, source in sorted(mapping.items()):
        if source.is_relative_to(build):
            continue
        package = checked(["dpkg-query", "-S", source]).splitlines()[0].rsplit(": ", 1)[0]
        assert ", " not in package, (source, package)
        if package not in packages:
            fields = checked(["dpkg-query", "-W", "-f=${Package}\\t${Version}\\t${source:Package}\\t${source:Version}\\n", package]).strip().split("\t")
            assert len(fields) == 4, fields
            packages[package] = dict(zip(("package", "version", "sourcePackage", "sourceVersion"), fields))
            copyright_file = Path("/usr/share/doc") / fields[0] / "copyright"
            assert copyright_file.is_file(), copyright_file
            destination = stage / "licenses" / fields[0] / "copyright"
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(copyright_file, destination)
        provenance.append({"path": relative, "sourcePath": str(source), "package": package, "sha256": sha256(stage / relative)})
    shutil.copyfile(root / "LICENSE", stage / "licenses/DuktoNext-GPL-3.0-or-later.txt")
    (stage / "dependency-packages.json").write_text(json.dumps(packages, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sources = source_archive(root, stage / "DuktoNext-corresponding-source.zip")
    (stage / "README.txt").write_text(
        "Dukto Next Linux x86_64 glibc development preview\n\n"
        "Run ./dukto-gui or ./dukto-cli --help. Use these launchers, which set the bundled runtime paths.\n"
        f"ELF payload requires glibc {abi['minimumVersion']} or newer; build host uses {build_glibc}.\n"
        "X11 or Wayland and suitable system fonts are required; see package-manifest.json for the tested distribution.\n"
        "The CLI runs independently without a desktop session. The GUI uses Qt software rendering.\n"
        "The GUI defaults LIBGL_ALWAYS_SOFTWARE to 1; set it explicitly to 0 to choose hardware EGL.\n"
        "A compatible host Mesa/EGL implementation and its driver dependencies are required for Wayland.\n"
        "Application source and installed dependency copyright notices are included.\n"
        "Exact third-party source distribution, clean OS and complete product qualification remain open.\n",
        encoding="utf-8")
    files = [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
             for path in sorted(stage.rglob("*")) if path.is_file()]
    verify_build(root, build, build_provenance)
    report = {"date": datetime.now(timezone.utc).isoformat(), "kind": "development-preview", "releaseQualified": False,
              "buildProvenance": build_provenance,
              "platform": "linux-x86_64-glibc", "sourceCommit": os.environ.get("GITHUB_SHA"),
              "inputCliSha256": sha256(build / "dukto-cli"), "inputGuiSha256": sha256(build / "dukto-gui"),
              "buildGlibc": build_glibc, "glibcAbi": abi,
              "distribution": Path("/etc/os-release").read_text(encoding="utf-8"), "files": files,
              "dependencyFiles": provenance, "elfDependencies": dependencies, "hostSystemLibraries": sorted(system),
              "qmlImports": imports, "sourceFiles": sources, "libraryAliases": aliases,
              "guiRuntimePolicy": {"LIBGL_ALWAYS_SOFTWARE": "default 1, user override supported",
                                   "waylandDecorationPlugins": True,
                                   "hostGraphicsDriverRequired": True},
              "hostSystemRequirements": [f"glibc {abi['minimumVersion']} or newer", "X11 or Wayland for GUI", "system fonts",
                                         "compatible Mesa/EGL and graphics driver dependencies for Wayland"],
              "openReleaseChecks": ["clean OS", "exact third-party source distribution", "complete product qualification"]}
    (stage / "package-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / (stage.name + ".tar.gz")
    with tarfile.open(archive, "x:gz") as bundle:
        bundle.add(stage, arcname=stage.name, recursive=True)
    checksum = sha256(archive)
    (output / "SHA256SUMS").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "sha256": checksum, "dependencyPackages": len(packages),
                      "files": len(files) + 1, "releaseQualified": False}))


if __name__ == "__main__":
    main()
