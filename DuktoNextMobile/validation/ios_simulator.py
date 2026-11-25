"""日期：2026-11-25；在独立iPhone模拟器安装完整Qt应用，核对首屏和真实连续接收落盘。"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import subprocess
import time
import uuid
from PIL import Image, ImageStat
from android_emulator import send_r6
from ios_send import verify_text_send


# 日期：2026-11-25；Xcode调用有界超时，失败输出直接写入CI日志，不接受静默成功。
def run(*command, timeout=120):
    result = subprocess.run([str(value) for value in command], text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError("命令失败: " + " ".join(map(str, command)) + "\n" + result.stdout + result.stderr)
    return result.stdout.strip()


# 日期：2026-11-25；逐批等待实际文件提交，超时或内容不符失败，禁止重发掩盖交接缺陷。
def wait_file(path, expected):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if path.is_file() and path.read_bytes() == expected:
            return
        time.sleep(0.1)
    raise RuntimeError("完整iOS应用未正确提交文件: " + str(path))


# 日期：2026-11-25；独立线协议发送到完整Qt接收器，覆盖中文、空文件、空目录和32批重名保留。
def receive_batches(documents):
    name = "r6-simulator-" + uuid.uuid4().hex
    payload = "完整iOS应用接收验证\n".encode("utf-8") * 65537 + bytes(range(256))
    collision = name + "-中文 sample.bin"
    send_r6(4644, [(name, None), (name + "/空目录", None), (name + "/中文 sample.bin", payload),
                   (name + "/zero", b""), (collision, payload)])
    wait_file(documents / name / "中文 sample.bin", payload)
    wait_file(documents / name / "zero", b"")
    if not (documents / name / "空目录").is_dir():
        raise RuntimeError("完整iOS应用未创建空目录")
    hashes = []
    for batch in range(2, 33):
        replacement = ("连续接收批次 " + str(batch) + "\n").encode("utf-8")
        send_r6(4644, [(collision, replacement)])
        wait_file(documents / (name + "-中文 sample (" + str(batch) + ").bin"), replacement)
        hashes.append(hashlib.sha256(replacement).hexdigest())
    wait_file(documents / collision, payload)
    return {"passed": True, "sequentialBatches": 32, "emptyFile": True, "emptyDirectory": True,
            "utf8Path": True, "originalPreserved": True, "collisionCopy": True,
            "fileSha256": hashlib.sha256(payload).hexdigest(), "fileBytes": len(payload),
            "perBatchContentVerified": True, "replacementSha256": hashes,
            "sendRetries": 0, "receiverRestarts": 0, "wifiDiscoveryTest": False,
            "transport": "macOS host TCP4644 to installed complete iOS simulator app"}


# 日期：2026-11-25；完整应用验收与UIKit替身测试分开，失败截图日志和收据始终保留。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    args = parser.parse_args()
    build = args.build.resolve()
    application = Path((build / "application-path.txt").read_text("utf-8").strip())
    info = plistlib.loads((application / "Info.plist").read_bytes())
    binary = application / info["CFBundleExecutable"]
    receipt = {"passed": False, "deviceTest": False, "completeQtApp": True,
               "shareExtensionTest": False, "signedForDistribution": False,
               "sourceCommit": run("git", "rev-parse", "HEAD"),
               "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "steps": []}
    device, logger, log_file = None, None, None
    try:
        runtime_list = json.loads(run("xcrun", "simctl", "list", "runtimes", "-j"))["runtimes"]
        runtimes = [item for item in runtime_list if item.get("isAvailable") and ".iOS-" in item["identifier"]]
        if not runtimes:
            raise RuntimeError("没有可用iOS模拟器运行时")
        runtime = max(runtimes, key=lambda item: tuple(map(int, item["version"].split("."))))
        types = json.loads(run("xcrun", "simctl", "list", "devicetypes", "-j"))["devicetypes"]
        phone = next(item for item in types if item["name"] == "iPhone 16")
        receipt["runtime"] = runtime
        device = run("xcrun", "simctl", "create", "DuktoCompleteApp", phone["identifier"], runtime["identifier"])
        run("xcrun", "simctl", "boot", device)
        run("xcrun", "simctl", "bootstatus", device, "-b", timeout=180)
        run("xcrun", "simctl", "install", device, application)
        receipt["steps"].append("installCompleteProductionSourceApp")
        log_file = (build / "runtime.log").open("wb")
        logger = subprocess.Popen(["xcrun", "simctl", "spawn", device, "log", "stream", "--level", "debug",
                                   "--style", "compact", "--predicate", 'process == "DuktoNextMobile"'],
                                  stdout=log_file, stderr=subprocess.STDOUT)
        time.sleep(1)
        launch = run("xcrun", "simctl", "launch", device, info["CFBundleIdentifier"])
        (build / "launch.txt").write_text(launch + "\n", "utf-8")
        pid = int(launch.rsplit(":", 1)[1].strip())
        receipt["pid"] = pid
        time.sleep(20)
        run("kill", "-0", str(pid))
        log_file.flush()
        log = (build / "runtime.log").read_text("utf-8", errors="replace")
        for marker in ["MobileStartup qml-ready", "MobileStartup event-loop-start"]:
            if marker not in log:
                raise RuntimeError("缺少完整Qt启动证据: " + marker)
        receipt["steps"].append("qmlAndEventLoopAlive20Seconds")
        run("xcrun", "simctl", "io", device, "screenshot", build / "startup.png")
        image = Image.open(build / "startup.png").convert("RGB")
        width, height = image.size
        deviations = ImageStat.Stat(image.crop((0, height // 10, width, height * 9 // 10)).resize((160, 160))).stddev
        receipt["frameStddev"] = deviations
        receipt["screenshotSize"] = [width, height]
        if max(deviations) < 8:
            raise RuntimeError("完整Qt应用首屏接近空白")
        receipt["steps"].append("nonBlankFrame")
        container = Path(run("xcrun", "simctl", "get_app_container", device, info["CFBundleIdentifier"], "data"))
        receipt["r6Receive"] = receive_batches(container / "Documents")
        receipt["steps"].append("productionReceiver32BatchesAndDiskHash")
        run("kill", "-0", str(pid))
        run("xcrun", "simctl", "io", device, "screenshot", build / "after-receive.png")
        receipt["r6UiTextSend"] = verify_text_send(device, build)
        receipt["steps"].append("productionUiTextSendAndIndependentWireHash")
        run("kill", "-0", str(pid))
        receipt["passed"] = True
        receipt["visualReviewPending"] = True
    except Exception as error:
        receipt["error"] = str(error)
        if device:
            try:
                run("xcrun", "simctl", "io", device, "screenshot", build / "failure.png")
            except Exception as capture_error:
                receipt["captureError"] = str(capture_error)
        raise
    finally:
        if logger:
            logger.terminate()
            try:
                logger.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.kill()
                logger.wait(timeout=10)
        if log_file:
            log_file.close()
        if device:
            try:
                run("xcrun", "simctl", "shutdown", device)
                run("xcrun", "simctl", "delete", device)
            except Exception as cleanup_error:
                receipt["cleanupError"] = str(cleanup_error)
        (build / "ios-complete-app.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
        print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
