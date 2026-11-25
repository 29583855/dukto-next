"""日期：2026-11-26；经真实Android系统文档选择器取消、重选和发送，独立核对文件。"""
from pathlib import Path
import hashlib
import json
import re
import shlex
import socket
import time
import uuid

from android_emulator import adb, sandbox, send_r6, wait_for_file
from android_send import (click_label, enter_target, find_label, receive_files,
                          tap_node, ui_tree)


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


# 日期：2026-11-26；系统选择器可能记忆多级目录，逐次返回并确认产品恢复，避免误关产品窗口。
def cancel_picker(output, stage):
    deadline = time.monotonic() + 30
    for attempt in range(10):
        tree = ui_tree(output, stage + "-" + str(attempt))
        packages = {node.get("package", "") for node in tree.iter("node")}
        if any(package.endswith(".documentsui") for package in packages):
            if time.monotonic() >= deadline:
                break
            adb("shell", "input", "keyevent", "KEYCODE_BACK")
            time.sleep(0.3)
        elif "org.duktonext.mobile" in packages:
            return
        else:
            raise RuntimeError("取消系统文档选择器后未返回产品：" + ",".join(sorted(packages)))
    raise RuntimeError("系统文档选择器在有界返回次数内未取消")


# 日期：2026-11-26；等待目录内容加载后按真实节点导航，不能把空白初帧当作根目录列表。
def open_downloads(output):
    deadline = time.monotonic() + 15
    roots_opened = False
    while True:
        tree = wait_picker(output, "picker-initial")
        if find_label(tree, "Files in Download") is not None:
            return
        # 日期：2026-11-26；系统树选择器会记忆子目录，面包屑文字禁用时点击其真实启用父容器。
        parents = {child: parent for parent in tree.iter() for child in parent}
        breadcrumb = next((node for node in tree.iter("node")
                           if node.get("text") == "Download"
                           and node.get("resource-id", "").endswith(":id/breadcrumb_text")), None)
        if breadcrumb is not None:
            target = breadcrumb if breadcrumb.get("enabled") == "true" else parents[breadcrumb]
            tap_node(target)
            time.sleep(0.3)
            if time.monotonic() >= deadline:
                raise RuntimeError("下载目录面包屑点击后未进入Download")
            continue
        if find_label(tree, "Download") is not None:
            click_label(output, "picker-download-directory", "Download")
            return
        if find_label(tree, "Downloads") is not None:
            click_label(output, "picker-downloads", "Downloads")
            return
        if not roots_opened and find_label(tree, "Show roots") is not None:
            click_label(output, "picker-roots", "Show roots")
            roots_opened = True
        if time.monotonic() >= deadline:
            raise RuntimeError("系统目录列表加载后仍缺少Download或Downloads节点")
        time.sleep(0.3)


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
    cancel_picker(output, "file-send-cancel")
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
    cancel_picker(output, "file-export-cancel")
    wait_message(output, "已取消导出")
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


# 日期：2026-11-26；目录样本同时覆盖中文名称、嵌套二进制、空文件及空目录。
def directory_fixtures(root):
    return [(root, None), (root + "/空目录", None), (root + "/nested", None),
            (root + "/nested/中文 sample.bin", "系统目录授权 / SAF\n".encode("utf-8") + bytes(range(256)) * 129),
            (root + "/zero.bin", b"")]


# 日期：2026-11-26；只在外部Downloads播种样本，应用私有文档由真实选择器导入或网络接收产生。
def seed_external_tree(output, root):
    fixtures = directory_fixtures(root)
    seed = output / "external-seed"
    for name, data in fixtures:
        target = seed / name
        if data is None:
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    # 日期：2026-11-26；逐项播种并读回，避免ADB递归推送遗漏空目录或媒体提供器未同步。
    for name, data in fixtures:
        destination = "/sdcard/Download/" + name
        if data is None:
            adb("shell", shlex.join(["mkdir", "-p", destination]))
        else:
            adb("push", str(seed / name), destination)
            adb("shell", shlex.join(["am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
                                     "-d", "file://" + destination]))
    verify_tree_content(fixtures, external=True, output=output)
    (output / "external-seed-verified.txt").write_text(
        adb("shell", shlex.join(["find", "/sdcard/Download/" + root])), "utf-8")
    return fixtures


