"""日期：2026-11-05；复现归档旧 mtime 和头文件内容变化，验证增量同步及摘要/路径拒绝行为。"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import subprocess
import tarfile
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_snapshot import RECEIPT, create, install
from package_windows import source_archive


# 日期：2026-11-05；失败快照必须在任何目标变更前拒绝，保留原内容和已有同步凭据。
def refused(destination, archive, original):
    try:
        install(destination, archive)
    except (ValueError, KeyError):
        pass
    else:
        raise AssertionError("Invalid snapshot was accepted")
    assert (destination / "src/api.h").read_bytes() == original


# 日期：2026-11-05；不运行外部编译器，用真实文件时间重现 Ninja 错过旧时间戳输入的必要前提。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="dukto-source-snapshot-") as temporary:
        root = Path(temporary)
        source, destination = root / "source", root / "destination"
        (source / "src").mkdir(parents=True)
        (source / "ui").mkdir()
        (source / "Dukto").mkdir()
        (source / "docs/validation").mkdir(parents=True)
        (source / "CMakeLists.txt").write_bytes(b"project(DuktoNext)\n")
        (source / ".gitattributes").write_bytes(b"third-party/sqlite-runtime/** -text\n")
        header = source / "src/api.h"
        header.write_bytes(b"int version();\n")
        (source / "ui/ServerPage.qml").write_bytes(b"Rectangle {\r\n}\r\n")
        (source / "Dukto/dukto.exe").write_bytes(b"reference")
        (source / "docs/validation/private.json").write_bytes(b"test states are excluded")
        vendor = source / "third-party/sqlite-runtime"
        (vendor / "qt-5.15.2").mkdir(parents=True)
        vendor_files = {"qt-5.15.2/qsql_sqlite.cpp": b"upstream bytes\r\n",
                        "sqlite-amalgamation-3530400.zip": b"fixed dependency archive\x00",
                        "LICENSE.LGPL3": b"dependency license\n"}
        for name, data in vendor_files.items():
            (vendor / name).write_bytes(data)
        (source / "third-party/private").mkdir()
        (source / "third-party/private/secret.zip").write_bytes(b"must remain excluded")
        destination.mkdir()
        (destination / "build").mkdir()
        object_file = destination / "build/old.obj"
        object_file.write_bytes(b"object")
        old_stamp = time.time_ns() - 60_000_000_000
        os.utime(object_file, ns=(old_stamp, old_stamp))
        archive = root / "first.tar.gz"
        first = create(source, archive)
        assert first["files"] == 4 + len(vendor_files)
        result = install(destination, archive)
        assert len(result["updated"]) == 4 + len(vendor_files)
        assert (destination / "src/api.h").stat().st_mtime_ns > object_file.stat().st_mtime_ns
        assert (destination / "ui/ServerPage.qml").read_bytes() == b"Rectangle {\r\n}\r\n"
        assert not (destination / "Dukto").exists() and not (destination / "docs/validation").exists()
        for name, data in vendor_files.items():
            assert (destination / "third-party/sqlite-runtime" / name).read_bytes() == data
        assert not (destination / "third-party/private").exists()

        # 日期：2026-11-07；真实Git强制autocrlf=true检出，Qt原件/二进制依赖仍逐字节保持。
        checkout = root / "git-checkout"
        commands = [["git", "init", "-q", str(source)],
                    ["git", "-C", str(source), "config", "core.autocrlf", "true"],
                    ["git", "-C", str(source), "add", ".gitattributes", "third-party/sqlite-runtime"],
                    ["git", "-C", str(source), "checkout-index", "--all",
                     "--prefix=" + checkout.as_posix() + "/"]]
        for command in commands:
            result = subprocess.run(command, capture_output=True, timeout=30)
            assert result.returncode == 0, result.stderr
        for name, data in vendor_files.items():
            assert (checkout / "third-party/sqlite-runtime" / name).read_bytes() == data

        assert install(destination, archive)["updated"] == []
        header.write_bytes(b"long version();\n")
        os.utime(header, ns=(0, 0))
        newer = root / "second.tar.gz"
        create(source, newer)
        second = install(destination, newer)
        assert second["updated"] == ["src/api.h"]
        assert (destination / "src/api.h").stat().st_mtime_ns > object_file.stat().st_mtime_ns
        assert (destination / "src/api.h").read_bytes() == header.read_bytes()
        poisoned = root / "bad-digest.tar.gz"
        with tarfile.open(newer) as original, tarfile.open(poisoned, "w:gz") as output:
            for member in original.getmembers():
                raw = original.extractfile(member).read()
                if member.name == "third-party/sqlite-runtime/sqlite-amalgamation-3530400.zip":
                    raw = b"changed dependency bytes\n"
                member.size = len(raw)
                output.addfile(member, io.BytesIO(raw))
        refused(destination, poisoned, header.read_bytes())
        outside = root / "outside.tar.gz"
        with tarfile.open(outside, "w:gz") as output:
            member = tarfile.TarInfo("../outside.cpp")
            member.size = 1
            output.addfile(member, io.BytesIO(b"x"))
        refused(destination, outside, header.read_bytes())
        assert not (root / "outside.cpp").exists()
        receipt = (destination / RECEIPT).read_bytes()
        future = time.time_ns() + 60_000_000_000
        os.utime(object_file, ns=(future, future))
        refused(destination, newer, header.read_bytes())
        assert (destination / RECEIPT).read_bytes() == receipt
        manifest = json.loads(receipt)
        assert manifest["files"]["src/api.h"]["sha256"] == hashlib.sha256(header.read_bytes()).hexdigest()
        # 日期：2026-11-07；三平台打包共用对应源码函数，逐字节验证真实固定依赖及许可完整进入ZIP。
        project = Path(__file__).resolve().parents[1]
        packaged = root / "application-source.zip"
        listing = source_archive(project, packaged)
        indexed = {row["path"]: row["sha256"] for row in listing}
        actual_vendor = project / "third-party/sqlite-runtime"
        originals = [path for path in actual_vendor.rglob("*") if path.is_file()]
        assert len(originals) >= 7
        with zipfile.ZipFile(packaged) as compressed:
            assert len(compressed.namelist()) == len(indexed)
            assert compressed.read(".gitattributes") == (project / ".gitattributes").read_bytes()
            for path in originals:
                name = path.relative_to(project).as_posix()
                assert compressed.read(name) == path.read_bytes()
                assert indexed[name] == hashlib.sha256(path.read_bytes()).hexdigest()
            assert not any(name.startswith("third-party/") and
                           not name.startswith("third-party/sqlite-runtime/") for name in compressed.namelist())
    report = {"date": "2026-11-07", "passed": True, "checks": ["old archive mtime refreshed", "changed header recopied",
              "identical input untouched", "CRLF bytes preserved", "reference and validation excluded", "bad digest refused before writes",
              "path traversal refused", "future build artifacts require clean",
              "vendor bytes included", "Git autocrlf checkout preserves vendor bytes", "unrelated third-party excluded", "tampered dependency refused before writes",
              "all three packages share verified corresponding-source archiver"]}
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Source snapshot validation passed")


if __name__ == "__main__":
    main()
