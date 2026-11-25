"""日期：2026-11-25；从校验过的源码构建移动依赖，逐项保留命令、失败日志及工具链版本。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import urllib.request


# 日期：2026-11-25；失败立即停止，完整输出保存到构建目录，禁止伪造通过收据。
def run(command, directory, environment, log):
    command = [str(value) for value in command]
    print(json.dumps(command), flush=True)
    with log.open("ab") as output:
        output.write((json.dumps(command) + "\n").encode())
        output.flush()
        subprocess.run(command, cwd=directory, env=environment, stdout=output,
                       stderr=subprocess.STDOUT, check=True, timeout=10800)


# 日期：2026-11-25；下载固定SHA256源码并使用Python安全解压，不执行研究仓库中的代码。
def extract(source, work):
    archive = work / Path(source["url"]).name
    with urllib.request.urlopen(source["url"], timeout=180) as response, archive.open("wb") as output:
        shutil.copyfileobj(response, output)
    with archive.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != source["sha256"]:
            raise ValueError("依赖摘要错误: " + source["name"])
    destination = work / source["name"]
    destination.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(destination, filter="data")
    children = list(destination.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError("源码归档布局错误")
    return children[0]


# 日期：2026-11-25；依赖许可随构建保存，静态链接iOS的再链接义务另在发行文档列出。
def licenses(source, prefix, name):
    destination = prefix / "licenses" / name
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    # 日期：2026-11-25；递归保存Qt内嵌字体/图片/压缩库等第三方声明及归属元数据，保留来源相对路径。
    for path in sorted(source.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(source)
        upper = path.name.upper()
        if not (upper.startswith(("LICENSE", "LICENCE", "COPYING", "NOTICE")) or
                upper == "QT_ATTRIBUTION.JSON" or "LICENSES" in relative.parts):
            continue
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        entries.append({"path": relative.as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    if not entries:
        raise ValueError("依赖未收集到许可证: " + name)
    (destination / "license-manifest.json").write_bytes(
        (json.dumps({"source": name, "files": entries}, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


# 日期：2026-11-25；Qt5的Android前置特性会清空配置命令的链接参数，必须修补该重置点。
def patch_android_alignment(qtbase):
    feature = qtbase / "mkspecs/features/android/default_pre.prf"
    original = feature.read_bytes()
    patched, count = re.subn(rb"(?m)^QMAKE_LFLAGS[ \t]*=[ \t]*$",
                             b"QMAKE_LFLAGS = -Wl,-z,max-page-size=16384 -Wl,-z,common-page-size=16384",
                             original)
    if count != 1:
        raise ValueError("Qt Android链接参数重置点不匹配，拒绝生成4KiB库")
    feature.write_bytes(patched)
    return {"path": "mkspecs/features/android/default_pre.prf",
            "beforeSha256": hashlib.sha256(original).hexdigest(),
            "afterSha256": hashlib.sha256(patched).hexdigest()}


# 日期：2026-11-25；Qt5保留C++14，移动平台使用同一版本Qt私有头与库；先编译依赖再进入应用门禁。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["android", "ios"], required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=3)
    args = parser.parse_args()
    prefix, work = args.prefix.resolve(), args.work.resolve()
    prefix.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    lock = json.loads(Path(__file__).with_name("dependencies.json").read_text("utf-8"))
    needed = {"openssl", "qtbase", "qtdeclarative", "qtquickcontrols2", "qtgraphicaleffects"}
    sources = {item["name"]: extract(item, work) for item in lock["sources"] if item["name"] in needed}
    qt, openssl = prefix / "qt", prefix / "openssl"
    environment = dict(os.environ)
    environment["OPENSSL_LIBS"] = "-L" + str(openssl / "lib") + " -lssl -lcrypto"
    environment.pop("MACOSX_DEPLOYMENT_TARGET", None)
    options = ["-prefix", str(qt), "-release", "-opensource", "-confirm-license",
               "-nomake", "examples", "-nomake", "tests", "-no-pch", "-no-pkg-config",
               "-no-glib", "-no-icu", "-no-dbus", "-no-zstd", "-qt-zlib", "-qt-pcre",
               "-qt-doubleconversion", "-qt-harfbuzz", "-qt-freetype", "-qt-libpng",
               "-qt-libjpeg", "-qt-sqlite", "-openssl-linked", "-I", str(openssl / "include"),
               "-L", str(openssl / "lib"), "QMAKE_CXXFLAGS+=-Wno-enum-constexpr-conversion"]
    if args.platform == "android":
        sdk = Path(environment["ANDROID_SDK_ROOT"])
        ndk = Path(environment["ANDROID_NDK_ROOT"])
        host = "linux-x86_64" if platform.system() == "Linux" else "darwin-x86_64"
        clang = ndk / "toolchains/llvm/prebuilt" / host / "bin"
        environment["PATH"] = str(clang) + os.pathsep + environment["PATH"]
        environment["ANDROID_NDK_HOME"] = str(ndk)
        configure = ["./Configure", "android-arm64", "no-shared", "no-tests", "-fPIC",
                     "-D__ANDROID_API__=29", "--prefix=" + str(openssl), "--libdir=lib"]
        options += ["-xplatform", "android-clang", "-android-ndk", str(ndk),
                    "-android-sdk", str(sdk), "-android-ndk-platform", "android-29",
                    "-android-abis", "arm64-v8a", "QMAKE_LFLAGS+=-Wl,-z,max-page-size=16384"]
        # 日期：2026-11-25；AndroidExtras仅用于平台桥接，不改变传输核心依赖。
        extra = {"name": "qtandroidextras", "url": "https://download.qt.io/archive/qt/5.15/5.15.19/submodules/qtandroidextras-everywhere-opensource-src-5.15.19.tar.xz"}
        # 日期：2026-11-25；AndroidExtras摘要由依赖锁提供，禁止接受运行时获取的摘要冒充固定值。
        extra = next(item for item in lock["sources"] if item["name"] == "qtandroidextras")
        sources["qtandroidextras"] = extract(extra, work)
    else:
        if platform.system() != "Darwin":
            raise ValueError("iOS必须在macOS宿主构建")
        sdk = subprocess.check_output(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"], text=True).strip()
        configure = ["./Configure", "ios64-xcrun", "no-shared", "no-tests", "-fPIC",
                     "-miphoneos-version-min=15.0", "--prefix=" + str(openssl), "--libdir=lib"]
        options += ["-xplatform", "macx-ios-clang", "-static", "-sdk", "iphoneos",
                    "QMAKE_IOS_DEPLOYMENT_TARGET=15.0", "QMAKE_APPLE_DEVICE_ARCHS=arm64"]
        config = sources["qtbase"] / "mkspecs/common/mac.conf"
        original = config.read_bytes()
        patched = original.replace(b"/System/Library/Frameworks/OpenGL.framework/Headers \\\n    /System/Library/Frameworks/AGL.framework/Headers/", b"/System/Library/Frameworks/OpenGL.framework/Headers")
        patched = patched.replace(b"-framework OpenGL -framework AGL", b"-framework OpenGL")
        config.write_bytes(patched)
    alignment_patch = patch_android_alignment(sources["qtbase"]) if args.platform == "android" else None
    run(configure, sources["openssl"], environment, work / "openssl.log")
    run(["make", "-j" + str(args.jobs)], sources["openssl"], environment, work / "openssl.log")
    run(["make", "install_sw"], sources["openssl"], environment, work / "openssl.log")
    # 日期：2026-11-25；Qt5的Android链接规则固定追加ABI后缀，保留通用库供CMake使用。
    if args.platform == "android":
        for name in ("ssl", "crypto"):
            shutil.copy2(openssl / "lib" / ("lib" + name + ".a"),
                         openssl / "lib" / ("lib" + name + "_arm64-v8a.a"))
    licenses(sources["openssl"], prefix, "openssl")
    build = work / "qtbase-build"
    build.mkdir()
    run([sources["qtbase"] / "configure", *options], build, environment, work / "qtbase.log")
    run(["make", "-j" + str(args.jobs)], build, environment, work / "qtbase.log")
    run(["make", "install"], build, environment, work / "qtbase.log")
    licenses(sources["qtbase"], prefix, "qtbase")
    for name in ["qtdeclarative", "qtquickcontrols2", "qtgraphicaleffects", "qtandroidextras"]:
        if name not in sources:
            continue
        build = work / (name + "-build")
        build.mkdir()
        # 日期：2026-11-25；每个Qt模块独立qmake，不会继承qtbase配置命令的链接参数。
        module_options = ["QMAKE_LFLAGS+=-Wl,-z,max-page-size=16384"] if args.platform == "android" else []
        run([qt / "bin/qmake", sources[name], *module_options], build, environment, work / (name + ".log"))
        run(["make", "-j" + str(args.jobs)], build, environment, work / (name + ".log"))
        run(["make", "install"], build, environment, work / (name + ".log"))
        licenses(sources[name], prefix, name)
    receipt = {"platform": args.platform, "sourceBuild": True, "dependencies": lock,
               "androidAlignmentPatch": alignment_patch,
               "host": platform.platform(), "builderSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
               "deviceTestsPassed": False, "signedForDistribution": False}
    (prefix / "dependency-manifest.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
