"""日期：2026-11-05；复现归档旧 mtime 和头文件内容变化，验证增量同步及摘要/路径拒绝行为。"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from source_snapshot import RECEIPT, create, install


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
        header = source / "src/api.h"
        header.write_bytes(b"int version();\n")
        (source / "ui/ServerPage.qml").write_bytes(b"Rectangle {\r\n}\r\n")
        (source / "Dukto/dukto.exe").write_bytes(b"reference")
        (source / "docs/validation/private.json").write_bytes(b"test states are excluded")
        destination.mkdir()
        (destination / "build").mkdir()
        object_file = destination / "build/old.obj"
        object_file.write_bytes(b"object")
        old_stamp = time.time_ns() - 60_000_000_000
        os.utime(object_file, ns=(old_stamp, old_stamp))
        archive = root / "first.tar.gz"
        first = create(source, archive)
        assert first["files"] == 3
        result = install(destination, archive)
        assert len(result["updated"]) == 3
        assert (destination / "src/api.h").stat().st_mtime_ns > object_file.stat().st_mtime_ns
        assert (destination / "ui/ServerPage.qml").read_bytes() == b"Rectangle {\r\n}\r\n"
        assert not (destination / "Dukto").exists() and not (destination / "docs/validation").exists()
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
                if member.name == "src/api.h":
                    raw = b"bad version();\n"
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
    report = {"date": "2026-11-05", "passed": True, "checks": ["old archive mtime refreshed", "changed header recopied",
              "identical input untouched", "CRLF bytes preserved", "reference and validation excluded", "bad digest refused before writes",
              "path traversal refused", "future build artifacts require clean"]}
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Source snapshot validation passed")


if __name__ == "__main__":
    main()
