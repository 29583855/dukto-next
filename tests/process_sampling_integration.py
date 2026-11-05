"""日期：2026-11-05；采样竞争适配的严格门槛及真实短命子进程验证。"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import psutil

import process_sampling


# 日期：2026-11-05；退出采样错误只有真实确认退出才可忽略，活动权限错误与超限指标必须失败。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    checks = []
    with subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"]) as child:
        try:
            for error in (psutil.AccessDenied(child.pid), psutil.NoSuchProcess(child.pid)):
                with patch.object(process_sampling, "metrics", side_effect=error):
                    try:
                        process_sampling.sample(child, {})
                        raise AssertionError("live process sampling error ignored")
                    except type(error):
                        assert child.poll() is None
                checks.append(type(error).__name__ + " active rejected")
            with patch.object(process_sampling, "metrics", return_value={"rss": 512 * 1024**2, "private": 1}):
                try:
                    process_sampling.sample(child, {})
                    raise RuntimeError("memory bound relaxed")
                except AssertionError:
                    checks.append("512MiB bound retained")
            inventory = process_sampling.thread_inventory(child, lambda _: [])
            if sys.platform != "win32":
                assert inventory and all(entry["id"] > 0 for entry in inventory)
                checks.append("real native thread inventory")
            measured = process_sampling.metrics(psutil.Process(child.pid))
            assert measured["rss"] > 0 and measured["private"] > 0 and measured["threads"] > 0
            checks.append("real child memory and thread sampling")
        finally:
            child.kill()
            child.wait(10)
        for error in (psutil.AccessDenied(child.pid), psutil.NoSuchProcess(child.pid)):
            with patch.object(process_sampling, "metrics", side_effect=error):
                process_sampling.sample(child, {})
            checks.append(type(error).__name__ + " exited ignored")
    for _ in range(50):
        with subprocess.Popen([sys.executable, "-c", "pass"]) as child:
            while child.poll() is None:
                process_sampling.sample(child, {})
            process_sampling.sample(child, {})
    path = Path(args.report)
    assert not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"date": "2026-11-05", "passed": True, "checks": checks,
        "shortLivedChildren": 50, "nativeMacOSVerified": sys.platform == "darwin",
        "privateMetric": "physical_footprint" if sys.platform == "darwin" else ("PrivateUsage" if sys.platform == "win32" else "USS")}, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
