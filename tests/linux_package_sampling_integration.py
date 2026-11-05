"""日期：2026-11-05；映射退出竞争仅在确认进程退出后可忽略，活动错误和模块来源仍严格拒绝。"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import psutil

from linux_package_integration import modules


# 日期：2026-11-05；真实短命进程配合受控映射采样，区分退出竞争、活动故障和非法依赖。
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', required=True)
    args = parser.parse_args()
    checks = []
    stage = Path('/dukto-module-sampling-boundary').resolve()
    with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(5)']) as child:
        try:
            with patch('linux_package_integration.psutil.Process') as target:
                target.return_value.memory_maps.return_value = []
                try:
                    modules(child, stage, set())
                except AssertionError as error:
                    assert str(error) == 'Active process has no shared-library mappings'
                    assert child.poll() is None
                    checks.append('empty-active-rejected')
                else:
                    raise RuntimeError('Active mapping failure was ignored')
                target.return_value.memory_maps.return_value = [
                    SimpleNamespace(path='/dukto-external-mapping/libQt5Core.so.5')]
                try:
                    modules(child, stage, set())
                except AssertionError as error:
                    assert error.args[0][0] == 'External dependency'
                    checks.append('external-Qt-dependency-rejected')
                else:
                    raise RuntimeError('External Qt dependency was ignored')
                target.return_value.memory_maps.return_value = [
                    SimpleNamespace(path='/dukto-module-sampling-boundary/libQt5Gui.so.5')]
                try:
                    modules(child, stage, set(), cli=True)
                except AssertionError:
                    checks.append('cli-graphical-dependency-rejected')
                else:
                    raise RuntimeError('CLI graphical dependency was ignored')
        finally:
            child.kill()
            child.wait(timeout=10)
        with patch('linux_package_integration.psutil.Process') as target:
            target.return_value.memory_maps.return_value = []
            try:
                modules(child, stage, set())
            except psutil.NoSuchProcess:
                assert child.poll() is not None
                checks.append('empty-exited-confirmed')
            else:
                raise RuntimeError('Exit race did not preserve explicit exited state')
    assert len(checks) == 4
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps({'date': '2026-11-05', 'passed': True, 'checks': checks}, indent=2) + '\n', encoding='utf-8')
    print('Module sampling exit/active/dependency boundaries passed')


if __name__ == '__main__':
    main()
