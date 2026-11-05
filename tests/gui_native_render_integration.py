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
        geometry_path = root / "geometry.json"
        result = subprocess.run([str(executable), "--self-test", "--data-directory", str(root / "state"),
                                 "--port", str(free_port()), "--screenshot", str(screenshot),
                                 "--render-report", str(geometry_path)],
                                cwd=root, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=30)
        report.parent.mkdir(parents=True, exist_ok=True)
        image = screenshot.read_bytes() if screenshot.is_file() else b""
        if image:
            report.with_suffix(".png").write_bytes(image)
        geometry = json.loads(geometry_path.read_text(encoding="utf-8")) if geometry_path.is_file() else {}
        report.write_text(json.dumps({"passed": False, "exitCode": result.returncode,
            "stdout": result.stdout.decode("utf-8", "replace")[:4096],
            "stderr": result.stderr.decode("utf-8", "replace")[:4096], "geometry": geometry},
            ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        assert result.returncode == 0 and not result.stdout and not result.stderr, (
            result.returncode, result.stdout, result.stderr)
        assert 1000 < len(image) <= 8 * 1024**2
        assert image[:8] == b"\x89PNG\r\n\x1a\n" and image[12:16] == b"IHDR"
        width, height = struct.unpack(">II", image[16:24])
        # 日期：2026-11-05；Cocoa 可把窗口收至屏幕可用高度，仍核对根布局、实际帧缓冲和原生缩放。
        assert geometry["platform"] == args.platform and geometry["requestedSize"] == [430, 700]
        logical_width, logical_height = geometry["logicalSize"]
        assert logical_width == 430 and 560 <= logical_height <= 700, geometry
        assert geometry["rootSize"] == geometry["logicalSize"], geometry
        scale = geometry["devicePixelRatio"]
        assert 0.75 <= scale <= 6 and geometry["renderedPixels"] == [width, height], geometry
        assert abs(width - logical_width * scale) <= 1 and abs(height - logical_height * scale) <= 1, geometry
        frame_width, frame_height = geometry["frameSize"]
        screen_width, screen_height = geometry["availableScreen"]
        assert frame_width <= screen_width + 1 and frame_height <= screen_height + 1, geometry
        if logical_height < 700:
            assert screen_height < 700 + frame_height - logical_height, geometry
        assert hashlib.sha256(executable.read_bytes()).hexdigest() == binary_sha
        report.parent.mkdir(parents=True, exist_ok=True)
        report.with_suffix(".png").write_bytes(image)
    report.write_text(json.dumps({"date": datetime.now(timezone.utc).isoformat(), "passed": True,
        "hostSystem": platform.system(), "hostMachine": platform.machine(),
        "forcedNativePlatform": args.platform, "binarySha256": binary_sha,
        "testScriptSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "geometry": geometry, "renderedPixels": [width, height], "renderedSha256": hashlib.sha256(image).hexdigest(),
        "workingPathUnicodeAndSpaces": True, "standardErrorEmpty": True,
        "scope": "actual complete GUI entrypoint and framebuffer under forced native platform; first-run view; full shell interaction/native choosers and packaged/clean-system qualification remain open"},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
