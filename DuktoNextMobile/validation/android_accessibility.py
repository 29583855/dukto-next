"""日期：2026-11-25；为模拟器启用独立无障碍服务，产品APK及业务状态保持原样。"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import time
import zipfile

from android_emulator import adb


# 日期：2026-11-25；工具失败立即中止，SDK路径和构建文件仅来自本次验收目录。
def run(*command):
    subprocess.run([str(value) for value in command], check=True, capture_output=True, timeout=90)


# 日期：2026-11-25；使用SDK构建无网络权限的辅助APK，不重签或修改待验产品APK。
def build_helper(output):
    source = Path(__file__).resolve().parent / "accessibility"
    sdk = Path(os.environ["ANDROID_SDK_ROOT"])
    tools = sdk / "build-tools/35.0.0"
    android = sdk / "platforms/android-35/android.jar"
    build = output / "accessibility-helper"
    classes, dex = build / "classes", build / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(exist_ok=True)
    run("javac", "-source", "8", "-target", "8", "-bootclasspath", android,
        "-d", classes, *sorted(source.glob("*.java")))
    run(tools / "d8", "--lib", android, "--output", dex, *classes.rglob("*.class"))
    unsigned, aligned, signed = [build / name for name in ["unsigned.apk", "aligned.apk", "helper.apk"]]
    # 日期：2026-11-26；资产供系统content提供器读取，独立接收器仍逐字节核对线协议内容。
    assets = build / "assets"
    assets.mkdir(exist_ok=True)
    from android_send import file_fixtures
    fixtures = file_fixtures()
    (assets / "sample").write_bytes(fixtures[0][1])
    (assets / "empty").write_bytes(fixtures[1][1])
    run(tools / "aapt", "package", "-f", "-M", source / "AndroidManifest.xml",
        "-I", android, "-S", source / "res", "-A", assets, "-F", unsigned)
    with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as bundle:
        bundle.write(dex / "classes.dex", "classes.dex")
    key = build / "validation.jks"
    run("keytool", "-genkeypair", "-keystore", key, "-storepass", "android",
        "-keypass", "android", "-alias", "validation", "-keyalg", "RSA",
        "-validity", "2", "-dname", "CN=Dukto Emulator Validation")
    run(tools / "zipalign", "-f", "4", unsigned, aligned)
    run(tools / "apksigner", "sign", "--ks", key, "--ks-pass", "pass:android",
        "--out", signed, aligned)
    return signed


# 日期：2026-11-25；持续启用系统服务避免单次dump退出时Qt撤下虚拟控件树，最终还原设置。
@contextmanager
def accessibility_session(output):
    original = adb("shell", "settings", "get", "secure", "enabled_accessibility_services").strip()
    enabled = adb("shell", "settings", "get", "secure", "accessibility_enabled").strip()
    component = "org.duktonext.validation/.ValidationAccessibility"
    apk = build_helper(output)
    adb("install", "-r", str(apk), timeout=90)
    try:
        # 日期：2026-11-26；显式启动辅助包，等待系统完成安装注册和服务绑定后才创建产品控件。
        adb("shell", "am", "start", "--user", "0", "-W", "-n",
            "org.duktonext.validation/.ValidationActivity")
        # 日期：2026-11-26；Android 15限制侧载服务，授权仅限本次无网络权限的验收辅助包。
        adb("shell", "appops", "set", "--user", "0", "org.duktonext.validation",
            "ACCESS_RESTRICTED_SETTINGS", "allow")
        (output / "accessibility-appops.txt").write_text(
            adb("shell", "appops", "get", "org.duktonext.validation",
                "ACCESS_RESTRICTED_SETTINGS"), "utf-8")
        services = component if original in ("null", "") else original + ":" + component
        adb("shell", "settings", "put", "secure", "enabled_accessibility_services", services)
        adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
        deadline = time.monotonic() + 45
        while True:
            state = adb("shell", "dumpsys", "accessibility")
            logs = adb("logcat", "-d", "-s", "DuktoValidation:I", "*:S")
            (output / "accessibility-services.txt").write_text(state, "utf-8")
            (output / "accessibility-helper-log.txt").write_text(logs, "utf-8")
            snapshot = {name: adb("shell", "settings", "get", "secure", name).strip()
                        for name in ("enabled_accessibility_services", "accessibility_enabled")}
            (output / "accessibility-settings.json").write_text(
                json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", "utf-8")
            bound_services = state.split("Bound services:", 1)[-1].split("Enabled services:", 1)[0]
            if ("accessibility-bound" in logs
                    and component in snapshot["enabled_accessibility_services"]
                    and "label=Dukto validation accessibility," in bound_services):
                # 日期：2026-11-26；系统Bound列表仅给标签，额外以新随机快照证明服务可响应。
                from android_send import ui_tree
                ui_tree(output, "accessibility-bound")
                break
            # 日期：2026-11-26；安装异步广播可能重置设置，按实际读回结果恢复，不能冒充绑定成功。
            if snapshot["enabled_accessibility_services"] != services:
                adb("shell", "settings", "put", "secure", "enabled_accessibility_services", services)
            if snapshot["accessibility_enabled"] != "1":
                adb("shell", "settings", "put", "secure", "accessibility_enabled", "1")
            if time.monotonic() >= deadline:
                (output / "accessibility-package.txt").write_text(
                    adb("shell", "dumpsys", "package", "org.duktonext.validation"), "utf-8")
                raise RuntimeError("辅助无障碍服务未实际绑定，停止界面测试，详见系统状态和服务日志")
            time.sleep(0.5)
        yield
    finally:
        for name, value in [("enabled_accessibility_services", original), ("accessibility_enabled", enabled)]:
            if value == "null":
                adb("shell", "settings", "delete", "secure", name)
            else:
                adb("shell", "settings", "put", "secure", name, value)
        adb("uninstall", "org.duktonext.validation")
