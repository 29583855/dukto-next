"""日期：2026-11-26；XCTest操作原始Qt应用，以独立R6接收器核对真实文字发送。"""
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from android_send import receive_files, receive_text
from android_emulator import send_r6

TEXT = b"Dukto iOS production UI send / ASCII 20261126"


# 日期：2026-11-26；独立系统UI测试工程先编译，避免构建耗时被误认为产品网络超时。
def command(log, *arguments, timeout=180):
    result = subprocess.run([str(value) for value in arguments], text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    with log.open("a", encoding="utf-8") as output:
        output.write(result.stdout)
    if result.returncode:
        raise RuntimeError("iOS系统UI验收命令失败: " + " ".join(map(str, arguments)) +
                           "\n" + result.stdout[-6000:])


# 日期：2026-11-26；只监听本机独立端口，逐字节验证正文和EOF，禁止测试代码代替产品发包。
def receive_one(listener, cancelled):
    deadline = time.monotonic() + 360
    while not cancelled.is_set() and time.monotonic() < deadline:
        try:
            connection, _ = listener.accept()
        except socket.timeout:
            continue
        with connection:
            connection.settimeout(30)
            return receive_text(connection, TEXT)
    raise RuntimeError("iOS真实UI未在期限内连接独立接收器")


# 日期：2026-11-26；只有真实UI测试和独立接收器同时成功才写通过收据。
def verify_text_send(device, build):
    source = Path(__file__).resolve().parent / "ios-ui"
    project = build / "ui" / "MobileSendTests.xcodeproj"
    log = build / "ios-ui.log"
    report = {"passed": False, "deviceTest": False, "realUiActions": True,
              "systemShareTest": False, "fileSendTest": False, "wifiDiscoveryTest": False}
    try:
        command(log, "ruby", source / "create_project.rb", project, source / "MobileSendTests.swift")
        arguments = ["xcodebuild", "-project", project, "-scheme", "MobileSendTests",
                     "-configuration", "Debug", "-destination", "platform=iOS Simulator,id=" + device,
                     "-derivedDataPath", build / "ui-derived", "CODE_SIGNING_ALLOWED=NO",
                     "CODE_SIGNING_REQUIRED=NO", "-parallel-testing-enabled", "NO"]
        command(log, *arguments, "build-for-testing", timeout=360)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 49231))
            listener.listen(1)
            listener.settimeout(0.25)
            cancelled = threading.Event()
            with ThreadPoolExecutor(max_workers=1) as executor:
                received = executor.submit(receive_one, listener, cancelled)
                try:
                    command(log, *arguments, "-resultBundlePath", build / "ios-ui.xcresult",
                            "-only-testing:MobileSendTests/MobileSendTests/testSendTextFromProductionUI",
                            "test-without-building", timeout=480)
                    report.update(received.result(timeout=35))
                finally:
                    cancelled.set()
        report.update(passed=True, transport="iOS simulator production Qt UI to independent host R6 receiver",
                      sendRetries=0, processRestarts=0)
        return report
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (build / "ios-ui-send.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")


# 日期：2026-11-26；系统文件选择与取消重开必须实际发送接收样本，严格核对正文、条目及EOF。
def verify_file_send(device, build, documents):
    sample_name = "a-ios-document-probe.bin"
    payload = "iOS系统文档选择器真实文件\n".encode("utf-8") + bytes(range(256)) * 257
    report = {"passed": False, "deviceTest": False, "realUiActions": True,
              "systemDocumentPicker": True, "pickerCancelAndReopen": False,
              "wifiDiscoveryTest": False, "cloudProviderTest": False}
    log = build / "ios-documents-ui.log"
    try:
        send_r6(4644, [(sample_name, payload)])
        deadline = time.monotonic() + 20
        sample = documents / sample_name
        while not sample.is_file() or sample.read_bytes() != payload:
            if time.monotonic() >= deadline:
                raise RuntimeError("系统选择器样本未由真实R6接收器正确提交")
            time.sleep(0.1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 49231))
            listener.listen(1)
            listener.settimeout(0.25)
            cancelled = threading.Event()

            # 日期：2026-11-26；独立接收器只等待产品连接，不注入发送数据、不重发。
            def receive_document():
                deadline = time.monotonic() + 360
                while not cancelled.is_set() and time.monotonic() < deadline:
                    try:
                        connection, _ = listener.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(30)
                        return receive_files(connection, [(sample_name, payload)])
                raise RuntimeError("系统文档选择未产生真实文件发送连接")

            with ThreadPoolExecutor(max_workers=1) as executor:
                received = executor.submit(receive_document)
                try:
                    command(log, "xcodebuild", "-project", build / "ui" / "MobileSendTests.xcodeproj",
                            "-scheme", "MobileSendTests", "-configuration", "Debug",
                            "-destination", "platform=iOS Simulator,id=" + device,
                            "-derivedDataPath", build / "ui-derived", "CODE_SIGNING_ALLOWED=NO",
                            "CODE_SIGNING_REQUIRED=NO", "-parallel-testing-enabled", "NO",
                            "-only-testing:MobileSendTests/MobileSendTests/testSendFileFromSystemDocuments",
                            "-resultBundlePath", build / "ios-documents.xcresult",
                            "test-without-building", timeout=480)
                    report.update(received.result(timeout=35))
                finally:
                    cancelled.set()
        report.update(passed=True, pickerCancelAndReopen=True, receiveBeforeSelecting=True,
                      sendRetries=0, processRestarts=0,
                      transport="iOS simulator system Files provider to production Qt R6 sender")
        return report
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (build / "ios-documents-send.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")


