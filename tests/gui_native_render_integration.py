"""日期：2026-11-05；强制原生平台插件运行完整 GUI，隔离配置并保留实际渲染截图。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import struct
import subprocess
import tempfile

from service_integration import free_port


# 日期：2026-11-05；原生插件必须与宿主系统匹配，不接受离屏插件冒充 Cocoa/Windows/X11/Wayland。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--platform", required=True, choices=("windows", "cocoa", "xcb", "wayland"))
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    allowed = {"Windows": ("windows",), "Darwin": ("cocoa",), "Linux": ("xcb", "wayland")}
    assert args.platform in allowed.get(platform.system(), ()), "Native host/platform mismatch"
    executable = args.executable.resolve(strict=True)
    report = args.report.resolve()
    assert not report.exists() and not report.with_suffix(".png").exists()
    binary_sha = hashlib.sha256(executable.read_bytes()).hexdigest()
    environment = os.environ.copy()
    environment.update({"QT_QPA_PLATFORM": args.platform, "QT_QUICK_BACKEND": "software",
                        "QML_DISABLE_DISK_CACHE": "1"})
    with tempfile.TemporaryDirectory(prefix="dukto-native-render-") as temporary:
        root = Path(temporary) / "中文路径 with spaces"
        root.mkdir()
        screenshot = root / "desktop.png"
        result = subprocess.run([str(executable), "--self-test", "--data-directory", str(root / "state"),
                                 "--port", str(free_port()), "--screenshot", str(screenshot)],
                                cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30)
        assert result.returncode == 0 and not result.stdout and not result.stderr, (
            result.returncode, result.stdout, result.stderr)
        image = screenshot.read_bytes()
        assert 1000 < len(image) <= 8 * 1024**2
        assert image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR"
        width, height = struct.unpack(">II", image[16:24])
        # 日期：2026-11-05；允许 Retina/系统缩放的实际物理像素，逻辑窗口比例仍必须为430×700。
        assert 430 <= width <= 2580 and width * 700 == height * 430, (width, height)
        assert hashlib.sha256(executable.read_bytes()).hexdigest() == binary_sha
        report.parent.mkdir(parents=True, exist_ok=True)
        report.with_suffix(".png").write_bytes(image)
    report.write_text(json.dumps({"date": datetime.now(timezone.utc).isoformat(), "passed": True,
        "hostSystem": platform.system(), "hostMachine": platform.machine(),
        "forcedNativePlatform": args.platform, "binarySha256": binary_sha,
        "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "renderedPixels": [width, height], "renderedSha256": hashlib.sha256(image).hexdigest(),
        "workingPathUnicodeAndSpaces": True, "standardErrorEmpty": True,
        "scope": "actual complete GUI entrypoint and framebuffer under forced native platform; first-run view; full shell interaction/native choosers and packaged/clean-system qualification remain open"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
