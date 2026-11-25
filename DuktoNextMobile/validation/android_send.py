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
from android_accessibility import accessibility_session


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


# 日期：2026-11-25；通过系统无障碍树定位实际可见控件，保留每一步原始XML供复核。
def ui_tree(output, stage):
    path = "/sdcard/dukto-mobile-validation.xml"
    adb("shell", "uiautomator", "dump", "--compressed", path, timeout=30)
    raw = adb("shell", "cat", path)
    (output / (stage + ".xml")).write_text(raw, "utf-8")
    return ET.fromstring(raw)


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
             and node.get("enabled") == "true"]
    return next((node for node in nodes if node.get("clickable") == "true"),
                nodes[0] if nodes else None)


# 日期：2026-11-25；等待异步界面出现有明确上限，过程中不重启应用、不重发传输。
def click_label(output, stage, label):
    deadline = time.monotonic() + 15
    while True:
        node = find_label(ui_tree(output, stage), label)
        if node is not None:
            tap_node(node)
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("没有找到界面控件: " + label)
        time.sleep(0.3)


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
    click_label(output, "manual", "IP 连接 · 发送到指定设备")
    tree = ui_tree(output, "target")
    fields = [node for node in tree.iter("node")
              if node.get("class") == "android.widget.EditText"
              and node.get("enabled") == "true" and node.get("text") != "4644"]
    if len(fields) != 1:
        raise RuntimeError("无法唯一定位目标地址输入框")
    tap_node(fields[0])
    adb("shell", "input", "text", "10.0.2.2")
    adb("shell", "input", "keyevent", "KEYCODE_BACK")
    click_label(output, "shared-text", "查看系统分享文字")
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


# 日期：2026-11-25；独立系统无障碍服务仅辅助获取真实控件，结束时清理，不注入应用业务。
def verify_text_send(output):
    with accessibility_session(Path(output)):
        return verify_text_send_ui(output)
