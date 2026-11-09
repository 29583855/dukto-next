"""日期：2026-11-09；从固定源码构建macOS 12依赖，避免Homebrew瓶装库抬高系统要求。"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import urllib.request


# 日期：2026-11-09；逐条记录构建命令和真实输出，失败立即中止并保留原日志。
def run(command, directory, environment, log):
    with log.open("ab") as output:
        output.write((json.dumps([str(part) for part in command]) + "\n").encode())
        output.flush()
        subprocess.run([str(part) for part in command], cwd=directory, env=environment,
                       stdout=output, stderr=subprocess.STDOUT, check=True, timeout=7200)


# 日期：2026-11-09；只接受预先固定摘要的官方源码，拒绝目录穿越和已有解压目录。
def extract(source, work):
    archive = work / Path(source["url"]).name
    with urllib.request.urlopen(source["url"], timeout=120) as response, archive.open("xb") as output:
        shutil.copyfileobj(response, output)
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != source["sha256"]:
        raise ValueError("Dependency source SHA-256 mismatch: " + source["name"])
    destination = work / source["name"]
    destination.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(destination, filter="data")
    directories = list(destination.iterdir())
    if len(directories) != 1 or not directories[0].is_dir():
        raise ValueError("Unexpected dependency source layout")
    return directories[0]


# 日期：2026-11-09；将依赖原许可随安装结果保存，归档中可以追溯精确上游和构建脚本。
def licenses(source, prefix, name):
    destination = prefix / "share/dukto-licenses" / name
    destination.mkdir(parents=True)
    for path in source.iterdir():
        if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
            shutil.copy2(path, destination / path.name)
    if (source / "LICENSES").is_dir():
        shutil.copytree(source / "LICENSES", destination / "LICENSES")


# 日期：2026-11-09；仅构建所需Qt模块，统一部署目标并使用Qt内置第三方库及同目标OpenSSL。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--work", type=Path, default=Path("dependency-build"))
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() not in ("arm64", "x86_64"):
        raise ValueError("Native macOS build required")
    prefix, work = args.prefix.resolve(), args.work.resolve()
    lock = json.loads(Path(__file__).with_name("macos_dependencies.json").read_text("utf-8"))
    work.mkdir(parents=True, exist_ok=True)
    prefix.mkdir(parents=True, exist_ok=True)
    qt, openssl = prefix / "qt", prefix / "openssl"
    environment = {**os.environ, "MACOSX_DEPLOYMENT_TARGET": lock["minimumMacOS"],
                   "PATH": str(qt / "bin") + os.pathsep + os.environ["PATH"],
                   "OPENSSL_LIBS": "-L" + str(openssl / "lib") + " -lssl -lcrypto"}
    sources = {item["name"]: extract(item, work) for item in lock["sources"]}
    architecture = platform.machine()
    target = "darwin64-arm64-cc" if architecture == "arm64" else "darwin64-x86_64-cc"
    run(["./Configure", target, "shared", "no-tests", "--prefix=" + str(openssl),
         "--libdir=lib", "--openssldir=" + str(openssl / "ssl"),
         "-mmacosx-version-min=" + lock["minimumMacOS"], "-Wl,-headerpad_max_install_names"],
        sources["openssl"], environment, work / "openssl.log")
    run(["make", "-j" + str(args.jobs)], sources["openssl"], environment, work / "openssl.log")
    run(["make", "install_sw"], sources["openssl"], environment, work / "openssl.log")
    licenses(sources["openssl"], openssl, "openssl")
    # 日期：2026-11-09；AGL已从新SDK移除；回移上游Qt6同等修正，保留修改前后摘要。
    config = sources["qtbase"] / "mkspecs/common/mac.conf"
    original = config.read_bytes()
    patched = original.replace(b"/System/Library/Frameworks/OpenGL.framework/Headers \\\n"
                               b"    /System/Library/Frameworks/AGL.framework/Headers/",
                               b"/System/Library/Frameworks/OpenGL.framework/Headers")
    patched = patched.replace(b"-framework OpenGL -framework AGL", b"-framework OpenGL")
    config.write_bytes(patched)
    base_build = work / "qtbase-build"
    base_build.mkdir()
    options = ["-prefix", str(qt), "-release", "-opensource", "-confirm-license",
               "-nomake", "examples", "-nomake", "tests", "-no-pch", "-no-pkg-config",
               "-no-glib", "-no-icu", "-no-dbus", "-no-zstd", "-no-feature-brotli",
               "-qt-zlib", "-qt-pcre", "-qt-doubleconversion", "-qt-harfbuzz", "-qt-freetype",
               "-qt-libpng", "-qt-libjpeg", "-qt-sqlite", "-openssl-linked",
               "-I", str(openssl / "include"), "-L", str(openssl / "lib"),
               "QMAKE_MACOSX_DEPLOYMENT_TARGET=" + lock["minimumMacOS"],
               "QMAKE_APPLE_DEVICE_ARCHS=" + architecture,
               "QMAKE_CXXFLAGS+=-Wno-enum-constexpr-conversion"]
    run([sources["qtbase"] / "configure", *options], base_build, environment, work / "qtbase.log")
    run(["make", "-j" + str(args.jobs)], base_build, environment, work / "qtbase.log")
    run(["make", "install"], base_build, environment, work / "qtbase.log")
    licenses(sources["qtbase"], qt, "qtbase")
    for name in ("qtdeclarative", "qtquickcontrols2", "qtgraphicaleffects"):
        build = work / (name + "-build")
        build.mkdir()
        run([qt / "bin/qmake", sources[name]], build, environment, work / (name + ".log"))
        run(["make", "-j" + str(args.jobs)], build, environment, work / (name + ".log"))
        run(["make", "install"], build, environment, work / (name + ".log"))
        licenses(sources[name], qt, name)
    deploy_build = work / "macdeployqt-build"
    deploy_build.mkdir()
    run([qt / "bin/qmake", sources["qttools"] / "src/macdeployqt/macdeployqt.pro"],
        deploy_build, environment, work / "macdeployqt.log")
    run(["make", "-j" + str(args.jobs)], deploy_build, environment, work / "macdeployqt.log")
    run(["make", "install"], deploy_build, environment, work / "macdeployqt.log")
    licenses(sources["qttools"], qt, "qttools")
    receipt = {**lock, "architecture": architecture, "sourceBuild": True,
               "qtBaseMacConfOriginalSha256": hashlib.sha256(original).hexdigest(),
               "qtBaseMacConfPatchedSha256": hashlib.sha256(patched).hexdigest(),
               "builderSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "hostVersion": platform.mac_ver()[0]}
    (prefix / "dependency-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
