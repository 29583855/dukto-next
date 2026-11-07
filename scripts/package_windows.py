"""日期：2026-11-05；部署 Windows UCRT 预览包，递归补齐非系统 PE 导入并记录来源、许可和逐文件摘要。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile


# 日期：2026-11-05；固定大小流式计算摘要，不把依赖 DLL 或源码归档整体放进内存。
def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


# 日期：2026-11-05；仅执行显式工具路径，失败保留完整部署诊断，不以忽略缺失库获得成功。
def checked(command, environment):
    result = subprocess.run([str(value) for value in command], env=environment,
                            capture_output=True, encoding="utf-8", errors="replace", timeout=180)
    if result.returncode:
        raise RuntimeError((command, result.returncode, result.stdout, result.stderr))
    return result


# 日期：2026-11-05；解析已安装 pacman 数据库的原始元数据及文件所有权，记录签名验证标记。
def installed_packages(msys):
    owners, packages = {}, {}
    for directory in sorted((msys / "var/lib/pacman/local").iterdir()):
        if not directory.is_dir():
            continue
        metadata = {}
        key = None
        for line in (directory / "desc").read_text(encoding="utf-8").splitlines():
            if line.startswith("%") and line.endswith("%"):
                key = line.strip("%")
                metadata[key] = []
            elif line and key:
                metadata[key].append(line)
        name = metadata["NAME"][0]
        packages[name] = metadata
        for line in (directory / "files").read_text(encoding="utf-8").splitlines():
            if line and not line.endswith("/") and not line.startswith("%"):
                owners[line.casefold()] = name
    return owners, packages


# 日期：2026-11-05；对应源码仅打包本工程维护文件，排除参考二进制、凭据、依赖安装和测试运行数据。
def source_archive(root, destination):
    paths = [root / value for value in ("CMakeLists.txt", ".clang-format", "LICENSE", "README.md", "开发计划与进度.md")]
    for folder in ("src", "ui", "resources", "scripts", "tests", ".github", "docs", "third-party/sqlite-runtime"):
        paths.extend(path for path in (root / folder).rglob("*") if path.is_file()
                     and "__pycache__" not in path.parts and "validation" not in path.relative_to(root).parts)
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for path in sorted(set(paths)):
            output.write(path, path.relative_to(root).as_posix())
    return [{"path": path.relative_to(root).as_posix(), "sha256": sha256(path)} for path in sorted(set(paths))]


# 日期：2026-11-05；从空目录生成独立预览包；缺失依赖、未知来源、文件内容变化均中止，永不覆盖既有包。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-directory", default="build/windows-ucrt")
    parser.add_argument("--qt-prefix", default=".tools/msys64/ucrt64")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    assert os.name == "nt", "Windows native packaging required"
    root = Path(__file__).resolve().parents[1]
    build, prefix, output = [Path(value).resolve() for value in
                             (args.build_directory, args.qt_prefix, args.output)]
    assert not output.exists(), "Output must be a new directory"
    output.mkdir(parents=True)
    stage = output / "DuktoNext-windows-x64-preview"
    stage.mkdir()
    environment = os.environ.copy()
    environment["PATH"] = str(prefix / "bin") + os.pathsep + environment["PATH"]
    for binary in ("dukto-cli.exe", "dukto-gui.exe"):
        shutil.copyfile(build / binary, stage / binary)
    deployed = checked([prefix / "bin/windeployqt-qt5.exe", "--release", "--no-patchqt", "--qmldir", root / "ui",
                        "--no-angle", "--no-opengl-sw", "--no-system-d3d-compiler", "--no-translations", "--json",
                        stage / "dukto-gui.exe", stage / "dukto-cli.exe"], environment)
    (output / "windeployqt.log").write_text(deployed.stderr, encoding="utf-8")
    mapping = {}
    for item in json.loads(deployed.stdout)["files"]:
        source = Path(item["source"])
        target = Path(item["target"]) / source.name
        assert target.is_relative_to(stage)
        if source.is_file() and target.is_file():
            assert sha256(source) == sha256(target), (source, target)
            mapping[target.relative_to(stage).as_posix()] = source
    # 日期：2026-11-05；应用仅使用 SQLite；不部署需要外部数据库客户端的未使用驱动。
    for path in (stage / "sqldrivers").glob("*.dll"):
        if path.name.casefold() != "qsqlite.dll":
            mapping.pop(path.relative_to(stage).as_posix(), None)
            path.unlink()
    for name in ("libssl-3-x64.dll", "libcrypto-3-x64.dll"):
        source = prefix / "bin" / name
        shutil.copyfile(source, stage / name)
        mapping[name] = source
    system_directory = Path(os.environ["SystemRoot"]) / "System32"
    os_imports, imports, scanned = set(), {}, set()
    while True:
        pending = [path for path in stage.rglob("*") if path.suffix.lower() in (".exe", ".dll") and path not in scanned]
        if not pending:
            break
        for binary in pending:
            scanned.add(binary)
            details = checked([prefix / "bin/objdump.exe", "-p", binary], environment).stdout
            names = sorted(set(re.findall(r"DLL Name:\s*(\S+)", details)))
            assert names, binary
            imports[binary.relative_to(stage).as_posix()] = names
            for name in names:
                if name.lower().startswith(("api-ms-win-", "ext-ms-win-")):
                    os_imports.add(name.lower())
                    continue
                dependency = prefix / "bin" / name
                if dependency.is_file():
                    target = stage / name
                    if not target.exists():
                        shutil.copyfile(dependency, target)
                    assert sha256(dependency) == sha256(target)
                    mapping[name] = dependency
                elif (system_directory / name).is_file():
                    os_imports.add(name.lower())
                else:
                    raise RuntimeError(("Unresolved PE import", binary.name, name))
    (stage / "qt.conf").write_text("[Paths]\nPrefix=.\nPlugins=.\nQml2Imports=.\n", encoding="utf-8")
    owners, packages = installed_packages(prefix.parent)
    used = set()
    provenance = []
    for relative, source in sorted(mapping.items()):
        installed_path = source.relative_to(prefix.parent).as_posix()
        owner = owners.get(installed_path.casefold())
        assert owner, ("Unknown dependency owner", source)
        used.add(owner)
        provenance.append({"path": relative, "installedPath": installed_path, "package": owner,
                           "sha256": sha256(stage / relative)})
    notices = stage / "licenses"
    notices.mkdir()
    shutil.copyfile(root / "LICENSE", notices / "DuktoNext-GPL-3.0-or-later.txt")
    # 日期：2026-11-05；GCC 拆分运行库的许可可归属于基础包，完整复制已安装许可目录并保留所属元数据。
    shutil.copytree(prefix / "share/licenses", notices / "dependencies")
    # 日期：2026-11-05；ICU 将许可放在 share/icu/版本下，不能只复制 share/licenses 而遗漏实际部署组件。
    additional_licenses = []
    icu_package = "mingw-w64-ucrt-x86_64-icu"
    if icu_package in used:
        version = packages[icu_package]["VERSION"][0].split("-", 1)[0].rsplit(":", 1)[-1]
        assert re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", version), version
        source = prefix / "share/icu" / version / "LICENSE"
        installed_path = source.relative_to(prefix.parent).as_posix()
        assert source.is_file() and owners.get(installed_path.casefold()) == icu_package
        target = notices / "dependencies/icu/LICENSE"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert sha256(target) == sha256(source), "Conflicting ICU license"
        else:
            shutil.copyfile(source, target)
        additional_licenses.append({"path": target.relative_to(stage).as_posix(), "installedPath": installed_path,
                                    "package": icu_package, "sha256": sha256(target)})
    (stage / "dependency-packages.json").write_text(json.dumps(
        {name: packages[name] for name in sorted(used)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    source_files = source_archive(root, stage / "DuktoNext-corresponding-source.zip")
    (stage / "README.txt").write_text(
        "Dukto Next Windows x64 development preview\n\n"
        "Run dukto-gui.exe for the desktop UI; run dukto-cli.exe --help in a terminal.\n"
        "Both programs run independently. No Qt developer installation is required.\n"
        "The desktop UI uses the Qt software renderer. The CLI does not load desktop modules.\n"
        "State uses platform user directories; CLI --state-directory and GUI --data-directory allow isolation.\n"
        "TLS server traffic uses 4646 by default; legacy R6 uses 4644 and has no authentication.\n"
        "See licenses/ and dependency-packages.json for dependency terms and exact versions.\n"
        "Application corresponding source is included. This is a local development preview.\n"
        "Release qualification still requires clean-system validation and exact third-party source distribution.\n",
        encoding="utf-8")
    files = [{"path": path.relative_to(stage).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}
             for path in sorted(stage.rglob("*")) if path.is_file()]
    report = {"date": datetime.now(timezone.utc).isoformat(), "platform": "windows-x64-ucrt",
              "kind": "development-preview", "releaseQualified": False, "files": files,
              "dependencyFiles": provenance, "peImports": imports, "windowsSystemImports": sorted(os_imports),
              "sourceFiles": source_files, "deployer": packages.get("mingw-w64-ucrt-x86_64-qt5-tools"),
              "additionalLicenseFiles": additional_licenses,
              "openReleaseChecks": ["clean Windows installation", "exact third-party corresponding source distribution",
                                    "complete product and cross-platform acceptance"]}
    (stage / "package-manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / (stage.name + ".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(output).as_posix())
    digest = sha256(archive)
    (output / "SHA256SUMS").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
    print(json.dumps({"archive": str(archive), "sha256": digest, "files": len(files) + 1,
                      "dependencyPackages": len(used), "releaseQualified": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
