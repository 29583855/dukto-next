"""日期：2026-11-06；双Windows完整编译/CTest及文本相关业务回归，独立新目录保留全部原件。"""
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import time

ROOT = Path.cwd()
OUT = ROOT / 'docs/validation/2026-11-06/legacy-text-r93-windows'
ENV = runpy.run_path('.cache/validate-overwrite-r62.py')['environment']


# 日期：2026-11-06；每个专项保留原报告和失败退出码，不以子项通过覆盖总失败。
def protocols(label):
    folder = OUT / label
    binary = ROOT / ('build/windows-ucrt/dukto-cli.exe' if label == 'ucrt' else 'build/windows/Release/dukto-cli.exe')
    cases = [('legacy-text-credit', 'legacy_text_credit_integration', []),
             ('legacy', 'legacy_integration', []), ('legacy-timeout', 'legacy_timeout_integration', []),
             ('cli', 'cli_contracts', []), ('service', 'service_integration', []),
             ('transfer', 'transfer_integration', ['--threads', '16']),
             ('conflict-skip', 'conflict_skip_integration', []),
             ('conflict-overwrite', 'conflict_overwrite_integration', []),
             ('parallel-recovery', 'transfer_recovery_integration', ['--threads', '4', '--resume-threads', '8',
                '--files', '4', '--payload-mib', '8', '--checkpoint-percent', '50'])]
    results = []
    for name, script, extra in cases:
        report = folder / (name + '.json')
        assert not report.exists()
        started = time.monotonic()
        with (folder / (name + '.log')).open('xb') as log:
            process = subprocess.run([sys.executable, '-X', 'utf8', 'tests/' + script + '.py', str(binary),
                                      *extra, '--report', str(report)], env=ENV(label), stdout=log, stderr=subprocess.STDOUT)
        value = json.loads(report.read_text('utf-8')) if report.is_file() else None
        passed = process.returncode == 0 and (value.get('passed', True) if isinstance(value, dict) else bool(value))
        results.append({'name': name, 'exitCode': process.returncode, 'passed': passed,
                        'seconds': round(time.monotonic()-started, 3),
                        'reportSha256': hashlib.sha256(report.read_bytes()).hexdigest() if report.is_file() else None})
        (folder / 'protocol-summary.json').write_text(json.dumps({'cases': results, 'completed': len(results)==len(cases),
                'passed': all(row['passed'] for row in results)}, indent=2)+'\n', 'utf-8')
        print(json.dumps({'toolchain': label, **results[-1]}), flush=True)
    return 0 if all(row['passed'] for row in results) else 1


# 日期：2026-11-06；核心回归串行避免发现端口干扰，随后各工具链的独立协议并行运行。
def main():
    if len(sys.argv)>1:
        return protocols(sys.argv[1])
    OUT.mkdir(exist_ok=False)
    results=[]
    for label, folder, cmake, ctest, extra in [
        ('ucrt','windows-ucrt','.tools/msys64/ucrt64/bin/cmake.exe','.tools/msys64/ucrt64/bin/ctest.exe',[]),
        ('msvc','windows','.tools/python/Scripts/cmake.exe','.tools/python/Scripts/ctest.exe',['-C','Release'])]:
        destination=OUT/label;destination.mkdir()
        with (destination/'build.log').open('xb') as log:
            build=subprocess.run([str(ROOT/cmake),'--build',str(ROOT/'build'/folder),'--config','Release','--parallel','2'],
                     env=ENV(label),stdout=log,stderr=subprocess.STDOUT)
        assert build.returncode==0,(label,build.returncode)
        with (destination/'ctest.log').open('xb') as log:
            result=subprocess.run([str(ROOT/ctest),'--test-dir',str(ROOT/'build'/folder),*extra,'--output-on-failure'],
                         env=ENV(label),stdout=log,stderr=subprocess.STDOUT)
        shutil.copyfile(ROOT/'build'/folder/'Testing/Temporary/LastTest.log',destination/'LastTest.log')
        shutil.copytree(ROOT/'build'/folder/'Testing/QtTest',destination/'QtTest')
        results.append({'toolchain':label,'exitCode':result.returncode})
        print(json.dumps(results[-1]),flush=True)
    (OUT/'core-summary.json').write_text(json.dumps({'cases':results,'passed':all(row['exitCode']==0 for row in results)},indent=2)+'\n','utf-8')
    children=[subprocess.Popen([sys.executable,'-u',__file__,label]) for label in ['ucrt','msvc']]
    codes=[child.wait() for child in children]
    return 0 if not any(codes) and all(row['exitCode']==0 for row in results) else 1


if __name__=='__main__':
    raise SystemExit(main())
