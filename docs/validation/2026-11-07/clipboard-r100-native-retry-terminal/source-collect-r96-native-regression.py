"""日期：2026-11-07；保留R96双Mac终态原件，分别核验原测试和显式Darwin边界。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import xml.etree.ElementTree as ET

COMMIT = '88f33b2c83f2950307c362fb64c693f7e9e5929d'
TAG = 'exclusive-first-ipv4-wildcard-then-specific'


# 日期：2026-11-07；逐条保留原FAIL/XPASS及XFAIL行，不能用进程退出码代替边界核验。
def inspect_qt(path, proof):
    text = path.read_text('utf-8')
    lines = text.splitlines()
    expected = [line for line in lines if line.startswith('XFAIL  :')]
    unexpected = [line for line in lines if line.startswith(('FAIL!  :', 'XPASS  :', 'QFATAL :'))]
    return {'log': proof(path), 'expectedFailureLines': expected,
            'unexpectedFailureLines': unexpected,
            'explicitBoundaryExactlyOnce': len(expected) == 1 and
            expected[0].startswith('XFAIL  : CoreTests::exclusiveTcpBinding(' + TAG + ')'),
            'exclusiveBindingPassLines': sum(line.startswith('PASS   : CoreTests::exclusiveTcpBinding(') for line in lines),
            'gracefulRestartPassRows': sum(line.startswith('PASS   : CoreTests::tcpGracefulRestart(') for line in lines),
            'addressFamiliesPassed': 'PASS   : CoreTests::tcpAddressFamilies()' in text}


# 日期：2026-11-07；下载可复用逐摘要相同的只读原件；回执只创建一次，失败终态始终保留。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', type=int, required=True)
    args = parser.parse_args()
    api = runpy.run_path('.cache/github-actions-r28.py')
    request, base = api['request'], '/repos/29583855/dukto-next'
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    run = request(base + '/actions/runs/' + str(args.run))
    assert run['head_sha'] == COMMIT and run['status'] == 'completed'
    assert run['path'] == '.github/workflows/macos-listener-regression.yml'
    jobs = request(base + '/actions/runs/' + str(args.run) + '/jobs?per_page=100')['jobs']
    assert len(jobs) == 2 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/' + str(args.run) + '/artifacts?per_page=100')['artifacts']
    assert {item['name'] for item in artifacts} == {
        'macos-listener-regression-macos-15', 'macos-listener-regression-macos-15-intel'}
    output = Path('docs/validation/2026-11-07/boundary-r96-native-regression-terminal')
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / 'receipt.json').exists()
    records = []
    for item in artifacts:
        archive = output / (item['name'] + '.zip')
        if archive.exists():
            raw = archive.read_bytes()
        else:
            raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
            archive.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        folder = output / item['name']
        if not folder.exists():
            helper['extract'](raw, folder)
        evidence = folder / 'evidence'
        assert (evidence / 'source-commit.txt').read_text('utf-8').strip() == COMMIT
        environment = (evidence / 'environment.log').read_text('utf-8')
        architecture = 'x86_64' if item['name'].endswith('-intel') else 'arm64'
        assert re.search('^' + architecture + '$', environment, re.M)
        xmls = sorted((folder / 'build/Testing/QtTest').glob('*.xml'))
        failures = []
        for path in xmls:
            for row in ET.parse(path).findall('.//testcase'):
                for child in row.findall('failure') + row.findall('error'):
                    failures.append({'report': helper['proof'](path), 'method': row.get('name'),
                                     'details': child.attrib})
        core = inspect_qt(folder / 'build/Testing/QtTest/core-tests.log', helper['proof'])
        focused = [dict(inspect_qt(evidence / ('core-' + str(number) + '.log'), helper['proof']),
                        attempt=number) for number in range(1, 6)]
        exit_rows = (evidence / 'core-exit-codes.txt').read_text('utf-8').splitlines()
        parallel = json.loads((evidence / 'parallel-exit/report.json').read_text('utf-8'))
        ctest = (evidence / 'ctest.log').read_text('utf-8')
        all_core_passed = (len(xmls) == 22 and not failures and
                           bool(re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$', ctest, re.M)))
        all_boundary_verified = all(row['explicitBoundaryExactlyOnce'] and
                                    not row['unexpectedFailureLines'] and
                                    row['gracefulRestartPassRows'] == 3 and row['addressFamiliesPassed']
                                    for row in [core, *focused])
        all_exit_passed = (exit_rows == [str(i) + ' 0' for i in range(1, 6)] and
                           parallel['completed'] and parallel['passed'] and
                           len(parallel['cases']) == 10 and all(row['passed'] for row in parallel['cases']))
        records.append({'name': item['name'], 'id': item['id'], 'sha256': digest,
                        'architecture': architecture, 'coreQtReports': [helper['proof'](p) for p in xmls],
                        'all23CoreTargetsPassed': all_core_passed, 'unexpectedXmlFailures': failures,
                        'core': core, 'focused': focused, 'allSixExplicitBoundariesVerified': all_boundary_verified,
                        'focusedExitCodes': exit_rows, 'parallelExitPassed': parallel['passed'],
                        'parallelExitReport': helper['proof'](evidence / 'parallel-exit/report.json'),
                        'allFocusedAndOriginalExitPassed': all_exit_passed})
    qualified = all(item['all23CoreTargetsPassed'] and item['allSixExplicitBoundariesVerified'] and
                    item['allFocusedAndOriginalExitPassed'] for item in records)
    if run['conclusion'] == 'success':
        assert qualified
        assert all(job['conclusion'] == 'success' for job in jobs)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'jobs': [{key: job[key] for key in ('id', 'name', 'status', 'conclusion')} for job in jobs],
             'artifacts': records, 'allOriginalArtifactsVerified': True,
             'nativeListenerRegressionQualifiedWithExplicitBoundary': qualified,
             'expectedFailuresPerArchitecture': 6, 'kernelExternalPortExclusivityQualified': False,
             'parallelExitRootCauseProven': False, 'fullProtocolQualified': False,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'originalRunConclusion': run['conclusion'], 'architectures': len(records),
                      'nativeRegressionQualifiedWithExplicitBoundary': qualified}), flush=True)


if __name__ == '__main__':
    main()
