"""日期：2026-11-25；独立编译C++14移动核心并交给Qt部署工具生成开发产物。"""
import argparse
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
from inspect_package import package


# 日期：2026-11-25；命令失败立即返回非零，编译和安装证据分开记录。
def run(command, directory, environment):
    print(json.dumps([str(value) for value in command]), flush=True)
    subprocess.run([str(value) for value in command], cwd=directory, env=environment, check=True)


# 日期：2026-11-25；生成项目私有的现代Gradle模板，交给Qt完整部署以生成资源及属性。
def prepare_android_package(root, qt, build):
    directory = build / "android-package"
    shutil.copytree(root / "platform/android", directory, dirs_exist_ok=True)
    text = (qt / "src/android/templates/build.gradle").read_text("utf-8")
    text, count = re.subn(r"com.android.tools.build:gradle:[0-9.]+", "com.android.tools.build:gradle:8.7.3", text)
    if count != 1 or "android {" not in text or "defaultConfig {" not in text:
        raise ValueError("Qt Gradle模板不匹配，拒绝静默部署")
    # 日期：2026-11-25；正式APK与合同测试统一使用已验通的Central镜像，避免主站HTTP429。
    central = "maven { url 'https://maven-central.storage-download.googleapis.com/maven2' }\n        mavenCentral()"
    text = text.replace("jcenter()", "mavenCentral()")
    text = text.replace("mavenCentral()", central)
    text = text.replace("android {", "android {\n    namespace 'org.duktonext.mobile'\n    buildFeatures.buildConfig true", 1)
    text = text.replace("defaultConfig {", "defaultConfig {\n        applicationId 'org.duktonext.mobile'", 1)
    # 日期：2026-11-25；Qt先解析原清单的包名；Gradle启动时仅去掉部署副本的旧package属性。
    preamble = """// 日期：2026-11-25；AGP8由namespace指定R包，保留Qt部署前的包名解析。
def duktoManifest = file('AndroidManifest.xml')
def duktoManifestText = duktoManifest.getText('UTF-8')
duktoManifest.setText(duktoManifestText.replace(' package="org.duktonext.mobile"', ''), 'UTF-8')
"""
    text = text.replace("apply plugin:", preamble + "\napply plugin:", 1)
    (directory / "build.gradle").write_bytes(text.encode("utf-8"))
    source = qt / "src/3rdparty/gradle/gradle/wrapper/gradle-wrapper.properties"
    text, count = re.subn(r"gradle-[0-9.]+-(bin|all)\.zip", "gradle-8.9-bin.zip", source.read_text("utf-8"))
    if count != 1:
        raise ValueError("Qt Gradle wrapper模板不匹配")
    wrapper = directory / "gradle/wrapper/gradle-wrapper.properties"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_bytes(text.encode("utf-8"))
    return directory


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
    qmake = [qt / "bin/qmake", root / "DuktoNextMobile.pro", "CORE_BUILD=" + str(core),
             "OPENSSL_PREFIX=" + str(prefix / "openssl"), "CONFIG+=release"]
    if args.platform == "android":
        package_source = prepare_android_package(root, qt, build)
        qmake.append("ANDROID_PACKAGE_SOURCE_DIR=" + str(package_source))
    run(qmake, app, environment)
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
        run(["xcodebuild", "-project", projects[0], "-scheme", "DuktoNextMobile", "-configuration", "Release", "-sdk", "iphoneos",
             "-derivedDataPath", build / "DerivedData", "CODE_SIGNING_ALLOWED=NO", "CODE_SIGNING_REQUIRED=NO",
             "CODE_SIGN_IDENTITY=", "build"], app, environment)
        artifacts = list(app.rglob("DuktoNextMobile.app")) + list((build / "DerivedData").rglob("DuktoNextMobile.app"))
        if not artifacts:
            raise ValueError("未生成iOS app")
    if args.platform == "ios":
        extension = build / "share-extension"
        run(["cmake", "-S", root / "platform/ios/share", "-B", extension, "-G", "Xcode",
             "-DCMAKE_SYSTEM_NAME=iOS", "-DCMAKE_OSX_SYSROOT=iphoneos", "-DCMAKE_OSX_ARCHITECTURES=arm64",
             "-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0", "-DCMAKE_XCODE_ATTRIBUTE_CODE_SIGNING_ALLOWED=NO",
             "-DCMAKE_XCODE_ATTRIBUTE_CODE_SIGNING_REQUIRED=NO"], build, environment)
        run(["cmake", "--build", extension, "--config", "Release"], build, environment)
        extensions = list(extension.rglob("DuktoShare.appex"))
        if len(extensions) != 1:
            raise ValueError("iOS分享扩展产物数量错误")
        for application in artifacts:
            shutil.copytree(extensions[0], application / "PlugIns/DuktoShare.appex", dirs_exist_ok=True)
    inspection = package(args.platform, artifacts, build / "packages" / args.platform, environment,
                         require_share_extension=args.platform == "ios")
    package_dir = build / "packages" / args.platform
    shutil.copytree(prefix / "licenses", package_dir / "licenses", dirs_exist_ok=True)
    shutil.copy2(prefix / "dependency-manifest.json", package_dir / "dependency-manifest.json")
    shutil.copy2(root / "LICENSE", package_dir / "LICENSE")
    # 日期：2026-11-25；开发产物随附实际限制、验收状态和签名说明，避免脱离源码目录后误用。
    shutil.copytree(root / "docs", package_dir / "docs", dirs_exist_ok=True)
    receipt = {"packageInspection": inspection, "platform": args.platform, "buildPassed": True, "deviceTestsPassed": False,
               "signedForDistribution": False, "artifacts": [str(path) for path in artifacts]}
    (build / "build-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
