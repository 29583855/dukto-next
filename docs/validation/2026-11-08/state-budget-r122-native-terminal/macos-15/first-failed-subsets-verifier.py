"""日期：2026-11-08；核验R122 ARM原失败的其余协议原件，保留超时失败，不授整轮通过。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
from types import SimpleNamespace


# 日期：2026-11-08；逐项匹配精确脚本、执行顺序及原摘要，失败必须保持原code/stage和业务断言。
def main():
    root = Path.cwd()
    repo = root / '.cache/github-29583855-dukto-next-r28'
    folder = repo / 'docs/validation/2026-11-08/state-budget-r122-native-terminal/macos-15'
    target = folder / 'verified-passed-subsets.json'
    assert not target.exists()
    receipt = json.loads((folder / 'receipt.json').read_bytes())
    source = receipt['sourceCommit']
    assert receipt['conclusion'] == 'failure' and not receipt['qualified']
    suite = json.loads((folder / 'build/protocol-suite.json').read_bytes())
    assert suite['completed'] and not suite['passed'] and suite['sourceCommit'] == source
    script = subprocess.check_output(['git', 'show', source + ':scripts/ci_protocol.py'], cwd=repo)
    assert hashlib.sha256(script).hexdigest() == suite['scriptSha256']
    namespace = {'__name__': 'exact_protocol'}
    exec(compile(script, 'exact_protocol', 'exec'), namespace)
    namespace['commands'].__globals__['sys'] = SimpleNamespace(platform=suite['platform'], executable='python')
    expected = [case[0] for case in namespace['commands'](Path('build'))]
    assert [case['name'] for case in suite['cases']] == expected and len(expected) == 47
    helper = runpy.run_path(str(root / '.cache/collect-exact-native-r87.py'))
    passed, failed = [], []
    for case in suite['cases']:
        report = folder / 'build' / Path(case['report'].replace('\\', '/')).name
        assert case['reportCreated']
        sha = hashlib.sha256(report.read_bytes()).hexdigest()
        assert sha == case['reportSha256']
        value = json.loads(report.read_bytes())
        if case['passed']:
            assert case['exitCode'] == 0 and value['passed']
            helper['verify_passed'](value)
            passed.append({'name': case['name'], 'report': report.name, 'sha256': sha})
        else:
            assert case['name'] == 'legacy-timeout' and case['exitCode'] == 1 and not value['passed']
            wrong, = [item for item in value['cases'] if not item['passed']]
            assert wrong['name'] == 'buffered-invalid-text' and wrong['expected'] == 6 and wrong['exitCode'] == 3
            assert wrong['lastEvent']['stage'] == 'transfer' and wrong['pausedSeconds'] == 6
            failed.append({'name': case['name'], 'report': report.name, 'sha256': sha, 'originalFailure': wrong})
    assert len(passed) == 46 and len(failed) == 1
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
             'jobId': receipt['jobId'], 'originalJobConclusion': 'failure', 'passedProtocolReports': passed,
             'failedProtocolReports': failed, 'completeNativeProtocolQualified': False,
             'failureRootCauseConfirmed': False, 'retryPerformed': False, 'deliveryComplete': False,
             'releaseQualified': False}
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), folder / 'failed-subsets-verifier.py')
    print(json.dumps({'passedReports': 46, 'failedReports': 1, 'originalConclusion': 'failure'}))


if __name__ == '__main__':
    main()
