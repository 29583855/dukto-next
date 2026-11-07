"""日期：2026-11-08；核验原生预算配置/真实CLI专项，固定四类额度不代替生产写入准入。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-08；全部实际方法及五个故障数据行必须通过，不接受跳过、警告或未知诊断。
def verify_xml(path):
    tree = ET.fromstring(path.read_bytes())
    expected = {'initTestCase', 'persistentLimitsAndUnchangedRecords', 'noOpAndStaleRevision',
                'refusalPreservesReservations', 'overdrawnCorrectionAnd64BitLimits',
                'configurationRecovery', 'corruptAndStaleConfigurationIntent',
                'processMaintenanceBoundary', 'directExitKeepsConfiguration',
                'realCliLifecycleAndRootBinding', 'realCliRefusalsHaveNoSideEffects', 'cleanupTestCase'}
    methods = tree.findall('TestFunction')
    assert tree.tag == 'TestCase' and {method.get('name') for method in methods} == expected
    assert len(methods) == len(expected) and not tree.findall('.//Message')
    rows = 0
    for method in methods:
        incidents = method.findall('Incident')
        assert len(incidents) == (5 if method.get('name') == 'configurationRecovery' else 1)
        assert all(incident.get('type') == 'pass' for incident in incidents)
        if method.get('name') == 'configurationRecovery':
            assert {incident.findtext('DataTag') for incident in incidents} == {str(n) for n in range(5)}
        rows += len(incidents)
    return {'methodsPassed': len(methods), 'rowsPassed': rows, 'warnings': 0, 'skipped': 0}


# 日期：2026-11-08；源码和执行文件分块计算摘要，不将完整二进制载入内存。
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


# 日期：2026-11-08；冻结全部维护构建输入和真实CLI/测试程序，官方原件同时保存文本和两种XML。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--configuration', default='Release')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    build = args.build.resolve()
    output = build / 'budget-configuration-regression'
    output.mkdir(exist_ok=False)
    directory = build / args.configuration if os.name == 'nt' else build
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = [directory / (name + suffix) for name in ['dukto-cli', 'budget-configuration-tests']]

    # 日期：2026-11-08；输入新增或删除也使身份失效，解释器缓存不参与维护源码。
    def sources():
        paths = [root / 'CMakeLists.txt']
        for folder in ['src', 'ui', 'resources', 'tests', 'scripts',
                       'third-party/sqlite-runtime', '.github/workflows']:
            paths.extend(path for path in (root / folder).rglob('*')
                         if path.is_file() and '__pycache__' not in path.parts)
        return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}

    before = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    inputs = sources()
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    command = [str(binaries[1]), '-o', str(output / 'budget-configuration-tests.log') + ',txt',
               '-o', str(output / 'budget-configuration-tests.xml') + ',xml',
               '-o', str(output / 'budget-configuration-tests-junit.xml') + ',junitxml']
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    after = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'system': platform.platform(), 'architecture': platform.machine(),
             'testExitCode': result.returncode, 'binaryBefore': before, 'binaryAfter': after,
             'binaryUnchanged': before == after, 'sourceInputs': inputs,
             'sourceInputsUnchanged': inputs == sources(), 'passed': False,
             'productionRootsIntegrated': False, 'globalQuotaEnforced': False,
             'completeCoreQualified': False, 'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        try:
            value.update(verify_xml(output / 'budget-configuration-tests.xml'))
            value['passed'] = value['binaryUnchanged'] and value['sourceInputsUnchanged']
        except (AssertionError, ET.ParseError) as error:
            value['verificationError'] = str(error)
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value.get(key) for key in ['testExitCode', 'rowsPassed', 'passed']}), flush=True)
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
