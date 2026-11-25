"""日期：2026-11-25；验证交付源码精确性、归档边界及离线依赖拒绝回退联网。"""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from build_dependencies import extract
from source_bundle import create, digest, verify


class SourceBundleTests(unittest.TestCase):
    # 日期：2026-11-25；构造独立临时仓库及真实小型上游归档，不接触客户源码或网络。
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="dukto-source-tests-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repository = self.root / "repository"
        self.repository.mkdir()
        self.cache = self.root / "cache"
        self.cache.mkdir()
        self.archive = self.cache / "dependency.tar.gz"
        with tarfile.open(self.archive, "w:gz") as bundle:
            member = tarfile.TarInfo("dependency/说明.txt")
            data = "原始依赖\n".encode("utf-8")
            member.size = len(data)
            bundle.addfile(member, io.BytesIO(data))
        self.entry = {"name": "dependency", "url": "https://invalid.test/dependency.tar.gz",
                      "sha256": digest(self.archive)}
        files = {"DuktoNextMobile/scripts/dependencies.json": json.dumps({"sources": [self.entry]}),
                 "DuktoNextMobile/LICENSE": "source license\n",
                 "DuktoNextMobile/app/sample.cpp": "// 原始源码\n",
                 "docs/iOS与Android开发计划与进度.md": "progress\n",
                 ".github/workflows/mobile-build.yml": "build\n",
                 ".github/workflows/mobile-storage.yml": "tests\n",
                 ".github/workflows/mobile-extended.yml": "install\n"}
        for relative, text in files.items():
            path = self.repository / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        self.git("init", "-q")
        self.git("add", ".")
        self.git("-c", "user.name=Source Test", "-c", "user.email=source@example.invalid",
                 "-c", "core.hooksPath=", "commit", "-qm", "fixture")

    # 日期：2026-11-25；仅在临时测试仓库内执行Git，并屏蔽继承的换行配置对样本字节的影响。
    def git(self, *arguments):
        return subprocess.check_output(["git", "-C", str(self.repository), "-c", "core.autocrlf=false", *arguments])

    # 日期：2026-11-25；真实导出与逐件复核，确认脏文件和未跟踪凭据不进入包，且输出可重复。
    def test_exact_commit_offline_reproducible(self):
        (self.repository / "DuktoNextMobile/app/sample.cpp").write_text("dirty", "utf-8")
        (self.repository / "DuktoNextMobile/private-token.json").write_text("untracked-secret", "utf-8")
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            first = create(self.repository, "HEAD", self.root / "first", self.cache)
            second = create(self.repository, "HEAD", self.root / "second", self.cache)
        self.assertEqual(first["archiveSha256"], second["archiveSha256"])
        archive = self.root / "first" / first["archiveFile"]
        self.assertTrue(verify(archive)["passed"])
        with tarfile.open(archive) as bundle:
            names = bundle.getnames()
            self.assertFalse(any("private-token" in name for name in names))
            sample = next(name for name in names if name.endswith("app/sample.cpp"))
            self.assertEqual(bundle.extractfile(sample).read(), "// 原始源码\n".encode("utf-8"))
        with self.assertRaises(FileExistsError):
            create(self.repository, "HEAD", self.root / "first", self.cache)

    # 日期：2026-11-25；归档位翻转后拒绝使用缓存，不能以联网覆盖掩盖损坏。
    def test_corrupt_cache_refused(self):
        self.archive.write_bytes(b"damaged")
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            with self.assertRaisesRegex(ValueError, "缓存源码摘要"):
                create(self.repository, "HEAD", self.root / "output", self.cache)

    # 日期：2026-11-25；补造路径穿越、链接、重复和未登记文件，验证无提取复核均拒绝。
    def test_archive_boundary_and_extra_files(self):
        result = create(self.repository, "HEAD", self.root / "valid", self.cache)
        archive = self.root / "valid" / result["archiveFile"]
        with tarfile.open(archive) as bundle:
            originals = [(member, bundle.extractfile(member).read()) for member in bundle]
        root = originals[0][0].name.split("/", 1)[0]
        for kind in ("traversal", "link", "duplicate", "extra", "corrupt"):
            with self.subTest(kind=kind):
                bad = self.root / (kind + ".tar.gz")
                with tarfile.open(bad, "w:gz") as bundle:
                    for index, (member, data) in enumerate(originals):
                        if kind == "corrupt" and index == 0:
                            data = b"x" * len(data)
                        bundle.addfile(member, io.BytesIO(data))
                    if kind != "corrupt":
                        name = root + "/extra.txt"
                        if kind == "traversal":
                            name = root + "/../escape.txt"
                        elif kind == "duplicate":
                            name = originals[0][0].name
                        extra = tarfile.TarInfo(name)
                        if kind == "link":
                            extra.type = tarfile.SYMTYPE
                            extra.linkname = "../../escape"
                        bundle.addfile(extra, io.BytesIO(b""))
                with self.assertRaises(ValueError):
                    verify(bad)

    # 日期：2026-11-25；生产提取入口在本地源码模式成功提取，任何网络请求均视为测试失败。
    def test_dependency_extract_without_network(self):
        work = self.root / "extract"
        work.mkdir()
        with patch.dict(os.environ, {"DUKTO_SOURCE_ARCHIVES": str(self.cache)}), \
                patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
            extracted = extract(self.entry, work)
        self.assertEqual((extracted / "说明.txt").read_bytes(), "原始依赖\n".encode("utf-8"))

    # 日期：2026-11-25；本地源码缺失或摘要错误立即失败，不允许隐式回退网络或提取损坏归档。
    def test_dependency_missing_or_corrupt_refused(self):
        for kind in ("missing", "corrupt"):
            with self.subTest(kind=kind):
                cache = self.root / kind
                cache.mkdir()
                if kind == "corrupt":
                    (cache / self.archive.name).write_bytes(b"damaged")
                work = self.root / (kind + "-work")
                work.mkdir()
                with patch.dict(os.environ, {"DUKTO_SOURCE_ARCHIVES": str(cache)}), \
                        patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
                    with self.assertRaises(ValueError):
                        extract(self.entry, work)
                self.assertFalse((work / self.entry["name"]).exists())


if __name__ == "__main__":
    unittest.main()
