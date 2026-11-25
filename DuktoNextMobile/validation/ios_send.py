"""日期：2026-11-26；XCTest操作原始Qt应用，以独立R6接收器核对真实文字发送。"""
import json
from pathlib import Path
import socket
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from android_send import receive_text

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
    deadline = time.monotonic() + 180
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
                            "test-without-building", timeout=240)
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
