"""日期：2026-11-04；仅用于 Qt 5.15.2 早期 CI 探针，发布依赖仍须替换为受维护组合。"""

import hashlib
from pathlib import Path
import tarfile
import urllib.request


# 日期：2026-11-04；下载固定散列存档，验证后仅提取指定运行库，不执行安装脚本。
def main():
    destination = Path(__file__).resolve().parent.parent / ".tools/openssl"
    destination.mkdir(parents=True, exist_ok=True)
    archive = destination / "runtime.tar.bz2"
    with urllib.request.urlopen("https://repo.anaconda.com/pkgs/main/win-64/openssl-1.1.1w-h2bbff1b_0.tar.bz2", timeout=60) as response, archive.open("wb") as output:
        while block := response.read(256 * 1024):
            output.write(block)
    if hashlib.file_digest(archive.open("rb"), "sha256").hexdigest() != "0474e14823c734edc088bef98b829149a47ed8b4654f9638926c2fe4bbc40f38":
        raise RuntimeError("TLS archive SHA-256 mismatch")
    target = destination / "Library/bin"
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive) as package:
        for name in ["Library/bin/libssl-1_1-x64.dll", "Library/bin/libcrypto-1_1-x64.dll"]:
            member = package.getmember(name)
            if not member.isfile() or member.size > 16 * 1024**2:
                raise RuntimeError("invalid runtime member")
            with package.extractfile(member) as source, (target / Path(name).name).open("wb") as output:
                while block := source.read(256 * 1024):
                    output.write(block)
    archive.unlink()


if __name__ == "__main__":
    main()
