"""日期：2026-11-25；缓存验证不得误用Android、缺文件、旧源码锁或未来构建器。"""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from validate_ios_cache import REQUIRED, REVIEWED_CURRENT, REVIEWED_BUILDERS, validate


class CacheTests(unittest.TestCase):
    # 日期：2026-11-25；创建完整最小安装布局，测试实际拒绝边界。
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.prefix = Path(self.temporary.name)
        self.lock = {"qtVersion": "5.15.19", "sources": [{"sha256": "fixed"}]}
        self.manifest = {"platform": "ios", "sourceBuild": True, "dependencies": self.lock,
                         "builderSha256": REVIEWED_CURRENT,
                         "host": "macOS-15.7.5-arm64-arm-64bit"}
        for relative in REQUIRED:
            path = self.prefix / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture")

    # 日期：2026-11-25；每次校验从磁盘重新读取，覆盖真实缓存恢复接口。
    def check_cache(self, builder=REVIEWED_CURRENT, machine="arm64"):
        (self.prefix / "dependency-manifest.json").write_text(json.dumps(self.manifest), "utf-8")
        return validate(self.prefix, self.lock, builder, machine)[0]

    # 日期：2026-11-25；两个已审查构建器都允许iOS源码等价复用。
    def test_reviewed_builders(self):
        for builder in REVIEWED_BUILDERS:
            self.manifest["builderSha256"] = builder
            self.assertTrue(self.check_cache())

    # 日期：2026-11-26；真实构建器变更必须重新审查，避免合同自洽但每次构建均拒绝缓存。
    def test_bundled_builder_is_reviewed(self):
        builder = Path(__file__).with_name("build_dependencies.py")
        self.assertEqual(hashlib.sha256(builder.read_bytes()).hexdigest(), REVIEWED_CURRENT)

    # 日期：2026-11-25；未来脚本和未审查缓存都不能从宽兼容。
    def test_unreviewed_builders(self):
        self.assertFalse(self.check_cache(builder="future"))
        self.manifest["builderSha256"] = "unknown"
        self.assertFalse(self.check_cache())

    # 日期：2026-11-25；不能混用平台、架构、系统代际或不同依赖锁。
    def test_incompatible_inputs(self):
        for field, value in (("platform", "android"), ("sourceBuild", False),
                             ("dependencies", {}), ("host", "macOS-14.8-arm64-arm-64bit")):
            saved = self.manifest[field]
            self.manifest[field] = value
            self.assertFalse(self.check_cache())
            self.manifest[field] = saved
        self.assertFalse(self.check_cache(machine="x86_64"))

    # 日期：2026-11-25；部分恢复或空库不能跳过依赖构建。
    def test_incomplete_installation(self):
        target = self.prefix / REQUIRED[-1]
        target.write_bytes(b"")
        self.assertFalse(self.check_cache())
        target.unlink()
        self.assertFalse(self.check_cache())

    # 日期：2026-11-25；损坏收据返回不可用而非终止工作流。
    def test_corrupt_receipt(self):
        (self.prefix / "dependency-manifest.json").write_text("{broken", "utf-8")
        self.assertFalse(validate(self.prefix, self.lock, REVIEWED_CURRENT, "arm64")[0])


if __name__ == "__main__":
    unittest.main()
