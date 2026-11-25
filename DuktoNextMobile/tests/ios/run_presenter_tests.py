"""日期：2026-11-25；创建独立iOS模拟器运行真实UIKit窗口回归，失败保留输出。"""
import argparse
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import time


# 日期：2026-11-25；所有Xcode调用限制时长，失败直接使门禁失败。
def run(*command, timeout=120):
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.STDOUT, timeout=timeout).strip()
    except subprocess.CalledProcessError as error:
        print(error.output, flush=True)
        raise


# 日期：2026-11-25；测试应用仅有UIKit窗口，不依赖Qt模拟器库或Apple签名材料。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-major", required=True, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    build = root / "build-presenter"
    app = build / "PresenterTests.app"
    app.mkdir(parents=True, exist_ok=True)
    info = {"CFBundleIdentifier": "org.duktonext.presenter.tests", "CFBundleExecutable": "PresenterTests",
            "CFBundleName": "PresenterTests", "CFBundlePackageType": "APPL", "CFBundleVersion": "1",
            "CFBundleShortVersionString": "1.0", "MinimumOSVersion": "15.0", "LSRequiresIPhoneOS": True,
            "UIDeviceFamily": [1, 2], "UILaunchScreen": {}}
    (app / "Info.plist").write_bytes(plistlib.dumps(info))
    sdk = run("xcrun", "--sdk", "iphonesimulator", "--show-sdk-path")
    print(run("xcrun", "--sdk", "iphonesimulator", "clang++", "-std=c++14", "-fobjc-arc", "-isysroot", sdk,
              "-target", "arm64-apple-ios15.0-simulator", "-framework", "UIKit", "-framework", "Foundation",
              "-I" + str(root / "platform/ios"), str(root / "platform/ios/presenter.mm"),
              str(root / "tests/ios/presenter_tests.mm"), "-o", str(app / "PresenterTests")))
    print(run("codesign", "--force", "--sign", "-", str(app)))
    runtimes = json.loads(run("xcrun", "simctl", "list", "runtimes", "-j"))["runtimes"]
    candidates = [r for r in runtimes if r.get("isAvailable") and "iOS" in r["identifier"] and int(r["version"].split(".")[0]) == args.runtime_major]
    if not candidates:
        raise RuntimeError("没有要求的iOS模拟器运行时")
    runtime = max(candidates, key=lambda r: tuple(int(n) for n in r["version"].split(".")))
    types = json.loads(run("xcrun", "simctl", "list", "devicetypes", "-j"))["devicetypes"]
    phones = [t for t in types if t["name"] == "iPhone 16"]
    if not phones:
        raise RuntimeError("没有iPhone16模拟设备类型")
    print("Selected runtime:", runtime["name"], flush=True)
    device = run("xcrun", "simctl", "create", "DuktoPresenterTests", phones[0]["identifier"], runtime["identifier"])
    try:
        run("xcrun", "simctl", "boot", device)
        print(run("xcrun", "simctl", "bootstatus", device, "-b", timeout=180))
        print(run("xcrun", "simctl", "install", device, str(app)))
        print(run("xcrun", "simctl", "launch", device, info["CFBundleIdentifier"]))
        container = Path(run("xcrun", "simctl", "get_app_container", device, info["CFBundleIdentifier"], "data"))
        receipt = container / "Documents/presenter-test.json"
        deadline = time.monotonic() + 45
        while not receipt.exists() and time.monotonic() < deadline:
            time.sleep(0.5)
        if not receipt.exists():
            raise RuntimeError("UIKit模拟器未产生实际测试收据")
        shutil.copy2(receipt, build / "presenter-test.json")
        result = json.loads(receipt.read_text("utf-8"))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result.get("passed") is not True:
            raise RuntimeError("UIKit传统窗口回归失败")
    finally:
        run("xcrun", "simctl", "shutdown", device)
        run("xcrun", "simctl", "delete", device)


if __name__ == "__main__":
    main()
