"""日期：2026-11-26；经真实Android系统文档选择器取消、重选和发送，独立核对文件。"""
from pathlib import Path
import hashlib
import re
import socket
import time
import uuid

from android_emulator import adb, sandbox, send_r6, wait_for_file
from android_send import (click_label, enter_target, find_label, receive_files,
                          ui_tree)


# 日期：2026-11-26；确认系统提供器实际显示，不能把产品占位页当作原生文档选择器。
def wait_picker(output, stage):
    deadline = time.monotonic() + 15
    while True:
        tree = ui_tree(output, stage)
        packages = {node.get("package", "") for node in tree.iter("node")}
        if any(package.endswith(".documentsui") for package in packages):
            return tree
        if time.monotonic() >= deadline:
            raise RuntimeError("真实系统文档选择器未出现：" + ",".join(sorted(packages)))
        time.sleep(0.3)


# 日期：2026-11-26；从可见系统根目录选择Downloads，名称来自系统英文测试镜像。
def open_downloads(output):
    tree = wait_picker(output, "picker-initial")
    if find_label(tree, "Show roots") is not None:
        click_label(output, "picker-roots", "Show roots")
    click_label(output, "picker-downloads", "Downloads")


# 日期：2026-11-26；只播种外部样本，选择和发送均由原始APK及系统控件完成。
def verify_saf_file_send(output):
    output = Path(output) / "saf-file-send"
    output.mkdir(parents=True, exist_ok=True)
    pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
    name = "dukto-saf-probe-" + uuid.uuid4().hex + ".bin"
    payload = "系统文档选择器真实授权 / SAF\n".encode("utf-8") + bytes(range(256)) * 257
    sample = output / name
    sample.write_bytes(payload)
    adb("shell", "mkdir", "-p", "/sdcard/Download")
    adb("push", str(sample), "/sdcard/Download/" + name)
    adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", "file:///sdcard/Download/" + name)
    click_label(output, "manual-cancel", "IP 连接 · 发送到指定设备")
    enter_target(output, "10.0.2.2")
    click_label(output, "open-cancel", "发送文件", scroll=True)
    wait_picker(output, "cancel-picker")
    (output / "cancel-picker.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    adb("shell", "input", "keyevent", "KEYCODE_BACK")
    # 日期：2026-11-26；取消后必须可再次打开并传输，验证迟到回调和busy状态已释放。
    click_label(output, "manual-reopen", "IP 连接 · 发送到指定设备")
    enter_target(output, "10.0.2.2")
    click_label(output, "open-retry", "发送文件", scroll=True)
    open_downloads(output)
    (output / "downloads.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 4644))
        listener.listen(1)
        listener.settimeout(40)
        click_label(output, "select-file", name)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(30)
            result = receive_files(connection, [(name, payload)])
    if adb("shell", "pidof", "org.duktonext.mobile").strip() != pid:
        raise RuntimeError("系统文档选择期间产品进程意外重启")
    log = adb("logcat", "-d", "--pid=" + pid)
    (output / "saf-logcat.txt").write_text(log, "utf-8")
    if re.search(r"FATAL EXCEPTION|Fatal signal|OutOfMemoryError|ForegroundServiceDidNotStartInTimeException", log):
        raise RuntimeError("系统文档选择收发期间出现运行异常")
    (output / "send-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    result.update(passed=True, realUiActions=True, systemDocumentPicker=True,
                  pickerCancelAndReopen=True, standardDownloadsProvider=True,
                  processRestarts=0, sendRetries=0, deviceTest=False,
                  wifiDiscoveryTest=False, utf8Path=False, emptyFile=False)
    return result


# 日期：2026-11-26；通过实际接收器建立样本，再从产品文件浏览器调用系统导出并逐字节读回。
def verify_saf_file_export(output):
    output = Path(output) / "saf-file-export"
    output.mkdir(parents=True, exist_ok=True)
    pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
    directories = sandbox("find", ".", "-type", "d", "-name", "Documents").splitlines()
    if len(directories) != 1 or not directories[0].startswith("./"):
        raise RuntimeError("无法唯一定位接收目录")
    name = "a-export-probe-" + uuid.uuid4().hex + ".bin"
    payload = "系统文件导出真实写回 / SAF\n".encode("utf-8") + bytes(range(256)) * 257
    port = int(adb("forward", "tcp:0", "tcp:4644").strip())
    try:
        send_r6(port, [(name, payload)])
        wait_for_file(directories[0] + "/" + name, payload)
    finally:
        adb("forward", "--remove", "tcp:" + str(port))
    click_label(output, "application-files", "应用文件")
    click_label(output, "export-file", name)
    wait_picker(output, "export-picker")
    # 日期：2026-11-26；第一次取消后从同一文件重新打开，验证导出回调也能正确解忙。
    adb("shell", "input", "keyevent", "KEYCODE_BACK")
    click_label(output, "export-reopen", name)
    open_downloads(output)
    deadline = time.monotonic() + 15
    while True:
        tree = ui_tree(output, "export-save")
        labels = [label for label in ("Save", "SAVE") if find_label(tree, label) is not None]
        if labels:
            click_label(output, "export-confirm", labels[0])
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("系统导出选择器缺少可用保存按钮")
        time.sleep(0.3)
    deadline = time.monotonic() + 30
    while True:
        try:
            actual = adb("exec-out", "cat", "/sdcard/Download/" + name, binary=True)
        except RuntimeError as error:
            if "No such file" not in str(error):
                raise
            actual = None
        tree = ui_tree(output, "export-completed")
        if actual == payload and find_label(tree, "已完成系统导出") is not None:
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("导出文件内容或产品完成状态核对失败")
        time.sleep(0.3)
    if adb("shell", "pidof", "org.duktonext.mobile").strip() != pid:
        raise RuntimeError("导出期间产品进程重启")
    (output / "export-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    (output / "export-logcat.txt").write_text(adb("logcat", "-d", "--pid=" + pid), "utf-8")
    return dict(passed=True, systemDocumentPicker=True, realUiActions=True,
                receiveBeforeExport=True, pickerCancelAndReopen=True,
                exportedFileReadBack=True, bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(), fileName=name,
                processRestarts=0, deviceTest=False, wifiDiscoveryTest=False,
                directoryExportTest=False, cloudProviderTest=False)
