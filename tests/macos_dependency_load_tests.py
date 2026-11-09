"""日期：2026-11-09；验证动态库自身ID与真正加载命令的区分，防止源码依赖打包重写循环。"""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from package_macos import parse_dylib_loads


class DependencyLoadTests(unittest.TestCase):
    # 日期：2026-11-09；otool包含裸文件名库ID时，仍只返回真正依赖并保留名称中的空格。
    def test_bare_install_id_is_not_dependency(self):
        commands = """app/Contents/Frameworks/libcrypto.3.dylib:
Load command 0
          cmd LC_ID_DYLIB
      cmdsize 48
         name libcrypto.3.dylib (offset 24)
Load command 1
          cmd LC_LOAD_DYLIB
      cmdsize 72
         name @executable_path/../Frameworks/Qt Core.framework/Versions/5/QtCore (offset 24)
Load command 2
          cmd LC_LOAD_WEAK_DYLIB
      cmdsize 72
         name /usr/lib/libSystem.B.dylib (offset 24)
Load command 3
          cmd LC_RPATH
      cmdsize 40
         path @executable_path/../Frameworks (offset 12)
"""
        self.assertEqual(parse_dylib_loads(commands), [
            "@executable_path/../Frameworks/Qt Core.framework/Versions/5/QtCore",
            "/usr/lib/libSystem.B.dylib"])

    # 日期：2026-11-09；通用镜像重复名称去重，重新导出依赖仍需被打包和校验。
    def test_reexport_and_duplicate_architectures(self):
        command = "Load command 0\n cmd LC_REEXPORT_DYLIB\n cmdsize 48\n name @rpath/a.dylib (offset 24)\n"
        self.assertEqual(parse_dylib_loads(command * 2), ["@rpath/a.dylib"])

    # 日期：2026-11-09；畸形加载命令不能被静默忽略后认定依赖闭包完整。
    def test_missing_load_name_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_dylib_loads("Load command 0\n cmd LC_LOAD_DYLIB\n cmdsize 48\n")


if __name__ == "__main__":
    unittest.main()
