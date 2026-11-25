"""日期：2026-11-25；检查实际移动产物结构并生成可审计开发包，不宣称真机通过。"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import tarfile
import zipfile


# 日期：2026-11-25；流式计算产物摘要，不把整个APK读进内存。
def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for data in iter(lambda: source.read(1024 * 1024), b""):
            result.update(data)
    return result.hexdigest()


# 日期：2026-11-25；逐个检查APK内arm64共享库的ELF LOAD段和16KiB页对齐。
def elf_alignment(data, name):
    if data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("不是arm64 ELF64: " + name)
    offset = struct.unpack_from("<Q", data, 32)[0]
    size, count = struct.unpack_from("<HH", data, 54)
    loads = []
    if size != 56 or count > 1024:
        raise ValueError("ELF程序头不合法: " + name)
    for index in range(count):
        kind, flags, file_offset, address, _, _, _, alignment = struct.unpack_from("<IIQQQQQQ", data, offset + index * size)
        if kind == 1:
            if alignment < 16384 or (file_offset - address) % 16384:
                raise ValueError("ELF未满足16KiB对齐: " + name)
            loads.append(alignment)
    if not loads:
        raise ValueError("ELF缺LOAD段: " + name)
    return {"name": name, "loadAlignments": loads}


# 日期：2026-11-25；用SDK验证实际APK签名、包名和对齐，并检查每一个原生库。
def inspect_android(apk, environment):
    tools = Path(environment["ANDROID_SDK_ROOT"]) / "build-tools/35.0.0"
    subprocess.run([tools / "apksigner", "verify", "--verbose", "--print-certs", apk], check=True)
    subprocess.run([tools / "zipalign", "-c", "-P", "16", "-v", "4", apk], check=True)
    badging = subprocess.check_output([tools / "aapt", "dump", "badging", apk], text=True)
    if "name='org.duktonext.mobile'" not in badging or "sdkVersion:'29'" not in badging or "targetSdkVersion:'35'" not in badging:
        raise ValueError("APK包名或SDK范围不匹配")
    libraries = []
    with zipfile.ZipFile(apk) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("APK存在重复条目")
        for name in archive.namelist():
            if name.startswith("lib/") and name.endswith(".so"):
                if not name.startswith("lib/arm64-v8a/"):
                    raise ValueError("APK包含未验收架构")
                libraries.append(elf_alignment(archive.read(name), name))
        if not any("DuktoNextMobile" in item["name"] for item in libraries) or "classes.dex" not in archive.namelist():
            raise ValueError("APK缺少应用库或Java代码")
    return {"kind": "debug-apk", "signatureVerified": True, "zipAlignmentVerified": True,
            "nativeLibraries": libraries, "badging": badging}


# 日期：2026-11-25；核对设备Mach-O与系统权限说明，未签名app只作为构建产物。
def inspect_ios(app):
    with (app / "Info.plist").open("rb") as source:
        info = plistlib.load(source)
    binary = app / info["CFBundleExecutable"]
    with binary.open("rb") as source:
        header = source.read(32)
    if header[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack_from("<I", header, 4)[0] != 0x100000c:
        raise ValueError("iOS应用不是arm64 Mach-O")
    if info.get("CFBundleIdentifier") != "org.duktonext.mobile" or not info.get("NSLocalNetworkUsageDescription"):
        raise ValueError("iOS标识或局域网说明缺失")
    if info.get("MinimumOSVersion") != "15.0" or set(info.get("UIDeviceFamily", [])) != {1, 2}:
        raise ValueError("iOS系统或设备范围不匹配")
    if not os.access(binary, os.X_OK):
        raise ValueError("iOS可执行位缺失")
    links = subprocess.check_output(["xcrun", "otool", "-L", binary], text=True)
    # 日期：2026-11-25；otool首行是被检查文件自身的绝对路径，只检查后续动态依赖条目。
    dependencies = [line.strip().split(" (", 1)[0] for line in links.splitlines()[1:] if line.strip()]
    if any(path in link for link in dependencies for path in ["/Users/", "/home/", "/private/tmp/", "/opt/homebrew/"]):
        raise ValueError("iOS链接包含构建机路径")
    return {"kind": "unsigned-device-app", "bundleId": info["CFBundleIdentifier"],
            "minimumOS": info["MinimumOSVersion"], "architecture": "arm64",
            "executableSha256": digest(binary), "executableBytes": binary.stat().st_size,
            "signed": (app / "_CodeSignature").exists(), "linkedLibraries": links}


# 日期：2026-11-25；将检查通过的开发产物放入独立目录，保留iOS执行权限和校验收据。
def package(platform, artifacts, destination, environment):
    destination.mkdir(parents=True, exist_ok=True)
    if platform == "android":
        if len(artifacts) != 1:
            raise ValueError("APK产物数量不唯一")
        receipt = inspect_android(artifacts[0], environment)
        output = destination / "DuktoNextMobile-android-arm64-debug.apk"
        shutil.copy2(artifacts[0], output)
    else:
        # 日期：2026-11-25；qmake可能有多个相同输出位置，分别核验后只归档一个。
        results = [inspect_ios(app) for app in artifacts]
        if len({item["executableSha256"] for item in results}) != 1:
            raise ValueError("iOS多个app内容不一致")
        receipt = results[0]
        output = destination / "DuktoNextMobile-ios-arm64-unsigned.tar.gz"
        with tarfile.open(output, "w:gz") as archive:
            archive.add(artifacts[0], arcname="DuktoNextMobile.app")
        with tarfile.open(output) as archive:
            executable = archive.getmember("DuktoNextMobile.app/DuktoNextMobile")
            if not executable.mode & 0o111:
                raise ValueError("iOS归档执行权限丢失")
    receipt.update({"platform": platform, "sourceCommit": environment.get("GITHUB_SHA", "local"),
                    "runId": environment.get("GITHUB_RUN_ID", "local"), "date": "2026-11-25",
                    "package": output.name, "sha256": digest(output), "deviceTestsPassed": False,
                    "signedForDistribution": False})
    (destination / "package-inspection.json").write_bytes((json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    (destination / "SHA256SUMS.txt").write_bytes((receipt["sha256"] + "  " + output.name + "\n").encode("utf-8"))
    (destination / "使用前必读.txt").write_bytes(("Dukto Next Mobile 开发构建；2026-11-25\nAndroid为调试签名测试APK；iOS为未签名设备app的tar.gz归档，不能直接安装。\n尚无真机验收，不作为客户发行版。安装步骤、能力和限制见项目docs。\n").encode("utf-8"))
    return receipt
