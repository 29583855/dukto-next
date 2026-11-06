"""日期：2026-11-07；精确收验R96完整原生或Alpine，Mac已知xfail须逐条披露。"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import xml.etree.ElementTree as ET

COMMIT = '88f33b2c83f2950307c362fb64c693f7e9e5929d'


# 日期：2026-11-07；只允许Mac核心精确已知方法的一条xfail，日志必须同时包含原数据行。
def verify_core(directory, helper, focused):
    ctest = directory / 'ctest.log'
    assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$', ctest.read_text('utf-8'), re.M)
    xmls = sorted((directory / 'Testing/QtTest').glob('*.xml'))
    assert len(xmls) == 22
    is_mac = directory.name.startswith('core-validation-macos-')
    expected = []
    for path in xmls:
        tree = ET.parse(path)
        assert not tree.findall('.//failure') and not tree.findall('.//error')
        for case in tree.findall('.//testcase'):
            if case.get('result') == 'xfail':
                assert is_mac and path.name == 'core-tests.xml' and case.get('name') == 'exclusiveTcpBinding'
                expected.append({'report': helper['proof'](path), 'method': case.get('name')})
            else:
                assert case.get('result') == 'pass', (path, case.attrib)
    assert len(expected) == (1 if is_mac else 0)
    core_log = directory / 'Testing/QtTest/core-tests.log'
    if is_mac:
        rows = focused['inspect_qt'](core_log, helper['proof'])
        assert rows['explicitBoundaryExactlyOnce'] and not rows['unexpectedFailureLines']
        assert rows['exclusiveBindingPassLines'] == 8 and rows['gracefulRestartPassRows'] == 3
    else:
        assert not any(line.startswith(('XFAIL  :', 'XPASS  :', 'FAIL!  :', 'QFATAL :'))
                       for line in core_log.read_text('utf-8').splitlines())
    return {'runner': directory.name, 'ctest': helper['proof'](ctest),
            'xmls': [helper['proof'](p) for p in xmls], 'expectedFailures': expected,
            'allOtherResultsPass': True, 'passed': True}


# 日期：2026-11-07；终态失败仍先保存附件，但只有完整原件全部通过才生成合格回执。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('kind', choices=('native', 'musl'))
    args = parser.parse_args()
    run_id = 42252931531 if args.kind == 'native' else 42253012733
    runners = 4 if args.kind == 'native' else 1
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    focused = runpy.run_path('.cache/collect-r96-native-regression.py')
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(run_id))
    assert run['head_sha'] == COMMIT and run['status'] == 'completed'
    jobs = request(base + '/actions/runs/' + str(run_id) + '/jobs?per_page=100')['jobs']
    assert len(jobs) == runners and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/' + str(run_id) + '/artifacts?per_page=100')['artifacts']
    output = Path('docs/validation/2026-11-07/boundary-r96-' + args.kind + '-terminal')
    output.mkdir(parents=True, exist_ok=True)
    assert not (output / 'receipt.json').exists()
    records = []
    for item in artifacts:
        if item['name'].startswith('macos-compiled-'):
            continue
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
        records.append({'name': item['name'], 'id': item['id'], 'sha256': digest})
    observed = {'sourceCommit': COMMIT, 'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                'artifacts': records, 'allArtifactDigestsVerified': True, 'qualificationPending': True}
    observation_path = output / 'terminal-artifact-observation.json'
    if not observation_path.exists():
        observation_path.write_text(json.dumps(observed, indent=2) + '\n', 'utf-8')
    assert run['conclusion'] == 'success' and all(job['conclusion'] == 'success' for job in jobs), 'Original terminal is failure; preserve and diagnose, do not claim qualification'
    cores = [verify_core(folder, helper, focused) for folder in output.iterdir()
             if folder.is_dir() and folder.name.startswith(('core-validation-', 'musl-native-core-validation'))]
    suites = [helper['protocol'](path, COMMIT) for path in output.rglob('protocol-suite.json')]
    assert len(cores) == len(suites) == runners
    expected = sum(len(row['expectedFailures']) for row in cores)
    assert expected == (2 if args.kind == 'native' else 0)
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
             'run': observed['run'], 'jobs': [{k: j[k] for k in ('id', 'name', 'status', 'conclusion')} for j in jobs],
             'artifacts': records, 'cores': cores, 'protocolSuites': suites,
             'allOriginalCoreAndProtocolReportsVerified': True, 'explicitDarwinExpectedFailureCount': expected,
             'allUnknownOrSkippedResultsRejected': True, 'kernelExternalPortExclusivityQualified': False,
             'publicSkipEnabled': all(any(row['name'] == 'conflict-skip' for row in suite['reports']) for suite in suites),
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    print(json.dumps({'kind': args.kind, 'runners': runners, 'protocolReports': sum(s['cases'] for s in suites),
                      'explicitDarwinExpectedFailures': expected, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()
