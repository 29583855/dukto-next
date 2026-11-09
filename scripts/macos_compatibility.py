"""日期：2026-11-09；独立解析所有Mach-O架构切片，拒绝高于声明系统基线的包内程序或依赖。"""

import argparse
import json
from pathlib import Path
import plistlib
import re
import struct

MAGICS = {b"\xcf\xfa\xed\xfe": ("<", 32), b"\xfe\xed\xfa\xcf": (">", 32),
          b"\xce\xfa\xed\xfe": ("<", 28), b"\xfe\xed\xfa\xce": (">", 28)}
FAT_MAGICS = {b"\xca\xfe\xba\xbe": (">", False), b"\xbe\xba\xfe\xca": ("<", False),
              b"\xca\xfe\xba\xbf": (">", True), b"\xbf\xba\xfe\xca": ("<", True)}
ARCHITECTURES = {0x01000007: "x86_64", 0x0100000C: "arm64"}


# 日期：2026-11-09；严格解析版本，不采用字符串顺序，12.10必须大于12.7。
def version(value):
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", value):
        raise ValueError("Invalid macOS version: " + value)
    parts = [int(part) for part in value.split(".")]
    return tuple((parts + [0])[:3])


# 日期：2026-11-09；统一解码Mach-O内置的16/8/8位系统版本号。
def encoded_version(value):
    return f"{value >> 16}.{(value >> 8) & 255}.{value & 255}"


# 日期：2026-11-09；以边界检查解析单个切片，不能用外层应用声明掩盖依赖的真实要求。
def thin_image(data):
    if data[:4] not in MAGICS:
        raise ValueError("Invalid Mach-O slice")
    endian, header_size = MAGICS[data[:4]]
    if len(data) < header_size:
        raise ValueError("Truncated Mach-O header")
    cpu = struct.unpack_from(endian + "I", data, 4)[0]
    count, command_bytes = struct.unpack_from(endian + "II", data, 16)
    end = header_size + command_bytes
    if count > 65536 or end > len(data):
        raise ValueError("Invalid Mach-O load-command bounds")
    offset, minima = header_size, []
    for _ in range(count):
        if offset + 8 > end:
            raise ValueError("Truncated Mach-O load command")
        command, size = struct.unpack_from(endian + "II", data, offset)
        if size < 8 or offset + size > end:
            raise ValueError("Invalid Mach-O load-command size")
        if command == 0x32:
            if size < 24:
                raise ValueError("Truncated LC_BUILD_VERSION")
            target, minimum, sdk = struct.unpack_from(endian + "III", data, offset + 8)
            if target != 1:
                raise ValueError("Non-macOS platform in application")
            minima.append((minimum, sdk))
        elif command == 0x24:
            if size < 16:
                raise ValueError("Truncated LC_VERSION_MIN_MACOSX")
            minima.append(struct.unpack_from(endian + "II", data, offset + 8))
        offset += size
    if offset != end or len(minima) != 1 or cpu not in ARCHITECTURES:
        raise ValueError("Missing/ambiguous macOS deployment version or unsupported architecture")
    return {"architecture": ARCHITECTURES[cpu], "minimumMacOS": encoded_version(minima[0][0]),
            "sdkVersion": encoded_version(minima[0][1])}


# 日期：2026-11-09；通用二进制的每个切片都要检查，支持两种字节序和64位fat头。
def image_versions(data):
    if data[:4] in MAGICS:
        return [thin_image(data)]
    if data[:4] not in FAT_MAGICS or len(data) < 8:
        raise ValueError("Not a supported Mach-O image")
    endian, wide = FAT_MAGICS[data[:4]]
    count = struct.unpack_from(endian + "I", data, 4)[0]
    entry_size = 32 if wide else 20
    if not 1 <= count <= 16 or 8 + count * entry_size > len(data):
        raise ValueError("Invalid universal Mach-O header")
    results, ranges = [], []
    for index in range(count):
        position = 8 + index * entry_size
        cpu = struct.unpack_from(endian + "I", data, position)[0]
        offset, size = struct.unpack_from(endian + ("QQ" if wide else "II"), data, position + 8)
        if offset < 8 + count * entry_size or size < 28 or offset + size > len(data):
            raise ValueError("Invalid universal Mach-O slice bounds")
        if any(offset < previous_end and offset + size > previous_start
               for previous_start, previous_end in ranges):
            raise ValueError("Overlapping universal Mach-O slices")
        result = thin_image(data[offset:offset + size])
        if ARCHITECTURES.get(cpu) != result["architecture"]:
            raise ValueError("Universal header/slice architecture mismatch")
        ranges.append((offset, offset + size))
        results.append(result)
    return results


# 日期：2026-11-09；识别可执行文件、动态库和插件，非Mach-O资源不参与系统基线判定。
def is_macho(path):
    with path.open("rb") as stream:
        magic = stream.read(4)
    return magic in MAGICS or magic in FAT_MAGICS


# 日期：2026-11-09；发布前同时核对Finder声明和所有原生载荷，任一依赖超限就拒绝打包。
def audit_app(app, minimum, architecture):
    baseline = version(minimum)
    with (app / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    if version(info.get("LSMinimumSystemVersion", "")) != baseline:
        raise ValueError("Info.plist minimum macOS does not match package baseline")
    records = []
    for image in sorted(app.rglob("*")):
        if not image.is_file() or image.is_symlink() or not is_macho(image):
            continue
        slices = image_versions(image.read_bytes())
        if architecture not in {item["architecture"] for item in slices}:
            raise ValueError("Missing native architecture: " + str(image))
        for item in slices:
            if version(item["minimumMacOS"]) > baseline:
                raise ValueError(f"{image}: requires macOS {item['minimumMacOS']}, baseline is {minimum}")
        records.append({"image": image.relative_to(app).as_posix(), "slices": slices})
    if not records:
        raise ValueError("No native images in application")
    return {"minimumMacOS": minimum, "architecture": architecture, "passed": True,
            "nativeImageCount": len(records), "images": records}


# 日期：2026-11-09；允许在打包后单独复验，不修改程序、版本标记或代码签名。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("app", type=Path)
    parser.add_argument("--minimum", default="12.0")
    parser.add_argument("--architecture", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = audit_app(args.app.resolve(strict=True), args.minimum, args.architecture)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", "utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "images"}))


if __name__ == "__main__":
    main()
