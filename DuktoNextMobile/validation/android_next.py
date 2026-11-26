"""日期：2026-11-26；原始APK通过真实服务器页面配对、浏览、上传下载，独立核对落盘。"""
import hashlib
import json
from pathlib import Path
import re
import selectors
import socket
import subprocess
import tempfile
import time

from android_emulator import adb, sandbox, wait_for_file
from android_documents import cancel_picker, open_downloads, wait_picker
from android_send import click_label, file_fixtures, find_label, tap_node, ui_tree, wait_share_ready


# 日期：2026-11-26；主机探针只准备独立服务，不代替Android客户端执行任何操作。
def service_command(probe, state, arguments):
    command = [str(probe), *arguments, "--state-directory", str(state), "--json"]
    result = subprocess.run(command, capture_output=True, encoding="utf-8", timeout=45)
    if result.returncode or result.stderr:
        raise RuntimeError("独立服务准备失败，退出码=" + str(result.returncode))
    events = [json.loads(line) for line in result.stdout.splitlines()]
    if len(events) != 1:
        raise RuntimeError("独立服务返回事件数量错误")
    return events[0]


# 日期：2026-11-26；仅从系统节点读取坐标，拒绝无效矩形及越界点击。
def bounds(node):
    match = re.fullmatch(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", node.get("bounds", ""))
    if not match:
        raise RuntimeError("系统节点缺少矩形")
    return tuple(map(int, match.groups()))


# 日期：2026-11-26；以实际TabBar和窗口矩形确定正文滑动范围，避开顶部导航与底部状态。
def scroll_server(tree, upward):
    tab = find_label(tree, "连接与文件")
    if tab is None:
        raise RuntimeError("不在真实服务器页面")
    windows = [bounds(n) for n in tree.iter("node") if n.get("package") == "org.duktonext.mobile"]
    left, top, right, bottom = max(windows, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
    start = bounds(tab)[3] + 50
    end = bottom - (bottom - top) // 5
    if end - start < 150:
        raise RuntimeError("服务器正文可滚动区域过小")
    x = left + (right - left) * 3 // 4
    high, low = start + (end - start) // 6, end - (end - start) // 6
    adb("shell", "input", "swipe", str(x), str(low if upward else high),
        str(x), str(high if upward else low), "450")
    time.sleep(0.3)


# 日期：2026-11-26；每次滚动重新读取可访问节点，次数有界，缺失即失败并保留现场。
def seek(output, label, upward=True):
    for index in range(13):
        tree = ui_tree(output, "seek-" + str(time.time_ns()))
        node = find_label(tree, label)
        if node is not None:
            return node
        if index < 12:
            scroll_server(tree, upward)
    raise RuntimeError("服务器页面控件不可达：" + label)


# 日期：2026-11-26；通过实际焦点与系统键盘替换ASCII参数，不注入QML或测试控制器。
def enter(output, label, value, upward=True):
    if not value.isascii() or any(char.isspace() for char in value):
        raise ValueError("键盘参数必须为无空白ASCII")
    tap_node(seek(output, label, upward))
    time.sleep(0.3)
    adb("shell", "input", "keycombination", "113", "29")
    adb("shell", "input", "text", value)
    keyboard = adb("shell", "dumpsys", "input_method")
    if re.search(r"(?:mInputShown|isInputViewShown|inputShown)=true", keyboard):
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
    time.sleep(0.3)


# 日期：2026-11-26；选择输入框后紧邻的真实按钮，避免多个“选择”控件被错误匹配。
def choose_adjacent(output, label):
    seek(output, label)
    tree = ui_tree(output, "adjacent-" + str(time.time_ns()))
    field = find_label(tree, label)
    parents = {child: parent for parent in tree.iter() for child in parent}
    siblings = list(parents[field])
    index = siblings.index(field)
    if index + 1 >= len(siblings):
        raise RuntimeError("输入框缺少相邻选择按钮：" + label)
    button = siblings[index + 1]
    if find_label(button, "选择") is None:
        raise RuntimeError("相邻控件不是可用选择按钮：" + label)
    tap_node(button)


# 日期：2026-11-26；凭据经真实系统选择器导入，先取消重开；不手工猜测应用进程私有路径。
def import_pairing(output, credential, external):
    adb("shell", "mkdir", "-p", "/sdcard/Download")
    adb("push", str(credential), external)
    adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", "file://" + external)
    choose_adjacent(output, "配对文件路径")
    wait_picker(output, "pairing-picker-cancel")
    cancel_picker(output, "pairing-cancel")
    choose_adjacent(output, "配对文件路径")
    open_downloads(output)
    click_label(output, "pairing-select", external.rsplit("/", 1)[1])
    deadline = time.monotonic() + 20
    while True:
        tree = ui_tree(output, "pairing-import-" + str(time.time_ns()))
        if find_label(tree, "配对并保存资料") is not None:
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("系统配对文件选择后未返回服务器页面")
        time.sleep(0.3)


# 日期：2026-11-26；等待实际产品状态并及时暴露操作错误，不以点击返回判断成功。
def wait_status(output, expected):
    deadline = time.monotonic() + 45
    while True:
        tree = ui_tree(output, "status-" + str(time.time_ns()))
        labels = [n.get("text", "") + " " + n.get("content-desc", "") for n in tree.iter("node")]
        failures = [label for label in labels if "操作失败（" in label]
        if failures:
            raise RuntimeError("服务器页面返回错误：" + failures[0])
        if any(expected in label for label in labels):
            (output / ("status-" + str(time.time_ns()) + ".png")).write_bytes(
                adb("exec-out", "screencap", "-p", binary=True))
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("服务器页面状态未按期出现：" + expected)
        time.sleep(0.4)


# 日期：2026-11-26；从真实共享目录逐字节核对上传，等待有界且禁止自动重发。
def wait_upload(root, fixtures):
    deadline = time.monotonic() + 45
    while True:
        if all((root / name).is_file() and (root / name).read_bytes() == content
               for name, content in fixtures):
            return
        if time.monotonic() >= deadline:
            raise RuntimeError("真实APK上传未完整落盘")
        time.sleep(0.2)


# 日期：2026-11-26；ADB反向通道仅用于模拟器传输，明确不代表Wi-Fi、Server2012或真机验收。
def verify_next(output, probe):
    output = Path(output) / "next-server"
    output.mkdir(parents=True, exist_ok=True)
    receipt = {"passed": False, "deviceTest": False, "wifiDiscoveryTest": False,
               "transport": "ADB reverse TCP to independent Linux host Next TLS service",
               "realUiActions": True, "sendRetries": 0, "processRestarts": 0, "checks": []}
    process = None
    port = None
    external = "/sdcard/Download/dukto-next-ui-pairing.json"
    original_pid = adb("shell", "pidof", "org.duktonext.mobile").strip()
    try:
        with tempfile.TemporaryDirectory(prefix="dukto-next-ui-") as temporary:
            root = Path(temporary)
            state, shared = root / "state", root / "shared"
            bundle = shared / "bundle"
            (bundle / "空目录").mkdir(parents=True)
            payload = ("Next客户端下载校验\n".encode("utf-8") + bytes(range(256)) * 257)
            (bundle / "中文 sample.bin").write_bytes(payload)
            (bundle / "empty zero.bin").write_bytes(b"")
            identity = service_command(probe, state, ["serve", "init", "--server-name", "127.0.0.1"])
            permissions = ["--allow-browse", "--allow-download", "--allow-upload"]
            service_command(probe, state, ["serve", "share", "add", "--share", "docs", "--path", str(shared), *permissions])
            offer = service_command(probe, state, ["serve", "pairing", "--share", "docs", *permissions])
            # 日期：2026-11-26；凭据正文留在临时文件，系统选择器导入后立即移除外部副本。
            credential = Path(offer["credentialFile"])
            # 日期：2026-11-26；仅使用回环空闲端口，端口竞争时失败而非盲目重跑。
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                reserved_port = str(reservation.getsockname()[1])
            process = subprocess.Popen([str(probe), "serve", "start", "--bind", "127.0.0.1", "--port", reserved_port,
                                        "--state-directory", str(state), "--json"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=15):
                    raise RuntimeError("独立Next服务未按期启动")
                listening = json.loads(process.stdout.readline())
            if listening.get("event") != "service-listening" or not listening.get("port"):
                raise RuntimeError("独立Next服务启动事件错误")
            port = str(listening["port"])
            adb("reverse", "tcp:" + port, "tcp:" + port)
            # 日期：2026-11-26；上一项文字发送可能留下发送页，按实际首页入口决定是否返回。
            for navigation in range(4):
                if find_label(ui_tree(output, "home-" + str(navigation)), "服务器 · 上传 / 下载") is not None:
                    break
                adb("shell", "input", "keyevent", "KEYCODE_BACK")
                time.sleep(0.3)
            click_label(output, "open-server", "服务器 · 上传 / 下载")
            click_label(output, "expand-pair", "首次连接：展开配对设置")
            enter(output, "服务器 IP:端口（默认 4646）", "127.0.0.1:" + port)
            enter(output, "核对服务器 SHA-256 指纹", identity["fingerprint"])
            import_pairing(output, credential, external)
            adb("shell", "rm", external)
            receipt["pairingSelection"] = {"systemDocumentPicker": True, "cancelAndReopen": True,
                                            "manualSandboxPath": False}
            tap_node(seek(output, "配对并保存资料"))
            wait_status(output, "配对成功；客户端 UUID：")
            receipt["checks"].append("uiPairWithPinnedFingerprint")
            clients = service_command(probe, state, ["serve", "clients"])
            if len(clients["entries"]) != 1 or clients["entries"][0].get("revoked"):
                raise RuntimeError("独立服务端未登记唯一有效客户端")
            # 日期：2026-11-26；收起配对表单，随后浏览必须经已保存资料独立认证。
            tap_node(seek(output, "首次连接：展开配对设置", upward=False))
            tap_node(seek(output, "浏览"))
            wait_status(output, "当前页 1 项")
            receipt["checks"].append("uiAuthenticatedBrowse")
            enter(output, "共享内相对路径；空表示共享根", "bundle")
            choose_adjacent(output, "本地保存目录（须已存在）")
            click_label(output, "download-choose-directory", "OK")
            directories = sandbox("find", "files", "-type", "d", "-name", "Documents").splitlines()
            if len(directories) != 1:
                raise RuntimeError("无法唯一定位应用下载目录")
            download_directory = directories[0]
            tap_node(seek(output, "下载"))
            wait_status(output, "任务状态：completed")
            # 日期：2026-11-26；目标位置由独立遍历确定，再逐字节检查文件和空目录，不能只看UI成功。
            matches = sandbox("find", download_directory, "-type", "f", "-name", "中文 sample.bin").splitlines()
            if len(matches) != 1:
                raise RuntimeError("下载目标文件数量错误")
            downloaded = matches[0]
            wait_for_file(downloaded, payload)
            parent = downloaded.rsplit("/", 1)[0]
            if sandbox("cat", parent + "/empty zero.bin", binary=True) != b"":
                raise RuntimeError("下载空文件内容错误")
            if not sandbox("ls", "-ld", parent + "/空目录").startswith("d"):
                raise RuntimeError("下载空目录缺失")
            receipt["download"] = {"bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(),
                                   "emptyFile": True, "emptyDirectory": True, "unicodePath": True}
            receipt["checks"].append("uiDownloadAndIndependentSandboxReadBack")
            click_label(output, "return-home", "‹ 返回")
            adb("shell", "am", "start", "-n", "org.duktonext.validation/.ValidationShareActivity")
            wait_share_ready(output, "系统分享：2项文件。请选择设备发送，或在服务器页上传。")
            click_label(output, "reopen-server", "服务器 · 上传 / 下载")
            # 日期：2026-11-26；远端目录改为bundle，上传同目录中的原始系统分享样本。
            tap_node(seek(output, "上传系统分享文件（2项）"))
            wait_status(output, "任务状态：completed")
            fixtures = file_fixtures()
            # 日期：2026-11-26；下载已有同名文件，默认keep-both必须保留旧件并给新件编号。
            expected = [("中文 sample (2).bin", fixtures[0][1]), ("empty zero (2).bin", b"")]
            wait_upload(bundle, expected)
            if (bundle / "中文 sample.bin").read_bytes() != payload:
                raise RuntimeError("上传错误覆盖服务器既有文件")
            receipt["upload"] = [{"name": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
                                 for name, data in expected]
            receipt["checks"].extend(["uiSystemShareUploadAndIndependentServerReadBack", "keepBothPreservesOriginal"])
            if adb("shell", "pidof", "org.duktonext.mobile").strip() != original_pid:
                raise RuntimeError("Next界面验收意外重启产品进程")
            receipt["passed"] = True
    except Exception as error:
        receipt["error"] = str(error)
        (output / "failure.png").write_bytes(adb("exec-out", "screencap", "-p", binary=True))
        raise
    finally:
        if port is not None:
            adb("reverse", "--remove", "tcp:" + port)
        if process is not None:
            process.terminate()
            out, err = process.communicate(timeout=10)
            # 日期：2026-11-26；服务事件不含凭据正文，仅保存公开协议执行记录。
            (output / "service-events.jsonl").write_text(out, "utf-8")
            (output / "service-stderr.txt").write_text(err, "utf-8")
        adb("shell", "rm", "-f", external)
        (output / "next-server.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    return receipt
