"""日期：2026-11-25；以锁定源码独立构建完整Qt模拟器应用，不复用iphoneos库。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_dependencies import extract, run
from collect_licenses import licenses


# 日期：2026-11-25；依赖缓存专用于当前模拟器工具链；原设备构建入口及缓存不变。
def dependencies(root, prefix, work, environment):
    lock = json.loads((root / "scripts/dependencies.json").read_text("utf-8"))
    selected = {"openssl", "qtbase", "qtdeclarative", "qtquickcontrols2", "qtgraphicaleffects"}
    sources = {entry["name"]: extract(entry, work) for entry in lock["sources"]
               if entry["name"] in selected}
    qt, openssl = prefix / "qt", prefix / "openssl"
    environment["OPENSSL_LIBS"] = "-L" + str(openssl / "lib") + " -lssl -lcrypto"
    run(["./Configure", "iossimulator-arm64-xcrun", "no-shared", "no-tests", "-fPIC",
         "-mios-simulator-version-min=15.0", "--prefix=" + str(openssl), "--libdir=lib"],
        sources["openssl"], environment, work / "openssl.log")
    run(["make", "-j3"], sources["openssl"], environment, work / "openssl.log")
    run(["make", "install_sw"], sources["openssl"], environment, work / "openssl.log")
    # 日期：2026-11-25；沿用已核对的Qt5现代macOS宿主AGL头文件路径兼容修正。
    config = sources["qtbase"] / "mkspecs/common/mac.conf"
    original = config.read_bytes()
    old_headers = (b"/System/Library/Frameworks/OpenGL.framework/Headers " + bytes([92, 10]) +
                   b"    /System/Library/Frameworks/AGL.framework/Headers/")
    patched = original.replace(old_headers, b"/System/Library/Frameworks/OpenGL.framework/Headers")
    patched = patched.replace(b"-framework OpenGL -framework AGL", b"-framework OpenGL")
    config.write_bytes(patched)
    options = ["-prefix", str(qt), "-release", "-opensource", "-confirm-license", "-static",
               "-xplatform", "macx-ios-clang", "-sdk", "iphonesimulator",
               "QMAKE_IOS_DEPLOYMENT_TARGET=15.0", "QMAKE_APPLE_SIMULATOR_ARCHS=arm64",
               "-nomake", "examples", "-nomake", "tests", "-no-pch", "-no-pkg-config",
               "-no-glib", "-no-icu", "-no-dbus", "-no-zstd", "-qt-zlib", "-qt-pcre",
               "-qt-doubleconversion", "-qt-harfbuzz", "-qt-freetype", "-qt-libpng",
               "-qt-libjpeg", "-qt-sqlite", "-openssl-linked", "-I", str(openssl / "include"),
               "-L", str(openssl / "lib"), "QMAKE_CXXFLAGS+=-Wno-enum-constexpr-conversion"]
    for name in ["qtbase", "qtdeclarative", "qtquickcontrols2", "qtgraphicaleffects"]:
        build = work / (name + "-build")
        build.mkdir()
        command = [sources[name] / "configure", *options] if name == "qtbase" else [qt / "bin/qmake", sources[name]]
        run(command, build, environment, work / (name + ".log"))
        run(["make", "-j3"], build, environment, work / (name + ".log"))
        run(["make", "install"], build, environment, work / (name + ".log"))
    for name, source in sources.items():
        licenses(source, prefix, name)
    manifest = {"platform": "ios-simulator-arm64", "dependencies": lock,
                "sourceBuild": True, "deviceTestsPassed": False,
                "builderSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (prefix / "simulator-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", "utf-8")


# 日期：2026-11-25；完整业务核心和QML使用同一模拟器SDK，不将设备arm64误当模拟器arm64。
def application(root, prefix, build, environment):
    qt, openssl = prefix / "qt", prefix / "openssl"
    core, app = build / "core", build / "app"
    app.mkdir(parents=True, exist_ok=True)
    log = build / "application.log"
    run(["cmake", "-S", root, "-B", core, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
         "-DCMAKE_SYSTEM_NAME=iOS", "-DCMAKE_OSX_SYSROOT=iphonesimulator",
         "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0",
         "-DCMAKE_PREFIX_PATH=" + str(qt), "-DQt5_DIR=" + str(qt / "lib/cmake/Qt5"),
         "-DCMAKE_FIND_ROOT_PATH=" + str(prefix), "-DOPENSSL_ROOT_DIR=" + str(openssl),
         "-DOPENSSL_USE_STATIC_LIBS=TRUE", "-DDUKTO_BUILD_GUI=OFF", "-DDUKTO_BUILD_TESTS=OFF"],
        root, environment, log)
    run(["cmake", "--build", core, "--parallel", "3"], root, environment, log)
    # 日期：2026-11-26；qmake使用SDK变量，-sdk仅适用于configure/xcodebuild。
    run([qt / "bin/qmake", root / "DuktoNextMobile.pro", "QMAKE_MAC_SDK=iphonesimulator",
         "CORE_BUILD=" + str(core), "OPENSSL_PREFIX=" + str(openssl), "CONFIG+=release",
         "QMAKE_APPLE_SIMULATOR_ARCHS=arm64"], app, environment, log)
    projects = list(app.glob("*.xcodeproj"))
    if len(projects) != 1:
        raise ValueError("完整应用Xcode工程数量错误")
    run(["xcodebuild", "-project", projects[0], "-scheme", "DuktoNextMobile", "-configuration", "Release",
         "-sdk", "iphonesimulator", "-destination", "generic/platform=iOS Simulator",
         "-derivedDataPath", build / "DerivedData", "CODE_SIGNING_ALLOWED=NO",
         "CODE_SIGNING_REQUIRED=NO", "CODE_SIGN_IDENTITY=", "build"], app, environment, log)
    apps = list((build / "DerivedData/Build/Products").glob("Release-iphonesimulator/DuktoNextMobile.app"))
    if len(apps) != 1:
        raise ValueError("完整模拟器应用产物数量错误")
    # 日期：2026-11-25；模拟器仅作本地ad-hoc签名，不具备设备安装/App Group发行权限。
    run(["codesign", "--force", "--sign", "-", apps[0]], app, environment, log)
    (build / "application-path.txt").write_text(str(apps[0]) + "\n", "utf-8")


# 日期：2026-11-25；依赖和应用分阶段运行，失败保留原始日志及未通过收据。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["dependencies", "application"], required=True)
    parser.add_argument("--prefix", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise RuntimeError("本验收要求arm64 macOS宿主")
    root = Path(__file__).resolve().parents[1]
    prefix, work = args.prefix.resolve(), args.work.resolve()
    prefix.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.pop("MACOSX_DEPLOYMENT_TARGET", None)
    receipt = {"phase": args.phase, "passed": False, "deviceTest": False}
    try:
        if args.phase == "dependencies":
            dependencies(root, prefix, work, environment)
        else:
            application(root, prefix, work, environment)
        receipt["passed"] = True
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        (work / "phase-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
