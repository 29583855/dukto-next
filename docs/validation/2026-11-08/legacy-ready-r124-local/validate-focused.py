"""日期：2026-11-08；冻结最终输入并用双Windows真实CLI重复三轮原超时用例。"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


# 日期：2026-11-08；保留旧核心原件，确认仅注释发生变化，再构建最终候选并执行全部12条专项。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('toolchain', choices=['msvc', 'ucrt'])
    tag = parser.parse_args().toolchain
    root = Path.cwd()
    output = root / ('.cache/r124-focused-' + tag)
    output.mkdir(exist_ok=False)
    names = {row['path'] for row in json.loads((root / 'docs/ci-verification-20261108-r123.json').read_bytes())['qualificationInputs']}
    names |= {'tests/legacy_ready_integration.py', '.github/workflows/legacy-ready-regression.yml'}
    inputs = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sorted(names)}
    first = json.loads((root / ('.cache/r124-first-' + tag) / 'receipt.json').read_bytes())
    assert first['passed'] and first['inputs'] == first['inputsAfter']
    raw = (root / '.cache/r124-first-source-legacy.cpp').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == first['inputs']['src/core/legacy.cpp']
    old = 'Qt的零期限轮询在部分平台会先判过期；最终1ms轮询不重置无进展计时。'.encode()
    new = '报超时前最多再等待1ms接收就绪通知；没有读到正文时不重置无进展计时。'.encode()
    assert raw.replace(old, new) == (root / 'src/core/legacy.cpp').read_bytes()
    assert all(inputs[name] == sha for name, sha in first['inputs'].items() if name != 'src/core/legacy.cpp')
    build = root / ('build/windows' if tag == 'msvc' else 'build/windows-ucrt')
    binary = build / ('Release/dukto-cli.exe' if tag == 'msvc' else 'dukto-cli.exe')
    env = os.environ.copy()
    bins = ['.tools/Qt/5.15.2/msvc2019_64/bin', '.tools/openssl/Library/bin'] if tag == 'msvc' else ['.tools/msys64/ucrt64/bin']
    env['PATH'] = os.pathsep.join(str(root / name) for name in bins) + os.pathsep + env['PATH']
    with (output / 'build.log').open('xb') as log:
        result = subprocess.run([str(root / '.tools/python/Scripts/cmake.exe'), '--build', str(build), '--config', 'Release', '--target', 'dukto-cli', '--parallel', '3'], env=env, stdout=log, stderr=subprocess.STDOUT)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'toolchain': tag, 'inputs': inputs, 'buildExitCode': result.returncode, 'coreDeltaIsCommentOnly': True, 'passed': False, 'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        before = hashlib.sha256(binary.read_bytes()).hexdigest()
        with (output / 'driver.log').open('xb') as log:
            tested = subprocess.run([str(root / '.tools/python/Scripts/python.exe'), '-X', 'utf8', str(root / 'tests/legacy_ready_integration.py'), str(binary), '--rounds', '3', '--report', str(output / 'legacy-ready.json')], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=480)
        report = json.loads((output / 'legacy-ready.json').read_bytes())
        value.update(testExitCode=tested.returncode, binaryBefore=before, binaryAfter=hashlib.sha256(binary.read_bytes()).hexdigest(), cases=len(report['cases']))
        value['passed'] = tested.returncode == 0 and report['passed'] and value['binaryBefore'] == value['binaryAfter']
    value['inputsAfter'] = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in inputs}
    value['passed'] = value['passed'] and inputs == value['inputsAfter']
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({key:value.get(key) for key in ['toolchain','buildExitCode','testExitCode','cases','passed']}),flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
