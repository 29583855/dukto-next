"""日期：2026-11-25；验收原始arm64 APK安装、首屏与可选R6接收，不代替真机验收。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import socket
import struct
import uuid
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


# 日期：2026-11-25；run-as只访问调试包自身沙箱，所有路径按Android shell规则引用。
def sandbox(*arguments, binary=False):
    return adb("shell", shlex.join(["run-as", "org.duktonext.mobile", *arguments]), binary=binary)


# 日期：2026-11-25；独立构造R6帧发送给完整APK，不调用宿主替身或被测序列化代码。
def send_r6(port, entries):
    total = sum(len(data) for _, data in entries if data is not None)
    header = struct.pack("<qq", len(entries), total)
    with socket.create_connection(("127.0.0.1", port), timeout=15) as client:
        client.settimeout(30)
        for offset in range(0, len(header), 3):
            client.sendall(header[offset:offset + 3])
        for name, data in entries:
            client.sendall(name.encode("utf-8") + b"\0" +
                           struct.pack("<q", -1 if data is None else len(data)))
            if data is not None:
                client.sendall(data)
        # 日期：2026-11-25；保持写端开放，EOF必须来自接收器，避免主动FIN被误判为提交确认。
        if client.recv(1) != b"":
            raise RuntimeError("R6接收端未按协议关闭连接")


# 日期：2026-11-25；最终落盘是独立验收条件，按有界期限等待，绝不重发或放宽内容核对。
def wait_for_file(path, expected):
    deadline = time.monotonic() + 20
    last_error = ""
    while True:
        try:
            actual = sandbox("cat", path, binary=True)
            if actual == expected:
                return actual
            last_error = "内容不一致，实际字节数=" + str(len(actual))
        except RuntimeError as error:
            last_error = str(error)
        if time.monotonic() >= deadline:
            raise RuntimeError("APK文件未按期正确提交: " + path + ": " + last_error)
        time.sleep(0.2)


# 日期：2026-11-25；通过ADB转发验证应用真实接收器及落盘，不能替代Wi-Fi发现或手机互通。
def verify_r6_receive():
    directories = sandbox("find", ".", "-type", "d", "-name", "Documents").splitlines()
    if len(directories) != 1 or not directories[0].startswith("./"):
        raise RuntimeError("无法唯一定位应用文档目录")
    directory = directories[0]
    root = "r6-emulator-" + uuid.uuid4().hex
    payload = ("真实APK接收验证\n".encode("utf-8") * 65537) + bytes(range(256))
    collision_name = root + "-中文 sample.bin"
    entries = [(root, None), (root + "/空目录", None),
               (root + "/中文 sample.bin", payload), (root + "/zero", b""),
               (collision_name, payload)]
    port = int(adb("forward", "tcp:0", "tcp:4644").strip())
    result = {"passed": False, "transport": "ADB TCP forward to production APK R6 port4644",
              "wifiDiscoveryTest": False, "fileSha256": hashlib.sha256(payload).hexdigest(),
              "fileBytes": len(payload)}
    try:
        send_r6(port, entries)
        wait_for_file(directory + "/" + root + "/中文 sample.bin", payload)
        if sandbox("cat", directory + "/" + root + "/zero", binary=True) != b"":
            raise RuntimeError("空文件内容错误")
        if not sandbox("ls", "-ld", directory + "/" + root + "/空目录").startswith("d"):
            raise RuntimeError("空目录未创建")
        # 日期：2026-11-25；再次发送同名文件，必须保留旧内容并生成编号副本。
        replacement = b"collision replacement\n"
        send_r6(port, [(collision_name, replacement)])
        collision = wait_for_file(directory + "/" + root + "-中文 sample (2).bin", replacement)
        original = sandbox("cat", directory + "/" + collision_name, binary=True)
        if collision != replacement or original != payload:
            raise RuntimeError("同名冲突覆盖旧文件或副本内容错误")
        # 日期：2026-11-25；同一进程连续接收32批，每批独立核对落盘，不重发、不重启接收器。
        batch_hashes = [hashlib.sha256(replacement).hexdigest()]
        for batch in range(3, 33):
            replacement = ("collision replacement " + str(batch) + "\n").encode("utf-8")
            send_r6(port, [(collision_name, replacement)])
            wait_for_file(directory + "/" + root + "-中文 sample (" + str(batch) + ").bin", replacement)
            batch_hashes.append(hashlib.sha256(replacement).hexdigest())
        if sandbox("cat", directory + "/" + collision_name, binary=True) != payload:
            raise RuntimeError("连续接收覆盖了最初文件")
        result.update(passed=True, emptyDirectory=True, emptyFile=True, utf8Path=True,
                      originalPreserved=True, collisionCopy=True, sequentialBatches=32,
                      perBatchContentVerified=True, replacementSha256=batch_hashes,
                      sendRetries=0, receiverRestarts=0)
        return result
    finally:
        adb("forward", "--remove", "tcp:" + str(port))


# 日期：2026-11-25；只对指定构建哈希的原始APK测试，禁止用替换ABI或宿主假实现冒充。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--r6-receive", action="store_true")
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
        if args.r6_receive:
            receipt["r6Receive"] = verify_r6_receive()
            receipt["steps"].append("productionApkR6ReceiveAndHash")
        receipt["passed"] = True
        receipt["visualReviewPending"] = True
    except Exception as error:
        receipt["error"] = str(error)
        # 日期：2026-11-25；保留应用错误界面及真实接收账本，区分连接拒绝与落盘失败。
        try:
            (args.output / "failure-screen.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
            (args.output / "failure-receipts.sqlite").write_bytes(
                sandbox("cat", "./files/history/receipts.sqlite", binary=True))
        except Exception as capture_error:
            receipt["receiptCaptureError"] = str(capture_error)
        try:
            (args.output / "failure-sandbox.txt").write_text(
                sandbox("find", ".", "-maxdepth", "5", "-type", "f"), "utf-8")
        except Exception as sandbox_error:
            receipt["sandboxCaptureError"] = str(sandbox_error)
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
