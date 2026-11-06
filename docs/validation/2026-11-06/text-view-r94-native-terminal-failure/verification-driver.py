"""日期：2026-11-07；保留R94完整原生失败终态，按精确源码和执行清单核对成功与失败原件。"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile


# 日期：2026-11-07；下载可续接但已有原件仅只读核对，整轮失败保持失败且不放宽任何断言。
def main():
    output = Path('docs/validation/2026-11-06/text-view-r94-native-terminal-failure')
    commit = 'dec40621cce2d223e46b343e0d3d345a67b80523'
    api = runpy.run_path('.cache/github-actions-r28.py')
    request, base = api['request'], '/repos/29583855/dukto-next'
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    run = request(base + '/actions/runs/42235469581')
    jobs = request(base + '/actions/runs/42235469581/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/42235469581/artifacts?per_page=100')['artifacts']
    assert run['head_sha'] == commit and run['status'] == 'completed' and run['conclusion'] == 'failure'
    assert len(jobs) == 4 and all(job['status'] == 'completed' for job in jobs)
    output.mkdir(exist_ok=True)
    assert not (output / 'receipt.json').exists()
    for name, value in (('run', run), ('jobs', jobs), ('artifacts', artifacts)):
        path = output / (name + '.json')
        if not path.exists():
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    records = []
    for row in artifacts:
        if not row['name'].startswith(('core-validation-', 'validation-')):
            continue
        cached = output / (row['name'] + '.zip')
        raw = cached.read_bytes() if cached.exists() else request(base + '/actions/artifacts/' + str(row['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert row['digest'] == 'sha256:' + digest and not row['expired']
        if not cached.exists():
            cached.write_bytes(raw)
        folder = output / row['name']
        if folder.exists():
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for member in archive.infolist():
                    if not member.is_dir():
                        assert (folder / member.filename).read_bytes() == archive.read(member)
        else:
            helper['extract'](raw, folder)
        records.append({'name': row['name'], 'id': row['id'], 'sha256': digest})
    assert len(records) == 8
    source = subprocess.check_output(['git', 'show', commit + ':scripts/ci_protocol.py'],
                                     cwd='.cache/github-29583855-dukto-next-r28')
    suites, failed_cases, reports = [], [], []
    for path in sorted(output.rglob('protocol-suite.json')):
        value = json.loads(path.read_text('utf-8'))
        assert value['sourceCommit'] == commit and value['completed']
        actual_source = source if value['platform'] != 'win32' else source.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        assert value['scriptSha256'] == hashlib.sha256(actual_source).hexdigest()
        scope = {'__name__': 'exact_r94_protocol_list'}
        exec(compile(actual_source, commit + ':scripts/ci_protocol.py', 'exec'), scope)
        scope['commands'].__globals__['sys'] = SimpleNamespace(platform=value['platform'], executable='python')
        assert [row['name'] for row in value['cases']] == [row[0] for row in scope['commands'](Path('build'))]
        for row in value['cases']:
            report = path.parent / row['report'].replace('\\', '/').split('/')[-1]
            assert row['reportCreated'] == report.is_file()
            if report.is_file():
                assert hashlib.sha256(report.read_bytes()).hexdigest() == row['reportSha256']
                reports.append(helper['proof'](report))
            if row['passed']:
                assert row['exitCode'] == 0 and report.is_file()
                helper['verify_passed'](json.loads(report.read_text('utf-8')))
            else:
                failed_cases.append({'platform': value['platform'], 'runner': path.parts[-3], **row})
        assert value['passed'] == all(row['passed'] for row in value['cases'])
        suites.append({'platform': value['platform'], 'suite': helper['proof'](path),
                       'cases': len(value['cases']), 'passed': value['passed']})
    assert len(suites) == 4
    cores, core_failures = [], []
    for folder in sorted(output.glob('core-validation-*')):
        if not folder.is_dir():
            continue
        ctest = folder / 'ctest.log'
        xmls = sorted((folder / 'Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 22
        failures = []
        for path in xmls:
            tree = ET.parse(path)
            for row in tree.findall('.//testcase'):
                for child in row.findall('failure') + row.findall('error'):
                    failures.append({'report': helper['proof'](path), 'method': row.get('name'),
                                     'details': child.attrib, 'text': child.text})
        text = ctest.read_text('utf-8')
        passed = '100% tests passed' in text
        assert (not failures) == passed
        assert 'out of 23' in text
        cores.append({'runner': folder.name, 'ctest': helper['proof'](ctest), 'coreTargets': 23,
                      'xmls': [helper['proof'](path) for path in xmls], 'passed': passed})
        core_failures.extend(dict(row, runner=folder.name) for row in failures)
    assert len(cores) == 4 and core_failures
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'jobs': [{key: job[key] for key in ('id', 'name', 'status', 'conclusion')} for job in jobs],
             'artifacts': records, 'coreSuites': cores, 'coreFailures': core_failures,
             'protocolSuites': suites, 'verifiedOriginalReports': reports, 'failedCases': failed_cases,
             'entireRunTerminalVerified': True, 'allOriginalCoreAndProtocolReportsPreserved': True,
             'allCoreTargetsPassed': False, 'allProtocolCasesPassed': not failed_cases,
             'rootCauseProvenForAllFailures': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'sourceCommit': commit, 'nativeConclusion': 'failure', 'protocolReports': len(reports),
                      'protocolFailures': len(failed_cases), 'coreFailures': len(core_failures)}), flush=True)


if __name__ == '__main__':
    main()