# 日期：2026-11-26；目录先由产品接收入库，再经系统Files授权发送，逐条核对中文、空文件、空目录和源保留。
def verify_directory_send(device, build, documents):
    folder = "a-ios-directory-probe"
    payload = "iOS目录系统授权\n".encode("utf-8") + bytes(range(256)) * 259
    fixtures = [(folder, None), (folder + "/中文 空格.bin", payload),
                (folder + "/empty.bin", b""), (folder + "/空目录", None)]
    report = {"passed": False, "deviceTest": False, "realUiActions": True,
              "systemDocumentPicker": True, "pickerCancelAndReopen": False,
              "wifiDiscoveryTest": False, "cloudProviderTest": False}
    log = build / "ios-directory-ui.log"
    try:
        send_r6(4644, fixtures)
        deadline = time.monotonic() + 20
        while True:
            ready = all((documents / name).is_dir() if data is None else
                        (documents / name).is_file() and (documents / name).read_bytes() == data
                        for name, data in fixtures)
            if ready:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("目录样本未由真实R6接收器完整提交")
            time.sleep(0.1)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 49231))
            listener.listen(1)
            listener.settimeout(0.25)
            cancelled = threading.Event()

            # 日期：2026-11-26；只接收产品产生的连接，任何路径、哨兵、内容或EOF不符立即失败。
            def receive_directory():
                deadline = time.monotonic() + 360
                while not cancelled.is_set() and time.monotonic() < deadline:
                    try:
                        connection, _ = listener.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(30)
                        return receive_files(connection, fixtures)
                raise RuntimeError("系统目录选择未产生真实发送连接")

            with ThreadPoolExecutor(max_workers=1) as executor:
                received = executor.submit(receive_directory)
                try:
                    command(log, "xcodebuild", "-project", build / "ui" / "MobileSendTests.xcodeproj",
                            "-scheme", "MobileSendTests", "-configuration", "Debug",
                            "-destination", "platform=iOS Simulator,id=" + device,
                            "-derivedDataPath", build / "ui-derived", "CODE_SIGNING_ALLOWED=NO",
                            "CODE_SIGNING_REQUIRED=NO", "-parallel-testing-enabled", "NO",
                            "-only-testing:MobileSendTests/MobileSendTests/testSendDirectoryFromSystemDocuments",
                            "-resultBundlePath", build / "ios-directory.xcresult",
                            "test-without-building", timeout=480)
                    report.update(received.result(timeout=35))
                finally:
                    cancelled.set()
        for name, data in fixtures:
            path = documents / name
            if not (path.is_dir() if data is None else path.is_file() and path.read_bytes() == data):
                raise RuntimeError("目录发送后源文件或目录被改变: " + name)
        report.update(passed=True, pickerCancelAndReopen=True, sourcePreserved=True,
                      receiveBeforeSelecting=True, sendRetries=0, processRestarts=0,
                      transport="iOS simulator system Files directory to production Qt R6 sender")
        return report
    except Exception as error:
        report["error"] = str(error)
        raise
    finally:
        (build / "ios-directory-send.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
