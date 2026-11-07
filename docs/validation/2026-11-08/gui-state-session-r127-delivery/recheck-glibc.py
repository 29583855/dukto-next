"""日期：2026-11-08；修正首次独立驱动的工作目录，保留原5通过/3截图保存失败。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-08；使用原生CTest相同构建工作目录重跑，源和执行程序均不修改或重编译。
def main():
    root = Path.cwd()
    prior = root / '.cache/r127-glibc'
    failed = json.loads((prior / 'receipt.json').read_bytes())
    assert not failed['passed'] and failed['driverExitCode'] == 3
    old_xml = ET.fromstring((prior / 'results/server-panel-tests.xml').read_bytes())
    failures = [item for item in old_xml.findall('TestFunction') if any(x.get('type') == 'fail' for x in item.findall('Incident'))]
    assert len(failures) == 3 and all('save(' in item.find('Incident/Description').text for item in failures)
    ssh = runpy.run_path(str(root / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    output = root / '.cache/r127-glibc-recheck'
    output.mkdir(exist_ok=False)
    program = '''set -eu
cd /home/dukto/gui-state-r127
mkdir results-recheck
cd build
mkdir -p Testing/QtTest
sha256sum dukto-cli server-panel-tests > ../results-recheck/before.sha256
set +e
QT_QPA_PLATFORM=offscreen ./server-panel-tests -o ../results-recheck/server-panel-tests.log,txt -o ../results-recheck/server-panel-tests.xml,xml -o ../results-recheck/server-panel-tests-junit.xml,junitxml > ../results-recheck/test-driver.log 2>&1
code=$?
printf '%s\\n' "$code" > ../results-recheck/test-exit.txt
sha256sum dukto-cli server-panel-tests > ../results-recheck/after.sha256
exit "$code"
'''
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(ssh + ['sh -s'], input=program.encode('utf-8'), stdout=log,
                                stderr=subprocess.STDOUT, timeout=600)
    archive = output / 'results.tar.gz'
    with archive.open('xb') as destination:
        subprocess.run(ssh + ['cd /home/dukto/gui-state-r127 && tar czf - results-recheck'],
                       stdout=destination, check=True, timeout=60)
    runpy.run_path(str(root / '.cache/validate-r121-glibc-qualified.py'))['extract'](archive, output)
    code = '''import hashlib,json
from pathlib import Path
root=Path('/home/dukto/gui-state-r127')
manifest=json.loads((root/'.dukto-source-snapshot.json').read_bytes())['files']
actual={n:{'bytes':(root/n).stat().st_size,'sha256':hashlib.sha256((root/n).read_bytes()).hexdigest()} for n in manifest}
assert actual==manifest
assert '-std=c++14' in (root/'build/build.ninja').read_text()
print(json.dumps({'files':actual,'cpp14BuildFlagPresent':True}))
'''
    installed = subprocess.run(ssh + ['python3 -'], input=code.encode('utf-8'), capture_output=True, timeout=60)
    assert installed.returncode == 0
    actual = json.loads(installed.stdout)
    assert actual['files'] == json.loads((prior / 'installed-source.json').read_bytes())['files']
    (output / 'installed-source.json').write_bytes(installed.stdout)
    before = (output / 'results-recheck/before.sha256').read_bytes()
    assert before == (output / 'results-recheck/after.sha256').read_bytes()
    assert before.split()[::2] == (prior / 'results/before.sha256').read_bytes().split()[::2]
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'driverExitCode': result.returncode,
             'allInstalledSourceInputsUnchanged': True, 'actualSourceFileCount': len(actual['files']),
             'cpp14BuildFlagPresent': True, 'sameOriginalBinariesUnchanged': True,
             'originalFailureRetained': True, 'originalPassed': 5, 'originalScreenshotSaveFailures': 3,
             'testWorkingDirectoryCorrected': True, 'passed': False,
             'fullCoreQualified': False, 'globalQuotaEnforced': False,
             'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        tree = ET.fromstring((output / 'results-recheck/server-panel-tests.xml').read_bytes())
        methods = tree.findall('TestFunction')
        assert tree.tag == 'TestCase' and tree.get('name') == 'ServerPanelTests'
        assert len(methods) == 8 and not tree.findall('.//Message')
        for method in methods:
            incidents = method.findall('Incident')
            assert len(incidents) == 1 and incidents[0].get('type') == 'pass'
        value.update(passed=True, methodsPassed=8, rowsPassed=8, warnings=0, skipped=0)
    (output / 'receipt.json').write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
