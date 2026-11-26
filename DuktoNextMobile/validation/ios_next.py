"""日期：2026-11-26；完整iOS Qt应用经真实Next界面操作，独立服务端核对认证与文件内容。"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import selectors
import shutil
import socket
import subprocess
import tempfile
import time

from PIL import Image, ImageStat

from android_emulator import send_r6
from android_next import service_command
from ios_send import command
from ios_storage import wait_entries
from ios_simulator import run


# 日期：2026-11-26；使用公开证书摘要生成测试源码，配对令牌不进入源码、日志或最终附件。
def verify_next(device, build, documents, probe, original_pid):
    report = {"passed": False, "deviceTest": False, "wifiDiscoveryTest": False,
              "realUiActions": True, "systemDocumentPicker": True,
              "transport": "iOS simulator TCP to independent macOS Next TLS service",
              "processRestarts": 0, "sendRetries": 0, "checks": []}
    log = build / "ios-next-ui.log"
    process = None
    pairing_file = documents / "a-next-pairing.json"
    try:
        with tempfile.TemporaryDirectory(prefix="dukto-ios-next-") as temporary:
            root = Path(temporary).resolve()
            state, shared = root / "state", root / "shared"
            bundle = shared / "bundle"
            (bundle / "空目录").mkdir(parents=True)
            payload = "iOS Next客户端下载校验\n".encode("utf-8") + bytes(range(256)) * 257
            upload = "iOS Next目录上传校验\n".encode("utf-8") + bytes(range(256)) * 259
            (bundle / "中文 sample.bin").write_bytes(payload)
            (bundle / "empty.bin").write_bytes(b"")
            # 日期：2026-11-26；上传目标预置同名目录，保留双方须创建编号目录并保留原内容。
            (bundle / "a-next-upload").mkdir()
            (bundle / "a-next-upload" / "keep-original.bin").write_bytes(b"preserve-server-original")
            identity = service_command(probe, state, ["serve", "init", "--server-name", "127.0.0.1"])
            permissions = ["--allow-browse", "--allow-download", "--allow-upload"]
            service_command(probe, state, ["serve", "share", "add", "--share", "docs",
                                           "--path", str(shared), *permissions])
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = str(reservation.getsockname()[1])
            process = subprocess.Popen([str(probe), "serve", "start", "--bind", "127.0.0.1",
                                        "--port", port, "--state-directory", str(state), "--json"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=15):
                    raise RuntimeError("独立macOS Next服务未按期启动")
                listening = json.loads(process.stdout.readline())
            if listening.get("event") != "service-listening" or not listening.get("port"):
                raise RuntimeError("独立服务启动事件错误")
            source = Path(__file__).resolve().parent / "ios-ui"
            swift = (source / "NextServerTests.swift").read_text("utf-8")
            fingerprint = identity["fingerprint"]
            if len(fingerprint) != 64 or any(c not in "0123456789abcdefABCDEF" for c in fingerprint):
                raise RuntimeError("服务指纹不是64位十六进制")
            swift = swift.replace("__NEXT_TARGET__", "127.0.0.1:" + str(listening["port"]))
            swift = swift.replace("__NEXT_FINGERPRINT__", fingerprint)
            generated = build / "next-ui" / "NextServerTests.swift"
            generated.parent.mkdir()
            generated.write_text(swift, "utf-8")
            project = build / "next-ui" / "MobileSendTests.xcodeproj"
            command(log, "ruby", source / "create_project.rb", project, generated)
            arguments = ["xcodebuild", "-project", project, "-scheme", "MobileSendTests",
                         "-configuration", "Debug", "-destination", "platform=iOS Simulator,id=" + device,
                         "-derivedDataPath", build / "next-ui-derived", "CODE_SIGNING_ALLOWED=NO",
                         "CODE_SIGNING_REQUIRED=NO", "-parallel-testing-enabled", "NO"]
            command(log, *arguments, "build-for-testing", timeout=360)
            # 日期：2026-11-26；测试宿主编译完成才颁发短时凭据，避免工具链耗时消耗配对有效期。
            offer = service_command(probe, state, ["serve", "pairing", "--share", "docs", *permissions])
            credential = Path(offer["credentialFile"])
            fixtures = [("a-next-pairing.json", credential.read_bytes()), ("a-next-upload", None),
                        ("a-next-upload/中文 sample.bin", upload), ("a-next-upload/empty.bin", b""),
                        ("a-next-upload/空目录", None)]
            send_r6(4644, fixtures)
            wait_entries(documents, fixtures)
            # 日期：2026-11-26；系统选择器读到的JSON来自实际R6接收，宿主只核对，不补写应用内容。
            for operation, test in [("pair", "testNextPairAndBrowse"),
                                    ("download", "testNextDownload"),
                                    ("upload", "testNextUploadDirectory")]:
                command(log, *arguments, "-only-testing:MobileSendTests/MobileSendTests/" + test,
                        "-resultBundlePath", build / ("ios-next-" + operation + ".xcresult"),
                        "test-without-building", timeout=600)
                subprocess.run(["kill", "-0", str(original_pid)], check=True, timeout=10)
                if operation == "pair":
                    clients = service_command(probe, state, ["serve", "clients"])
                    if len(clients["entries"]) != 1 or clients["entries"][0].get("revoked"):
                        raise RuntimeError("独立服务未登记唯一有效iOS客户端")
                    pairing_file.unlink()
                    report["checks"].extend(["uiPairWithPinnedFingerprint", "uiAuthenticatedBrowse"])
                elif operation == "download":
                    report["download"] = wait_entries(documents, [
                        ("bundle", None), ("bundle/中文 sample.bin", payload), ("bundle/empty.bin", b""),
                        ("bundle/空目录", None), ("bundle/a-next-upload", None),
                        ("bundle/a-next-upload/keep-original.bin", b"preserve-server-original")], "bundle")
                    report["checks"].append("uiDownloadAndIndependentSandboxReadBack")
                else:
                    expected = [("a-next-upload (2)", None), ("a-next-upload (2)/中文 sample.bin", upload),
                                ("a-next-upload (2)/empty.bin", b""), ("a-next-upload (2)/空目录", None)]
                    report["upload"] = wait_entries(bundle, expected, "a-next-upload (2)")
                    if (bundle / "a-next-upload/keep-original.bin").read_bytes() != b"preserve-server-original":
                        raise RuntimeError("上传覆盖服务端既有目录")
                    wait_entries(documents, fixtures[1:], "a-next-upload")
                    report["checks"].extend(["uiFilesDirectoryUploadAndIndependentServerReadBack",
                                             "keepBothPreservesOriginal", "uploadSourcePreserved"])
            report["passed"] = True
            report["visualReviewPending"] = True
            return report
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        if pairing_file.exists():
            pairing_file.unlink()
        if process is not None:
            process.terminate()
            out, err = process.communicate(timeout=10)
            (build / "ios-next-service-events.jsonl").write_text(out, "utf-8")
            (build / "ios-next-service-stderr.txt").write_text(err, "utf-8")
        (build / "ios-next.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")


# 日期：2026-11-26；在独立模拟器安装生产源码应用，只运行Next新增流程并保留原始失败现场。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--runtime-major", type=int)
    args = parser.parse_args()
    build, probe = args.build.resolve(), args.probe.resolve()
    application = Path((build / "application-path.txt").read_text("utf-8").strip())
    info = plistlib.loads((application / "Info.plist").read_bytes())
    binary = application / info["CFBundleExecutable"]
    receipt = {"passed": False, "deviceTest": False, "completeQtApp": True,
               "shareExtensionTest": False, "signedForDistribution": False,
               "sourceCommit": run("git", "rev-parse", "HEAD"),
               "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "steps": []}
    device, logger, log_file = None, None, None
    try:
        sdk_version = run("xcrun", "--sdk", "iphonesimulator", "--show-sdk-version")
        runtime_major = args.runtime_major or int(sdk_version.split(".")[0])
        receipt.update(sdkVersion=sdk_version, requestedRuntimeMajor=runtime_major)
        runtime_list = json.loads(run("xcrun", "simctl", "list", "runtimes", "-j", timeout=300))["runtimes"]
        runtimes = [item for item in runtime_list if item.get("isAvailable") and ".iOS-" in item["identifier"]
                    and int(item["version"].split(".")[0]) == runtime_major]
        if not runtimes:
            raise RuntimeError("没有要求代际的iOS模拟器运行时: " + str(runtime_major))
        runtime = max(runtimes, key=lambda item: tuple(map(int, item["version"].split("."))))
        types = json.loads(run("xcrun", "simctl", "list", "devicetypes", "-j"))["devicetypes"]
        phones = [item for item in types if item["name"] == "iPhone 16"]
        if len(phones) != 1:
            raise RuntimeError("没有唯一iPhone16设备类型")
        device = run("xcrun", "simctl", "create", "DuktoNextServerUI", phones[0]["identifier"], runtime["identifier"])
        receipt.update(device=device, runtime=runtime["name"])
        run("xcrun", "simctl", "boot", device)
        run("xcrun", "simctl", "bootstatus", device, "-b", timeout=240)
        run("xcrun", "simctl", "install", device, application, timeout=240)
        receipt["steps"].append("installCompleteProductionSourceApp")
        log_file = (build / "ios-next-runtime.log").open("wb")
        logger = subprocess.Popen(["xcrun", "simctl", "spawn", device, "log", "stream", "--level", "debug",
                                   "--style", "compact", "--predicate", 'process == "DuktoNextMobile"'],
                                  stdout=log_file, stderr=subprocess.STDOUT)
        time.sleep(1)
        launch = run("xcrun", "simctl", "launch", device, info["CFBundleIdentifier"], timeout=180)
        (build / "ios-next-launch.txt").write_text(launch + "\n", "utf-8")
        pid = int(launch.rsplit(":", 1)[1].strip())
        receipt["pid"] = pid
        time.sleep(20)
        run("kill", "-0", pid)
        log_file.flush()
        log = (build / "ios-next-runtime.log").read_text("utf-8", errors="replace")
        for marker in ["MobileStartup qml-ready", "MobileStartup event-loop-start"]:
            if marker not in log:
                raise RuntimeError("缺少完整Qt启动证据: " + marker)
        run("xcrun", "simctl", "io", device, "screenshot", build / "ios-next-startup.png")
        image = Image.open(build / "ios-next-startup.png").convert("RGB")
        width, height = image.size
        deviations = ImageStat.Stat(image.crop((0, height // 10, width, height * 9 // 10)).resize((160, 160))).stddev
        receipt.update(frameStddev=deviations, screenshotSize=[width, height])
        if max(deviations) < 8:
            raise RuntimeError("完整Qt应用首屏接近空白")
        receipt["steps"].append("qmlEventLoopAliveAndNonBlankFrame")
        container = Path(run("xcrun", "simctl", "get_app_container", device, info["CFBundleIdentifier"], "data"))
        receipt["nextServer"] = verify_next(device, build, container / "Documents", probe, pid)
        receipt["steps"].append("productionUiNextPairBrowseDownloadDirectoryUploadAndReadBack")
        run("kill", "-0", pid)
        run("xcrun", "simctl", "io", device, "screenshot", build / "ios-next-final.png")
        receipt.update(passed=True, visualReviewPending=True)
    except Exception as error:
        receipt["error"] = str(error)
        if device:
            probes = [("system.log", ["xcrun", "simctl", "spawn", device, "log", "show", "--last", "5m",
                                     "--style", "compact", "--predicate",
                                     'process == "SpringBoard" OR process == "runningboardd" OR process == "DuktoNextMobile"']),
                      ("failure.png", ["xcrun", "simctl", "io", device, "screenshot", build / "ios-next-failure.png"])]
            for name, arguments in probes:
                try:
                    output = run(*arguments, timeout=30)
                    (build / ("ios-next-" + name + ".txt")).write_text(output + "\n", "utf-8")
                except Exception as diagnostic_error:
                    receipt[name + "Error"] = str(diagnostic_error)
            reports = Path.home() / "Library/Logs/DiagnosticReports"
            for crash in reports.glob("DuktoNextMobile*"):
                if crash.is_file():
                    shutil.copy2(crash, build / ("crash-" + crash.name))
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
            for action in ("shutdown", "delete"):
                try:
                    run("xcrun", "simctl", action, device, timeout=30)
                except Exception as cleanup_error:
                    receipt[action + "Error"] = str(cleanup_error)
        (build / "ios-next-complete-app.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")


if __name__ == "__main__":
    main()
