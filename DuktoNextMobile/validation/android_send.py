"""日期：2026-11-25；从原始APK真实界面发送系统分享文本，由独立R6接收器核对。"""
import hashlib
from pathlib import Path
import re
import shlex
import socket
import struct
import time
import uuid
import xml.etree.ElementTree as ET

from android_emulator import adb


# 日期：2026-11-25；只接受完整有界字节，截断和超时不能算作发送完成。
def receive_exact(connection, length):
    if length < 0 or length > 262144:
        raise ValueError("独立接收器长度越界")
    result = bytearray()
    while len(result) < length:
        chunk = connection.recv(min(4096, length - len(result)))
        if not chunk:
            raise RuntimeError("APK发送流提前结束")
        result.extend(chunk)
    return bytes(result)


# 日期：2026-11-25；独立解析文本线格式，逐字节核对UTF-8正文及结束边界。
def receive_text(connection, expected):
    count, total = struct.unpack("<qq", receive_exact(connection, 16))
    if count != 1 or total != len(expected):
        raise RuntimeError("APK文本批次条目数或长度错误")
    name = bytearray()
    while len(name) < 64:
        value = receive_exact(connection, 1)
        if value == b"\0":
            break
        name.extend(value)
    else:
        raise RuntimeError("APK文本名称未结束")
    if bytes(name) != b"___DUKTO___TEXT___":
        raise RuntimeError("APK未发送R6文本标记")
    size, = struct.unpack("<q", receive_exact(connection, 8))
    if size != total or receive_exact(connection, size) != expected:
        raise RuntimeError("APK文本正文不一致")
    if connection.recv(1) != b"":
        raise RuntimeError("APK文本包含额外数据")
    return {"bytes": total, "sha256": hashlib.sha256(expected).hexdigest(),
            "utf8Text": True, "independentWireParser": True}


# 日期：2026-11-26；提供固定中文二进制与空文件，来源提供器和独立接收器共用公开样本。
def file_fixtures():
    return [("中文 sample.bin", "系统content授权文件 / UTF-8\n".encode("utf-8") + bytes(range(256)) * 512),
            ("empty zero.bin", b"")]


# 日期：2026-11-26；独立检查R6文件批次，名称、数量、总长、正文和EOF缺一不可。
def receive_files(connection, fixtures):
    expected = dict(fixtures)
    if len(expected) != len(fixtures):
        raise ValueError("验收样本名称重复")
    count, total = struct.unpack("<qq", receive_exact(connection, 16))
    if count != len(fixtures) or total != sum(len(data) for data in expected.values()):
        raise RuntimeError("APK文件批次条目数或总长错误")
    files = []
    for _ in range(count):
        name = bytearray()
        while len(name) < 512:
            value = receive_exact(connection, 1)
            if value == b"\0":
                break
            name.extend(value)
        else:
            raise RuntimeError("APK文件名称未结束")
        try:
            name = bytes(name).decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise RuntimeError("APK文件名称不是UTF-8") from error
        if name not in expected:
            raise RuntimeError("APK文件名称错误或重复: " + name)
        data = expected.pop(name)
        size, = struct.unpack("<q", receive_exact(connection, 8))
        if size != len(data) or receive_exact(connection, size) != data:
            raise RuntimeError("APK文件长度或内容不一致: " + name)
        files.append({"name": name, "bytes": size, "sha256": hashlib.sha256(data).hexdigest()})
    if expected or connection.recv(1) != b"":
        raise RuntimeError("APK文件批次缺少条目或包含额外数据")
    return {"bytes": total, "files": files, "independentWireParser": True,
            "utf8Path": True, "emptyFile": True, "perFileContentVerified": True}


# 日期：2026-11-26；从持久系统服务读取真实控件树，拒绝旧快照且不创建临时UiAutomation。
def ui_tree(output, stage):
    token = uuid.uuid4().hex
    adb("shell", "am", "broadcast", "-a", "org.duktonext.validation.SNAPSHOT",
        "-p", "org.duktonext.validation", "--es", "token", token)
    raw = adb("shell", "run-as", "org.duktonext.validation", "cat", "files/tree.xml")
    tree = ET.fromstring(raw)
    if tree.get("token") != token:
        raise RuntimeError("系统无障碍快照未更新，拒绝使用旧控件树")
    (output / (stage + ".xml")).write_text(raw, "utf-8")
    return tree


