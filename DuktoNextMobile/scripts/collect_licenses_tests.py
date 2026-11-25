"""日期：2026-11-25；验证任意名称许可、元数据相对引用以及缺失/越界拒绝。"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from collect_licenses import licenses


class LicenseCollectionTests(unittest.TestCase):
    # 日期：2026-11-25；此前遗漏的blessing/FTL及父目录内合法引用都必须随包保存并校验摘要。
    def test_declared_arbitrary_names_and_multiline_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            metadata = source / "thirdparty/font"
            metadata.mkdir(parents=True)
            (source / "FTL.TXT").write_text("font notice", "utf-8")
            (metadata / "blessing.txt").write_text("public domain notice", "utf-8")
            (metadata / "qt_attribution.json").write_text(
                '[{"Id":"font","LicenseFile":"../../FTL.TXT","Description":"line1\nline2"},'
                '{"Id":"sqlite","LicenseFile":"blessing.txt"}]', "utf-8")
            licenses(source, root / "install", "fixture")
            output = root / "install/licenses/fixture"
            manifest = json.loads((output / "license-manifest.json").read_text("utf-8"))
            names = {item["path"] for item in manifest["files"]}
            self.assertIn("FTL.TXT", names)
            self.assertIn("thirdparty/font/blessing.txt", names)
            self.assertEqual(len(manifest["attributions"]), 2)
            for item in manifest["files"]:
                self.assertEqual(hashlib.sha256((output / item["path"]).read_bytes()).hexdigest(),
                                 item["sha256"])

    # 日期：2026-11-25；声明存在但文件缺失时不能生成完整收据。
    def test_missing_declared_file_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source").mkdir()
            (root / "source/qt_attribution.json").write_text(
                '{"LicenseFile":"MISSING.TXT"}', "utf-8")
            with self.assertRaises(ValueError):
                licenses(root / "source", root / "install", "fixture")
            self.assertFalse((root / "install/licenses/fixture/license-manifest.json").exists())

    # 日期：2026-11-25；不允许元数据把工作区外文件带入公开安装包。
    def test_outside_reference_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "source").mkdir()
            (root / "private.txt").write_text("must not copy", "utf-8")
            (root / "source/qt_attribution.json").write_text(
                '{"LicenseFile":"../private.txt"}', "utf-8")
            with self.assertRaises(ValueError):
                licenses(root / "source", root / "install", "fixture")
            self.assertFalse((root / "install/licenses/private.txt").exists())


if __name__ == "__main__":
    unittest.main()
