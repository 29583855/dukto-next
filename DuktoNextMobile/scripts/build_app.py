"""日期：2026-11-25；独立编译C++14移动核心并交给Qt部署工具生成开发产物。"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


# 日期：2026-11-25；命令失败立即返回非零，编译和安装证据分开记录。
def run(command, directory, environment):
    print(json.dumps([str(value) for value in command]), flush=True)
    subprocess.run([str(value) for value in command], cwd=directory, env=environment, check=True)


# 日期：2026-11-25；Android生成测试APK，iOS只生成未签名设备app，不能作为安装通过证据。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["android", "ios"], required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    prefix, build = args.prefix.resolve(), args.build.resolve()
    build.mkdir(parents=True, exist_ok=True)
    core, app = build / "core", build / "app"
    app.mkdir(exist_ok=True)
    environment = dict(os.environ)
    qt = prefix / "qt"
    # 日期：2026-11-25；交叉工具链默认只搜索目标根，显式指定已安装Qt配置及依赖根。
    command = ["cmake", "-S", root, "-B", core, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=Release",
               "-DCMAKE_PREFIX_PATH=" + str(qt), "-DQt5_DIR=" + str(qt / "lib/cmake/Qt5"),
               "-DCMAKE_FIND_ROOT_PATH=" + str(prefix),
               "-DOPENSSL_ROOT_DIR=" + str(prefix / "openssl"),
               "-DOPENSSL_USE_STATIC_LIBS=TRUE", "-DDUKTO_BUILD_GUI=OFF", "-DDUKTO_BUILD_TESTS=OFF"]
    if args.platform == "android":
        ndk = Path(environment["ANDROID_NDK_ROOT"])
        command += ["-DCMAKE_TOOLCHAIN_FILE=" + str(ndk / "build/cmake/android.toolchain.cmake"),
                    "-DANDROID_SDK_ROOT=" + environment["ANDROID_SDK_ROOT"],
                    "-DANDROID_SDK_BUILD_TOOLS_REVISION=35.0.0",
                    "-DANDROID_ABI=arm64-v8a", "-DANDROID_PLATFORM=android-29", "-DANDROID_STL=c++_shared"]
    else:
        command += ["-DCMAKE_SYSTEM_NAME=iOS", "-DCMAKE_OSX_SYSROOT=iphoneos",
                    "-DCMAKE_OSX_ARCHITECTURES=arm64", "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0"]
    run(command, root, environment)
    run(["cmake", "--build", core, "--parallel", "3"], root, environment)
    run([qt / "bin/qmake", root / "DuktoNextMobile.pro", "CORE_BUILD=" + str(core),
         "OPENSSL_PREFIX=" + str(prefix / "openssl"), "CONFIG+=release"], app, environment)
    if args.platform == "android":
        run(["make", "-j3"], app, environment)
        # 日期：2026-11-25；先执行qmake安装目标，将应用so放入部署目录的libs/ABI。
        run(["make", "INSTALL_ROOT=" + str(app / "android-build"), "install"], app, environment)
        settings = list(app.glob("android-*-deployment-settings.json"))
        if len(settings) != 1:
            raise ValueError("Android部署设置数量错误")
        run([qt / "bin/androiddeployqt", "--input", settings[0], "--output", app / "android-build",
             "--android-platform", "android-35", "--jdk", environment["JAVA_HOME"], "--gradle"], app, environment)
        artifacts = list((app / "android-build/build/outputs/apk").rglob("*.apk"))
        if not artifacts:
            raise ValueError("未生成APK")
    else:
        projects = list(app.glob("*.xcodeproj"))
        if len(projects) != 1:
            raise ValueError("iOS Xcode工程数量错误")
        run(["xcodebuild", "-project", projects[0], "-configuration", "Release", "-sdk", "iphoneos",
             "-derivedDataPath", build / "DerivedData", "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO",
             "CODE_SIGN_IDENTITY=", "build"], app, environment)
        artifacts = list(app.rglob("DuktoNextMobile.app")) + list((build / "DerivedData").rglob("DuktoNextMobile.app"))
        if not artifacts:
            raise ValueError("未生成iOS app")
    receipt = {"platform": args.platform, "buildPassed": True, "deviceTestsPassed": False,
               "signedForDistribution": False, "artifacts": [str(path) for path in artifacts]}
    (build / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