# 日期：2026-11-26；按系统真实名称点击树授权与确认按钮，缺少可访问节点即失败并保留现场。
def grant_download_tree(output, root):
    tree = wait_picker(output, "tree-before-navigation")
    if find_label(tree, "Files in " + root) is None:
        open_downloads(output)
        click_label(output, "tree-open-" + root, root)
    deadline = time.monotonic() + 15
    while True:
        tree = wait_picker(output, "tree-grant")
        label = next((label for label in ("Use this folder", "USE THIS FOLDER")
                      if find_label(tree, label) is not None), None)
        if label is not None:
            click_label(output, "tree-use", label)
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("系统目录选择器缺少授权按钮")
        time.sleep(0.3)
    deadline = time.monotonic() + 15
    while True:
        tree = ui_tree(output, "tree-confirm")
        label = next((label for label in ("Allow", "ALLOW")
                      if find_label(tree, label) is not None), None)
        if label is not None:
            click_label(output, "tree-allow", label)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("系统目录授权确认未出现")
        time.sleep(0.3)


# 日期：2026-11-26；应用状态与每个落盘条目均需满足，空文件不能被空目录或反向替代。
def verify_tree_content(fixtures, external=False, output=None):
    for name, data in fixtures:
        if external:
            path = "/sdcard/Download/" + name
            adb("shell", shlex.join(["test", "-d" if data is None else "-f", path]))
            if data is not None:
                # 日期：2026-11-26；exec-out使用单层远端命令引用，保留中文和空格路径且避免重复sh解析。
                actual = adb("exec-out", shlex.join(["cat", path]), binary=True)
                if actual != data:
                    diagnostic = dict(path=name, expectedBytes=len(data), actualBytes=len(actual),
                                      expectedSha256=hashlib.sha256(data).hexdigest(),
                                      actualSha256=hashlib.sha256(actual).hexdigest(),
                                      actualPrefixHex=actual[:96].hex(),
                                      remoteMetadata=adb("shell", shlex.join(["ls", "-ln", path])),
                                      remoteHash=adb("shell", shlex.join(["sha256sum", path])))
                    if output is not None:
                        (Path(output) / "tree-content-mismatch.json").write_text(
                            json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n", "utf-8")
                        (Path(output) / "tree-content-actual.bin").write_bytes(actual)
                    raise RuntimeError("系统目录内容错误: " + json.dumps(diagnostic, ensure_ascii=False))
        else:
            directories = sandbox("find", ".", "-type", "d", "-name", "Documents").splitlines()
            if len(directories) != 1:
                raise RuntimeError("无法唯一定位应用文档目录")
            path = directories[0] + "/" + name
            sandbox("test", "-d" if data is None else "-f", path)
            if data is not None:
                wait_for_file(path, data)


# 日期：2026-11-26；等待真实产品完成状态，保留系统节点快照以区分授权失败与产品复制失败。
def wait_message(output, text, prefix=False):
    deadline = time.monotonic() + 30
    while True:
        tree = ui_tree(output, "tree-product-completed")
        if find_label(tree, text) is not None:
            return
        if prefix and any((node.get("text", "").startswith(text)
                           or node.get("content-desc", "").startswith(text))
                          for node in tree.iter("node")):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("产品目录操作未完成: " + text)
        time.sleep(0.3)


# 日期：2026-11-26；从原始APK执行目录发送、导入与导出，不注入产品入口，不重发掩盖失败。
def verify_saf_directory(output):
    output = Path(output) / "saf-directory"
    output.mkdir(parents=True, exist_ok=True)
    pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
    tree = ui_tree(output, "before-directory")
    if find_label(tree, "Close") is not None:
        click_label(output, "close-files", "Close")
    source_root = "dukto-tree-" + uuid.uuid4().hex
    fixtures = seed_external_tree(output, source_root)
    click_label(output, "directory-manual-cancel", "IP 连接 · 发送到指定设备")
    enter_target(output, "10.0.2.2")
    click_label(output, "directory-send-cancel", "发送文件夹", scroll=True)
    wait_picker(output, "directory-cancel")
    cancel_picker(output, "directory-send-cancel")
    click_label(output, "directory-manual-reopen", "IP 连接 · 发送到指定设备")
    enter_target(output, "10.0.2.2")
    click_label(output, "directory-send-reopen", "发送文件夹", scroll=True)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 4644))
        listener.listen(1)
        listener.settimeout(40)
        grant_download_tree(output, source_root)
        connection, _ = listener.accept()
        with connection:
            connection.settimeout(30)
            sent = receive_files(connection, fixtures)
    (output / "directory-send-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    click_label(output, "directory-application-files", "应用文件")
    click_label(output, "directory-import", "导入目录")
    grant_download_tree(output, source_root)
    wait_message(output, "已导入1项到应用文件目录")
    verify_tree_content(fixtures)
    (output / "directory-import-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    click_label(output, "directory-files-close", "Close")
    exported_root = "a-directory-export-" + uuid.uuid4().hex
    received = directory_fixtures(exported_root)
    port = int(adb("forward", "tcp:0", "tcp:4644").strip())
    try:
        send_r6(port, received)
        verify_tree_content(received)
    finally:
        adb("forward", "--remove", "tcp:" + str(port))
    target = "dukto-target-" + uuid.uuid4().hex
    adb("shell", "mkdir", "-p", "/sdcard/Download/" + target)
    click_label(output, "directory-export-files", "应用文件")
    click_label(output, "directory-export-open", "[目录] " + exported_root)
    click_label(output, "directory-export-cancel", "导出目录")
    wait_picker(output, "directory-export-cancel-picker")
    cancel_picker(output, "directory-export-cancel")
    wait_message(output, "已取消导出")
    click_label(output, "directory-export-reopen", "导出目录")
    grant_download_tree(output, target)
    wait_message(output, "已完成系统导出")
    verify_tree_content([(target + "/" + name, data) for name, data in received],
                        external=True, output=output)
    # 日期：2026-11-26；实际禁用系统提供器，验证启动失败可读、进程存活，恢复后可以重新打开。
    provider = "com.google.android.documentsui"
    try:
        disabled = adb("shell", "pm", "disable-user", "--user", "0", provider)
        (output / "provider-disabled.txt").write_text(disabled, "utf-8")
        if "package:" + provider not in adb("shell", "pm", "list", "packages", "-d"):
            raise RuntimeError("验收环境未禁用系统DocumentsUI，不能验证缺失提供器恢复")
        click_label(output, "directory-export-unavailable", "导出目录")
        wait_message(output, "无法打开系统文档选择器：", prefix=True)
        if adb("shell", "pidof", "org.duktonext.mobile").strip() != pid:
            raise RuntimeError("系统文档提供器不可用时产品进程退出")
    finally:
        enabled = adb("shell", "pm", "enable", "--user", "0", provider)
        (output / "provider-enabled.txt").write_text(enabled, "utf-8")
    click_label(output, "directory-export-provider-restored", "导出目录")
    wait_picker(output, "directory-export-provider-recovered")
    cancel_picker(output, "directory-export-provider-cancel")
    wait_message(output, "已取消导出")
    if adb("shell", "pidof", "org.duktonext.mobile").strip() != pid:
        raise RuntimeError("系统目录操作期间产品进程意外重启")
    log = adb("logcat", "-d", "--pid=" + pid)
    (output / "directory-logcat.txt").write_text(log, "utf-8")
    if re.search(r"FATAL EXCEPTION|Fatal signal|OutOfMemoryError|ForegroundServiceDidNotStartInTimeException", log):
        raise RuntimeError("系统目录操作期间出现运行异常")
    (output / "directory-export-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    return dict(passed=True, systemDocumentTreePicker=True, realUiActions=True,
                independentDirectorySend=sent, importContentVerified=True,
                receiveBeforeExport=True, exportContentVerified=True,
                emptyDirectory=True, emptyFile=True, utf8Path=True,
                sendCancelAndReopen=True, exportCancelAndReopen=True,
                unavailableProviderRecovery=True,
                processRestarts=0, sendRetries=0, deviceTest=False,
                wifiDiscoveryTest=False, cloudProviderTest=False)
