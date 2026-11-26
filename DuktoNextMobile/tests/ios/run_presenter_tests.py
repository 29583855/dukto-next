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
    # 日期：2026-11-26；运行时查询也纳入失败收据；冷启动一次最多300秒，不重试或重启服务。
    device = None
    runner = {"passed": False, "deviceTest": False, "requestedRuntimeMajor": args.runtime_major,
              "stage": "compile-and-query-runtime", "runtimeQueryTimeoutSeconds": 300}
    try:
        sdk = run("xcrun", "--sdk", "iphonesimulator", "--show-sdk-path")
        print(run("xcrun", "--sdk", "iphonesimulator", "clang++", "-std=c++14", "-fobjc-arc", "-isysroot", sdk,
                  "-target", "arm64-apple-ios15.0-simulator", "-framework", "UIKit", "-framework", "Foundation",
                  "-I" + str(root / "platform/ios"), str(root / "platform/ios/presenter.mm"),
                  str(root / "tests/ios/presenter_tests.mm"), "-o", str(app / "PresenterTests")))
        print(run("codesign", "--force", "--sign", "-", str(app)))
        runtimes = json.loads(run("xcrun", "simctl", "list", "runtimes", "-j", timeout=300))["runtimes"]
        candidates = [r for r in runtimes if r.get("isAvailable") and "iOS" in r["identifier"] and int(r["version"].split(".")[0]) == args.runtime_major]
        if not candidates:
            raise RuntimeError("没有要求的iOS模拟器运行时")
        runner["stage"] = "select-device"
        runtime = max(candidates, key=lambda r: tuple(int(n) for n in r["version"].split(".")))
        runner["runtime"] = runtime
        types = json.loads(run("xcrun", "simctl", "list", "devicetypes", "-j"))["devicetypes"]
        phones = [t for t in types if t["name"] == "iPhone 16"]
        if not phones:
            raise RuntimeError("没有iPhone16模拟设备类型")
        print("Selected runtime:", runtime["name"], flush=True)
        device = run("xcrun", "simctl", "create", "DuktoPresenterTests", phones[0]["identifier"], runtime["identifier"])
        runner.update(device=device, stage="boot")
        run("xcrun", "simctl", "boot", device)
        print(run("xcrun", "simctl", "bootstatus", device, "-b", timeout=180))
        # 日期：2026-11-26；新运行时首次安装服务启动较慢，单次有界等待，不重跑掩盖失败。
        print(run("xcrun", "simctl", "install", device, str(app), timeout=240))
        print(run("xcrun", "simctl", "launch", device, info["CFBundleIdentifier"], timeout=180))
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
        runner["passed"] = True
    except Exception as error:
        runner["error"] = str(error)
        # 日期：2026-11-26；启动超时时先收集原生收据和系统日志，不能在删除模拟器后丢失原因。
        probes = [
            ("container", ("xcrun", "simctl", "get_app_container", device, info["CFBundleIdentifier"], "data")),
            ("system-log", ("xcrun", "simctl", "spawn", device, "log", "show", "--last", "5m",
                            "--style", "compact", "--predicate",
                            'process == "PresenterTests" OR eventMessage CONTAINS "org.duktonext.presenter.tests"')),
            ("screen", ("xcrun", "simctl", "io", device, "screenshot", str(build / "failure.png")))
        ]
        if not device:
            probes = [("simulator-processes", ("pgrep", "-lf", "CoreSimulator"))]
        for name, arguments in probes:
            try:
                output = run(*arguments, timeout=30)
                (build / (name + ".txt")).write_text(output + "\n", "utf-8")
                if name == "container":
                    native = Path(output) / "Documents/presenter-test.json"
                    if native.is_file():
                        shutil.copy2(native, build / "presenter-native-after-failure.json")
            except Exception as diagnostic_error:
                runner[name + "Error"] = str(diagnostic_error)
        raise
    finally:
        (build / "presenter-runner.json").write_text(
            json.dumps(runner, ensure_ascii=False, indent=2) + "\n", "utf-8")
        for action in (("shutdown", "delete") if device else ()):
            try:
                run("xcrun", "simctl", action, device, timeout=30)
            except Exception as cleanup_error:
                print("模拟器清理失败：", cleanup_error, flush=True)


if __name__ == "__main__":
    main()