# 日期：2026-11-26；地址框紧随目标标签，端口SpinBox也可编辑，不能仅按可编辑数量定位。
def wait_target_field(output):
    deadline = time.monotonic() + 15
    while True:
        tree = ui_tree(output, "target")
        fields = []
        for parent in tree.iter("node"):
            children = list(parent)
            for index, label in enumerate(children[:-1]):
                if "目标 IP 或主机名" not in (label.get("text"), label.get("content-desc")):
                    continue
                field = children[index + 1]
                if (field.get("editable") == "true" and field.get("enabled") == "true"
                        and field.get("visible-to-user") == "true"):
                    fields.append(field)
        if len(fields) == 1:
            return fields[0]
        if time.monotonic() >= deadline:
            raise RuntimeError("无法按目标标签唯一定位地址输入框，实际数量: " + str(len(fields)))
        time.sleep(0.3)


# 日期：2026-11-25；严格从控件矩形中心点击，不用固定屏幕坐标掩盖布局问题。
def tap_node(node):
    numbers = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
    if not numbers or node.get("enabled") != "true":
        raise RuntimeError("界面控件不可用或缺少有效位置")
    left, top, right, bottom = map(int, numbers.groups())
    if right <= left or bottom <= top:
        raise RuntimeError("界面控件没有可点击区域")
    adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))


# 日期：2026-11-25；同名可访问节点优先选择可点击父控件，缺失时保存现场并失败。
def find_label(tree, label):
    nodes = [node for node in tree.iter("node")
             if label in (node.get("text"), node.get("content-desc"))
             and node.get("enabled") == "true"
             and node.get("visible-to-user", "true") == "true"]
    return next((node for node in nodes if node.get("clickable") == "true"),
                nodes[0] if nodes else None)


