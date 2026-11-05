"""日期：2026-11-05；真实主窗口服务器入口的原生平台与高DPI场景回归，剪贴板专项保持隔离。"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import traceback
import xml.etree.ElementTree as ET


# 日期：2026-11-05；固定QtTest程序身份，每个场景使用独立目录，原失败和截图不相互覆盖。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--platform", choices=("windows", "cocoa", "xcb", "wayland"), required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    executable = args.executable.resolve(strict=True)
    report_path = args.report.resolve()
    workspace = report_path.with_suffix("")
    assert not report_path.exists() and not workspace.exists()
    workspace.mkdir(parents=True)
    original = hashlib.sha256(executable.read_bytes()).hexdigest()
    report = {"date": datetime.now(timezone.utc).isoformat(), "passed": False,
              "sourceCommit": os.environ.get("GITHUB_SHA"), "executableSha256": original,
              "nativePlatform": args.platform, "cases": [],
              "scope": "production Main.qml loaded by compiled application controller fixture; real native server-entry click, compact/default layout, tabs, back/reopen and resize; high-DPI scenes use isolated offscreen; packaged GUI/native choosers and complete R6 remain separate"}
    try:
        for name, platform, scale in (("native", args.platform, "1"),
                                      ("offscreen-150", "offscreen", "1.5"),
                                      ("offscreen-200", "offscreen", "2")):
            working = workspace / name
            working.mkdir()
            env = os.environ.copy()
            if platform == "offscreen":
                env.pop("DUKTO_TEST_UI_PLATFORM", None)
            else:
                env["DUKTO_TEST_UI_PLATFORM"] = platform
            env["QT_SCALE_FACTOR"] = scale
            log, xml = working / "qt-test.log", working / "qt-test.xml"
            entry = {"name": name, "platform": platform, "scaleFactor": scale, "passed": False}
            report["cases"].append(entry)
            try:
                result = subprocess.run([str(executable), "serverEntryThroughMainQml",
                                         "-o", str(log) + ",txt", "-o", str(xml) + ",junitxml"],
                                        env=env, cwd=working, capture_output=True, timeout=60)
                entry.update(exitCode=result.returncode,
                             stdout=result.stdout.decode("utf-8", "replace")[-16384:],
                             stderr=result.stderr.decode("utf-8", "replace")[-16384:])
                assert result.returncode == 0 and not result.stderr, entry
                suite = ET.parse(xml).getroot()
                assert suite.tag == "testsuite" and suite.attrib["failures"] == "0" and suite.attrib["errors"] == "0"
                text = log.read_text(encoding="utf-8-sig")
                assert "QWARN" not in text and "QFATAL" not in text
                assert "serverEntryThroughMainQml(compact)" in text and "serverEntryThroughMainQml(default)" in text
                frames = []
                for size in ("360x560", "430x700"):
                    stem = working / "Testing/QtTest" / ("main-server-" + size)
                    geometry = json.loads(stem.with_suffix(".json").read_text(encoding="utf-8"))
                    assert geometry["platform"] == platform and geometry["popupInstances"] == 1, geometry
                    assert geometry["chineseGlyphCoverage"]["passed"] and geometry["chineseGlyphCoverage"]["missingGlyphs"] == 0, geometry
                    ratio = geometry["devicePixelRatio"]
                    assert ratio > 0 and (platform != "offscreen" or abs(ratio - float(scale)) < 0.01), geometry
                    assert all(abs(pixel - logical * ratio) <= 1 for pixel, logical in
                               zip(geometry["pixels"], geometry["logicalSize"])), geometry
                    png = stem.with_suffix(".png").read_bytes()
                    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
                    geometry.update(pngSha256=hashlib.sha256(png).hexdigest())
                    frames.append(geometry)
                entry.update(passed=True, frames=frames)
            except (AssertionError, OSError, subprocess.TimeoutExpired, ET.ParseError, ValueError, KeyError) as error:
                entry["error"] = traceback.format_exc(limit=5)[-16384:]
        assert hashlib.sha256(executable.read_bytes()).hexdigest() == original
        report["binaryUnchanged"] = True
        report["passed"] = len(report["cases"]) == 3 and all(item["passed"] for item in report["cases"])
    finally:
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "cases": report["cases"]}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
