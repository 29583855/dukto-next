"""日期：2026-11-09；复现主程序与依赖最低版本不一致，覆盖通用切片和损坏Mach-O拒绝。"""

from pathlib import Path
import plistlib
import struct
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from macos_compatibility import audit_app, image_versions, version


# 日期：2026-11-09；构造真实格式的最小Mach-O加载命令，同时覆盖新旧系统版本命令。
def image(major=12, cpu=0x0100000C, legacy=False, endian="<"):
    command = (struct.pack(endian + "IIII", 0x24, 16, major << 16, 15 << 16) if legacy else
               struct.pack(endian + "IIIIII", 0x32, 24, 1, major << 16, 15 << 16, 0))
    return struct.pack(endian + "IIIIIIII", 0xFEEDFACF, cpu, 0, 2, 1, len(command), 0, 0) + command


# 日期：2026-11-09；两种架构混合打包，验证不能只扫描第一个低版本切片。
def universal(first, second):
    start = 48
    return (struct.pack(">II", 0xCAFEBABE, 2) +
            struct.pack(">IIIII", 0x0100000C, 0, start, len(first), 0) +
            struct.pack(">IIIII", 0x01000007, 0, start + len(first), len(second), 0) + first + second)


class CompatibilityTests(unittest.TestCase):
    # 日期：2026-11-09；新命令、旧命令与大端头必须给出相同系统基线。
    def test_load_command_versions(self):
        for legacy, endian in ((False, "<"), (True, "<"), (False, ">")):
            self.assertEqual(image_versions(image(legacy=legacy, endian=endian))[0]["minimumMacOS"], "12.0.0")

    # 日期：2026-11-09；数字版本比较不能将12.10误判为比12.7更旧。
    def test_numeric_versions(self):
        self.assertGreater(version("12.10"), version("12.7.6"))
        with self.assertRaises(ValueError):
            version("12")

    # 日期：2026-11-09；必须识别通用归档中每个切片的真实系统要求。
    def test_all_universal_slices(self):
        records = image_versions(universal(image(), image(15, 0x01000007)))
        self.assertEqual([item["minimumMacOS"] for item in records], ["12.0.0", "15.0.0"])

    # 日期：2026-11-09；畸形、截断和越界命令必须明确失败，不能跳过后放行。
    def test_malformed_images(self):
        bad_command = bytearray(image())
        struct.pack_into("<I", bad_command, 36, 4)
        for data in (b"", image()[:20], image()[:-1], bytes(bad_command), b"\xca\xfe\xba\xbe" + b"\xff" * 12):
            with self.assertRaises(ValueError):
                image_versions(data)

    # 日期：2026-11-09；执行真正的整包扫描，重现旧OpenSSL要求15而程序只声明12的问题。
    def test_dependency_floor_and_declared_version(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary) / "Dukto Next.app"
            executable = app / "Contents/MacOS/dukto-gui"
            dependency = app / "Contents/Frameworks/libcrypto.3.dylib"
            executable.parent.mkdir(parents=True)
            dependency.parent.mkdir(parents=True)
            info = app / "Contents/Info.plist"
            info.write_bytes(plistlib.dumps({"LSMinimumSystemVersion": "12.0"}))
            executable.write_bytes(image())
            dependency.write_bytes(image(15))
            with self.assertRaisesRegex(ValueError, "libcrypto"):
                audit_app(app, "12.0", "arm64")
            dependency.write_bytes(image())
            self.assertEqual(audit_app(app, "12.0", "arm64")["nativeImageCount"], 2)
            with self.assertRaisesRegex(ValueError, "architecture"):
                audit_app(app, "12.0", "x86_64")
            info.write_bytes(plistlib.dumps({"LSMinimumSystemVersion": "15.0"}))
            with self.assertRaisesRegex(ValueError, "Info.plist"):
                audit_app(app, "12.0", "arm64")
            info.write_bytes(plistlib.dumps({"LSMinimumSystemVersion": "12.0"}))
            dependency.write_bytes(universal(image(), image(15, 0x01000007)))
            with self.assertRaisesRegex(ValueError, "requires macOS 15"):
                audit_app(app, "12.0", "arm64")


if __name__ == "__main__":
    unittest.main()
