"""日期：2026-11-08；原生验证持久域和多根关联，底层通过不代替生产总配额验收。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-08；每个真实方法必须通过，禁止跳过、警告及未知诊断，保留原始XML和文本。
def verify_xml(path):
    tree = ET.fromstring(path.read_bytes())
    expected = {'initTestCase', 'persistentCoordinatorAndReservedNames', 'multipleRootsAndAliases',
                'foreignDomainAndUnregisteredRoot', 'copiedMarkersAndCoordinatorAreRejected',
                'retiredRegistrationAndCorruption', 'coordinatorMutationInvalidatesExistingDomain',
                'admissionPrecedesMarkerCreation', 'processMaintenanceAndReopen',
                'exitBeforeMarkerRetainsCharge', 'threadsShareOneDomain', 'cleanupTestCase'}
    methods = tree.findall('TestFunction')
    assert tree.tag == 'TestCase' and len(methods) == len(expected)
    assert {method.get('name') for method in methods} == expected
    assert not tree.findall('.//Message')
    for method in methods:
        incidents = method.findall('Incident')
        assert len(incidents) == 1 and incidents[0].get('type') == 'pass', method.get('name')
    return {'methodsPassed': len(methods), 'rowsPassed': len(methods), 'skipped': 0, 'warnings': 0,
            'markerBytes': 256, 'rootBindingFoundationQualified': True}


# 日期：2026-11-08；流式读取执行程序及源码摘要，不缓存整个二进制或随源文件大小增加内存。
def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


# 日期：2026-11-08；冻结精确源码、CLI和测试程序，真实进程退出和原件核对通过后才登记专项成功。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--build', type=Path, required=True)
    parser.add_argument('--configuration', default='Release')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent.parent
    build = args.build.resolve()
    output = build / 'state-domain-regression'
    output.mkdir(exist_ok=False)
    directory = build / args.configuration if os.name == 'nt' else build
    suffix = '.exe' if os.name == 'nt' else ''
    binaries = [directory / (name + suffix) for name in ['dukto-cli', 'state-domain-tests']]

    # 日期：2026-11-08；输入增删也视为身份变化，全部维护构建/资格输入参与冻结。
    def sources():
        paths = [root / 'CMakeLists.txt']
        for folder in ['src', 'tests', 'scripts', 'third-party/sqlite-runtime', '.github/workflows']:
            paths.extend(path for path in (root / folder).rglob('*')
                         if path.is_file() and '__pycache__' not in path.parts)
        return {path.relative_to(root).as_posix(): digest(path) for path in sorted(paths)}

    before = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    inputs = sources()
    source = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root).decode().strip()
    command = [str(binaries[1]), '-o', str(output / 'state-domain-tests.log') + ',txt',
               '-o', str(output / 'state-domain-tests.xml') + ',xml',
               '-o', str(output / 'state-domain-tests-junit.xml') + ',junitxml']
    with (output / 'driver.log').open('xb') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=180)
    after = {path.relative_to(build).as_posix(): digest(path) for path in binaries}
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'system': platform.platform(), 'architecture': platform.machine(), 'testExitCode': result.returncode,
             'binaryBefore': before, 'binaryAfter': after, 'binaryUnchanged': before == after,
             'sourceInputs': inputs, 'sourceInputsUnchanged': inputs == sources(), 'passed': False,
             'completeCoreQualified': False, 'productionRootsIntegrated': False,
             'globalQuotaEnforced': False, 'automaticGcImplemented': False,
             'deliveryComplete': False, 'releaseQualified': False}
    if result.returncode == 0:
        try:
            value.update(verify_xml(output / 'state-domain-tests.xml'))
            value['passed'] = value['binaryUnchanged'] and value['sourceInputsUnchanged']
        except (AssertionError, ET.ParseError) as error:
            value['verificationError'] = str(error)
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: value.get(key) for key in ['sourceCommit', 'architecture', 'testExitCode',
                                                    'rowsPassed', 'binaryUnchanged', 'sourceInputsUnchanged', 'passed']}))
    raise SystemExit(0 if value['passed'] else 1)


if __name__ == '__main__':
    main()
