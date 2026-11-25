"""日期：2026-11-25；验证验包器的真实文件输入及外部链接拒绝路径。"""
import os
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
from unittest.mock import patch
from inspect_package import elf_alignment, inspect_ios, package


class PackageInspectionTests(unittest.TestCase):
    # 日期：2026-11-25；创建最小设备Mach-O输入，外部工具输出单独替换，不将夹具记为设备构建通过。
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.app = self.root / "DuktoNextMobile.app"
        self.app.mkdir()
        info = {"CFBundleExecutable": "DuktoNextMobile", "CFBundleIdentifier": "org.duktonext.mobile",
                "MinimumOSVersion": "15.0", "UIDeviceFamily": [1, 2], "NSLocalNetworkUsageDescription": "局域网传输"}
        (self.app / "Info.plist").write_bytes(plistlib.dumps(info))
        self.binary = self.app / "DuktoNextMobile"
        self.binary.write_bytes(struct.pack("<IIIIIIII", 0xfeedfacf, 0x100000c, 0, 2, 0, 0, 0, 0))
        self.binary.chmod(0o755)

    # 日期：2026-11-25；otool自身标题可以是构建绝对路径，系统依赖及归档执行权限仍须通过。
    @patch("inspect_package.subprocess.check_output")
    def test_header_path_is_not_dependency(self, output):
        output.return_value = "/Users/runner/build/DuktoNextMobile:\n\t/usr/lib/libSystem.B.dylib (compatibility version 1.0.0)\n"
        if os.name == "nt":
            receipt = inspect_ios(self.app)
            self.assertEqual(receipt["architecture"], "arm64")
            return  # Windows无POSIX执行位，归档权限只在Unix门禁验证。
        receipt = package("ios", [self.app], self.root / "packages", {"GITHUB_SHA": "fixture"})
        self.assertEqual(receipt["architecture"], "arm64")
        self.assertFalse(receipt["deviceTestsPassed"])
        self.assertTrue((self.root / "packages" / receipt["package"]).is_file())

    # 日期：2026-11-25；动态库实际引用构建机路径时必须拒绝，不能因为放过标题而放过依赖。
    @patch("inspect_package.subprocess.check_output")
    def test_host_dynamic_library_is_rejected(self, output):
        output.return_value = "DuktoNextMobile:\n\t/Users/runner/libBad.dylib (compatibility version 1.0.0)\n"
        with self.assertRaisesRegex(ValueError, "构建机路径"):
            inspect_ios(self.app)

    # 日期：2026-11-25；相同ELF输入仅改变LOAD页对齐，拒绝4KiB而接受16KiB并检查架构。
    def test_every_load_requires_16k(self):
        image = bytearray(120)
        image[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", image, 18, 183)
        struct.pack_into("<Q", image, 32, 64)
        struct.pack_into("<HH", image, 54, 56, 1)
        struct.pack_into("<IIQQQQQQ", image, 64, 1, 5, 0, 0, 0, 120, 120, 4096)
        with self.assertRaisesRegex(ValueError, "16KiB"):
            elf_alignment(image, "fixture.so")
        struct.pack_into("<Q", image, 112, 16384)
        self.assertEqual(elf_alignment(image, "fixture.so")["loadAlignments"], [16384])
        struct.pack_into("<H", image, 18, 62)
        with self.assertRaisesRegex(ValueError, "arm64"):
            elf_alignment(image, "fixture.so")


if __name__ == "__main__":
    unittest.main()
