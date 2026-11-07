"""日期：2026-11-08；独立验收旧失败作业中完整通过的子集，保持失败job及原报告不变。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'


# 日期：2026-11-08；按原提交脚本及逐报告摘要验证Windows51协议项，不改变其核心失败结论。
def previous_windows():
    folder = REPO / 'docs/validation/2026-11-07/sqlite-vfs-r119-native-terminal/windows-2022'
    original = json.loads((folder / 'receipt.json').read_bytes())
    assert original['conclusion'] == 'failure' and not original['qualified']
    failed = [step['name'] for step in original['steps'] if step['conclusion'] == 'failure']
    assert failed == ['Core and GUI controller tests']
    helper = runpy.run_path(str(ROOT / '.cache/collect-exact-native-r87.py'))
    proof = helper['protocol'](folder / 'build/protocol-suite.json', original['sourceCommit'])
    assert proof['passed'] and proof['cases'] == 51
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': original['sourceCommit'],
             'jobId': original['jobId'], 'jobConclusion': 'failure', 'completeJobQualified': False,
             'windowsProtocolSubsetQualified': True, 'protocolSubset': proof,
             'originalCoreFailureRetained': True, 'failedSteps': failed,
             'deliveryComplete': False, 'releaseQualified': False}
    (folder / 'verified-protocol-subset.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return {'r119WindowsProtocolCasesVerified': 51, 'r119WindowsCompleteJobQualified': False}


# 日期：2026-11-08；核对环境准备缺失作业中新文件观察专项的原始11条，不授予整个核心集资格。
def first_regression():
    folder = REPO / 'docs/validation/2026-11-08/sqlite-file-info-r120-native'
    original = json.loads((folder / 'receipt.json').read_bytes())
    helper = runpy.run_path(str(ROOT / '.cache/collect-r120-fixed-file-info-native.py'))
    expected = helper['input_hashes'](original['sourceCommit'])
    records = []
    for runner in ['windows-2022', 'ubuntu-22.04', 'macos-15', 'macos-15-intel']:
        base = folder / runner
        result = json.loads((base / 'sqlite-file-info-regression/receipt.json').read_bytes())
        assert result['sourceCommit'] == original['sourceCommit']
        assert result['binaryUnchanged'] and result['binaryBefore'] == result['binaryAfter']
        assert result['sourceInputsUnchanged'] and set(result['sourceInputs']) == set(expected)
        for name, actual in result['sourceInputs'].items():
            choices = expected[name]
            if runner != 'windows-2022':
                source = subprocess.check_output(['git', 'show', original['sourceCommit'] + ':' + name], cwd=REPO)
                choices = {hashlib.sha256(source).hexdigest()}
            assert actual in choices, (runner, name)
        target = base / 'Testing/QtTest/sqlite-file-info-tests.xml'
        tree = ET.fromstring(target.read_bytes())
        assert tree.get('failures') == tree.get('errors') == '0'
        cases = tree.findall('testcase')
        assert len(cases) == 11 and all(case.get('result') == 'pass' for case in cases)
        assert not tree.findall('.//failure') and not tree.findall('.//skipped')
        records.append({'runner': runner, 'fileInfoRowsPassed': 11, 'fileInfoSkipped': 0,
                        'xmlPath': target.relative_to(REPO).as_posix(),
                        'xmlSha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                        'ctestExitCode': result['ctestExitCode'], 'completeCoreQualified': runner == 'windows-2022'})
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': original['sourceCommit'],
             'originalRun': original['run'], 'records': records, 'allFourFileInfoSubsetsQualified': True,
             'failedCompleteCoreResultsRetained': True, 'completeRunQualified': False,
             'globalQuotaEnforced': False, 'deliveryComplete': False, 'releaseQualified': False}
    (folder / 'verified-file-info-subsets.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return {'r120InitialFileInfoSubsetsEach': 11, 'r120InitialCompleteRunQualified': False}


# 日期：2026-11-08；仅发布独立核对的结论，不重新运行或覆盖旧产品测试。
def main():
    print(json.dumps({**previous_windows(), **first_regression()}), flush=True)


if __name__ == '__main__':
    main()