# 日期：2026-11-26；从真实发送表单视口推导滑动区域，窄屏下到达底部系统分享按钮。
def scroll_send_form(tree):
    viewports = [parent for parent in tree.iter("node")
                 if any("目标 IP 或主机名" in (child.get("text"), child.get("content-desc"))
                        for child in parent)]
    if len(viewports) != 1:
        raise RuntimeError("无法唯一确定发送表单滚动区域")
    match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]",
                         viewports[0].get("bounds", ""))
    if not match:
        raise RuntimeError("发送表单缺少系统矩形")
    left, top, right, bottom = map(int, match.groups())
    if right <= left or bottom - top < 100:
        raise RuntimeError("发送表单滚动区域过小")
    middle = (left + right) // 2
    height = bottom - top
    adb("shell", "input", "swipe", str(middle), str(top + height * 4 // 5),
        str(middle), str(top + height // 5), "450")


# 日期：2026-11-26；等待有界；指定发送表单按钮不可见时，按系统视口实际滚动后重新读取节点。
def click_label(output, stage, label, scroll=False):
    deadline = time.monotonic() + 15
    scrolls = 0
    while True:
        tree = ui_tree(output, stage)
        node = find_label(tree, label)
        if node is not None:
            tap_node(node)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("没有找到界面控件: " + label)
        if scroll and scrolls < 6:
            scroll_send_form(tree)
            scrolls += 1
        time.sleep(0.3)


# 日期：2026-11-26；先等待异步分享摘要，避免顶栏插入后按旧控件坐标点击。
def wait_share_ready(output, label):
    deadline = time.monotonic() + 15
    while find_label(ui_tree(output, "share-ready"), label) is None:
        if time.monotonic() >= deadline:
            raise RuntimeError("系统分享摘要未就绪: " + label)
        time.sleep(0.3)


# 日期：2026-11-26；编辑后核对系统节点实际值，只在系统报告软键盘显示时返回，避免关闭弹窗。
def enter_target(output, address):
    field = wait_target_field(output)
    if address not in (field.get("text"), field.get("content-desc")):
        tap_node(field)
        focus_deadline = time.monotonic() + 10
        while wait_target_field(output).get("focused") != "true":
            if time.monotonic() >= focus_deadline:
                raise RuntimeError("目标地址框未获得系统焦点")
            time.sleep(0.3)
        adb("shell", "input", "keycombination", "113", "29")
        adb("shell", "input", "text", address)
    deadline = time.monotonic() + 10
    while True:
        field = wait_target_field(output)
        if address in (field.get("text"), field.get("content-desc")):
            break
        if time.monotonic() >= deadline:
            raise RuntimeError("目标地址输入未生效")
        time.sleep(0.3)
    keyboard = adb("shell", "dumpsys", "input_method")
    (output / "input-method.txt").write_text(keyboard, "utf-8")
    if re.search(r"(?:mInputShown|isInputViewShown|inputShown)=true", keyboard):
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
    wait_target_field(output)


# 日期：2026-11-25；系统分享→指定目标→发送均经真实Activity和QML控件，不注入测试控制器。
def verify_text_send_ui(output):
    output = Path(output) / "r6-send"
    output.mkdir(parents=True, exist_ok=True)
    original_pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
    # 日期：2026-11-25；先通过系统真实授权按钮关闭首次通知弹窗，再操作产品欢迎页。
    tree = ui_tree(output, "initial")
    permission = next((node for node in tree.iter("node")
                       if node.get("resource-id", "").endswith(":id/permission_allow_button")), None)
    if permission is not None:
        tap_node(permission)
    else:
        adb("shell", "pm", "grant", "org.duktonext.mobile", "android.permission.POST_NOTIFICATIONS")
    click_label(output, "welcome", "开始使用")
    text = "原始APK真实界面发送：中文与空格 / UTF-8 " + uuid.uuid4().hex
    command = ["am", "start", "-W", "-n", "org.duktonext.mobile/.DuktoActivity",
               "-a", "android.intent.action.SEND", "-t", "text/plain",
               "--es", "android.intent.extra.TEXT", text]
    launch = adb("shell", shlex.join(command))
    (output / "share-launch.txt").write_text(launch, "utf-8")
    if "Status: ok" not in launch:
        raise RuntimeError("系统分享Activity未正常启动")
    wait_share_ready(output, "系统分享：0项文件，含文字。请选择设备发送，或在服务器页上传。")
    click_label(output, "manual", "IP 连接 · 发送到指定设备")
    enter_target(output, "10.0.2.2")
    click_label(output, "shared-text", "查看系统分享文字", scroll=True)
    (output / "send-editor.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 4644))
        listener.listen(1)
        listener.settimeout(40)
        click_label(output, "submit", "发送")
        connection, peer = listener.accept()
        with connection:
            connection.settimeout(30)
            result = receive_text(connection, text.encode("utf-8"))
    if adb("shell", "pidof", "org.duktonext.mobile").strip() != original_pid:
        raise RuntimeError("发送期间应用进程被替换")
    (output / "send-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    result.update(passed=True, transport="Android emulator 10.0.2.2 TCP4644 to independent host receiver",
                  systemShareText=True, realUiActions=True, notificationGranted=True,
                  validationAccessibilityService=True,
                  sendRetries=0, processRestarts=0, deviceTest=False, fileSendTest=False,
                  wifiDiscoveryTest=False)
    return result


# 日期：2026-11-25；服务由安装验收在首次启动前统一管理，此处只操作真实界面。
def verify_text_send(output):
    return verify_text_send_ui(output)


# 日期：2026-11-26；来源应用通过系统只读授权分享两份文件，真实QML按钮发送给独立接收器。
def verify_file_send(output):
    output = Path(output) / "r6-file-send"
    output.mkdir(parents=True, exist_ok=True)
    original_pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
    if not original_pid:
        raise RuntimeError("文件发送前应用没有运行")
    launch = adb("shell", "am", "start", "-W", "-n",
                 "org.duktonext.validation/.ValidationShareActivity")
    (output / "share-launch.txt").write_text(launch, "utf-8")
    if "Status: ok" not in launch:
        raise RuntimeError("系统文件分享来源Activity未正常启动")
    wait_share_ready(output, "系统分享：2项文件。请选择设备发送，或在服务器页上传。")
    click_label(output, "manual", "IP 连接 · 发送到指定设备")
    enter_target(output, "10.0.2.2")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("0.0.0.0", 4644))
        listener.listen(1)
        listener.settimeout(40)
        click_label(output, "submit", "发送系统分享文件（2项）", scroll=True)
        connection, peer = listener.accept()
        with connection:
            connection.settimeout(30)
            result = receive_files(connection, file_fixtures())
    if adb("shell", "pidof", "org.duktonext.mobile").strip() != original_pid:
        raise RuntimeError("文件发送期间应用进程被替换")
    (output / "send-completed.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
    result.update(passed=True, systemContentUriShare=True, realUiActions=True,
                  transport="Android emulator 10.0.2.2 TCP4644 to independent host receiver",
                  sendRetries=0, processRestarts=0, deviceTest=False, wifiDiscoveryTest=False)
    return result
