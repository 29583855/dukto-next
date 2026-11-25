"""日期：2026-11-25；在真实Android模拟器上验收既有arm64 APK的安装与首屏，不代替真机验收。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from PIL import Image, ImageStat


# 日期：2026-11-25；ADB命令全部设定超时，保存失败输出并拒绝无响应的设备。
def adb(*args, binary=False, timeout=45):
    result = subprocess.run(["adb", *args], capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("ADB命令失败: " + " ".join(args) + ": " +
                           result.stderr.decode("utf-8", "replace") + result.stdout.decode("utf-8", "replace"))
    return result.stdout if binary else result.stdout.decode("utf-8", "replace")


# 日期：2026-11-25；只对指定构建哈希的原始APK测试，禁止用替换ABI或宿主假实现冒充。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256", default="750908dbf8d4b5698b7550966cab251f17a4f81fe932533f12df0e4a03c7c9e6")
    parser.add_argument("--source", default="45647c484f818ad7b16f10b1b3b03d72b7145f30")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = {"passed": False, "deviceTest": False, "scope": "Android模拟器安装启动原始arm64开发APK",
               "sourceCommit": args.source, "steps": []}
    try:
        digest = hashlib.sha256(args.apk.read_bytes()).hexdigest()
        receipt["apkSha256"] = digest
        if digest != args.sha256:
            raise ValueError("APK与已验包构建不匹配")
        receipt["abiList"] = adb("shell", "getprop", "ro.product.cpu.abilist").strip()
        receipt["systemVersion"] = adb("shell", "getprop", "ro.build.version.release").strip()
        receipt["nativeBridge"] = adb("shell", "getprop", "ro.dalvik.vm.native.bridge").strip()
        if "arm64-v8a" not in receipt["abiList"].split(","):
            raise RuntimeError("当前模拟器未声明支持arm64-v8a，不能测试既有APK")
        receipt["steps"].append("originalApkHashAndAbi")
        receipt["installOutput"] = adb("install", "-r", str(args.apk), timeout=150).strip()
        if "Success" not in receipt["installOutput"]:
            raise RuntimeError("APK安装未成功")
        receipt["steps"].append("install")
        receipt["systemDirectoryAliases"] = adb("shell", "ls", "-ld", "/data/user/0", "/data/data").strip()
        adb("logcat", "-c")
        receipt["launchOutput"] = adb("shell", "am", "start", "-W", "-n",
                                      "org.duktonext.mobile/.DuktoActivity")
        if "Status: ok" not in receipt["launchOutput"]:
            raise RuntimeError("Activity启动失败")
        time.sleep(20)
        pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
        receipt["pid"] = pid
        if not pid:
            raise RuntimeError("启动后进程消失")
        activity = adb("shell", "dumpsys", "activity", "activities")
        (args.output / "activity.txt").write_text(activity, "utf-8")
        if not re.search(r"(?:mResumedActivity|topResumedActivity)[^\n]*org\.duktonext\.mobile", activity):
            raise RuntimeError("应用未成为前台Activity")
        log = adb("logcat", "-d", "--pid=" + pid, timeout=60)
        (args.output / "logcat.txt").write_text(log, "utf-8")
        errors = [line for line in log.splitlines() if re.search(
            r"FATAL EXCEPTION|Fatal signal|QQmlApplicationEngine failed|module .+ is not installed|Cannot load library", line)]
        receipt["runtimeErrors"] = errors
        if errors:
            raise RuntimeError("应用原生或QML启动错误")
        screenshot = args.output / "startup.png"
        screenshot.write_bytes(adb("exec-out", "screencap", "-p", binary=True))
        image = Image.open(screenshot).convert("RGB")
        # 日期：2026-11-25；去掉系统状态栏后检测空白帧，并保留原图供人工复核实际内容。
        width, height = image.size
        cropped = image.crop((0, height // 10, width, height * 9 // 10))
        deviations = ImageStat.Stat(cropped.resize((160, 160))).stddev
        receipt["screenshotSize"] = [width, height]
        receipt["frameStddev"] = deviations
        if max(deviations) < 8:
            raise RuntimeError("前台图像接近空白，拒绝视为界面启动通过")
        receipt["steps"].append("foregroundAliveAndNonBlankFrame")
        receipt["passed"] = True
        receipt["visualReviewPending"] = True
    except Exception as error:
        receipt["error"] = str(error)
        try:
            (args.output / "failure-logcat.txt").write_text(adb("logcat", "-d", timeout=30), "utf-8")
        except Exception as log_error:
            receipt["logCaptureError"] = str(log_error)
        raise
    finally:
        (args.output / "android-startup.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
