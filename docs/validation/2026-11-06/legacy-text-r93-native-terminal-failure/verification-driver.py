"""日期：2026-11-06；R93全轮失败终态按精确提交收取全部原件，成功子项不能改变整轮失败。"""
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


# 日期：2026-11-06；先核对精确失败终态，逐附件摘要/执行清单/子报告检查，原失败不放宽为成功。
def main():
    output = Path('docs/validation/2026-11-06/legacy-text-r93-native-terminal-failure')
    commit = 'b615d8a0e820bcf9de05d0dce546e930b27ad748'
    api = runpy.run_path('.cache/github-actions-r28.py')
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    request, base = api['request'], '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/42224583301')
    jobs = request(base + '/actions/runs/42224583301/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/42224583301/artifacts?per_page=100')['artifacts']
    assert run['head_sha'] == commit and run['status'] == 'completed' and run['conclusion'] == 'failure'
    assert len(jobs) == 4 and all(row['status'] == 'completed' for row in jobs)
    resumed = output.exists()
    output.mkdir(exist_ok=True)
    assert not (output / 'receipt.json').exists()
    for name, data in [('run', run), ('jobs', jobs), ('artifacts', artifacts)]:
        path = output / (name + '.json')
        if path.exists():
            original = json.loads(path.read_text('utf-8'))
            if name == 'run':
                assert original['head_sha'] == commit and original['id'] == run['id']
            elif name == 'artifacts':
                artifacts = original
        else:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    records = []
    for row in artifacts:
        if not row['name'].startswith(('validation-', 'core-validation-')):
            continue
        cached = output / (row['name'] + '.zip')
        raw = cached.read_bytes() if cached.exists() else request(base + '/actions/artifacts/' + str(row['id']) + '/zip', binary=True)
        sha = hashlib.sha256(raw).hexdigest()
        assert not row['expired'] and row['digest'] == 'sha256:' + sha
        if not cached.exists():
            cached.write_bytes(raw)
        extracted = output / row['name']
        if extracted.exists():
            # 日期：2026-11-06；复查只读原附件和既有原件，避免因收件器目录筛选错误而覆盖下载证据。
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for member in archive.infolist():
                    if not member.is_dir():
                        assert (extracted / member.filename).read_bytes() == archive.read(member)
        else:
            helper['extract'](raw, extracted)
        records.append({'name': row['name'], 'id': row['id'], 'sha256': sha})
    assert len(records) == 8
    suites, failed, verified_reports = [], [], []
    committed_source = subprocess.check_output(['git', 'show', commit + ':scripts/ci_protocol.py'],
                                              cwd='.cache/github-29583855-dukto-next-r28')
    for path in sorted(output.rglob('protocol-suite.json')):
        value = json.loads(path.read_text('utf-8'))
        assert value['sourceCommit'] == commit and value['completed']
        source = committed_source
        if value['platform'] == 'win32':
            source = source.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        assert value['scriptSha256'] == hashlib.sha256(source).hexdigest()
        scope = {'__name__': 'exact_r93_protocol_list'}
        exec(compile(source, commit + ':scripts/ci_protocol.py', 'exec'), scope)
        scope['commands'].__globals__['sys'] = SimpleNamespace(platform=value['platform'], executable='python')
        assert [row['name'] for row in value['cases']] == [row[0] for row in scope['commands'](Path('build'))]
        for row in value['cases']:
            report = path.parent / row['report'].replace('\\', '/').split('/')[-1]
            assert row['reportCreated'] == report.is_file()
            if report.is_file():
                assert hashlib.sha256(report.read_bytes()).hexdigest() == row['reportSha256']
                verified_reports.append(helper['proof'](report))
            if row['passed']:
                assert row['exitCode'] == 0 and report.is_file()
                helper['verify_passed'](json.loads(report.read_text('utf-8')))
            else:
                failed.append({'platform': value['platform'], 'runner': path.parts[-3], **row})
        assert value['passed'] == all(row['passed'] for row in value['cases'])
        suites.append({'platform': value['platform'], 'suite': helper['proof'](path),
                       'cases': len(value['cases']), 'passed': value['passed']})
    assert len(suites) == 4 and failed
    cores = []
    for directory in sorted(output.glob('core-validation-*')):
        if not directory.is_dir():
            continue
        ctest = directory / 'ctest.log'
        xmls = sorted((directory / 'Testing/QtTest').glob('*.xml'))
        assert '100% tests passed' in ctest.read_text('utf-8') and 'out of 23' in ctest.read_text('utf-8')
        assert len(xmls) >= 22
        for path in xmls:
            tree = ET.parse(path)
            assert not tree.findall('.//failure') and not tree.findall('.//error')
            assert all(row.get('result') == 'pass' for row in tree.findall('.//testcase'))
        cores.append({'runner': directory.name, 'ctest': helper['proof'](ctest), 'coreTargets': 23,
                      'xmls': [helper['proof'](path) for path in xmls], 'passed': True})
    assert len(cores) == 4
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': commit,
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'jobs': [{key: row[key] for key in ('id', 'name', 'status', 'conclusion')} for row in jobs],
             'artifacts': records, 'coreSuites': cores, 'protocolSuites': suites,
             'verifiedOriginalReports': verified_reports, 'failedCases': failed,
             'entireRunTerminalVerified': True, 'allOriginalCoreAndProtocolReportsPreserved': True,
             'allProtocolCasesPassed': False, 'rootCauseProvenForAllFailures': False,
             'collectorResumedAfterZipDirectoryFilter': resumed,
             'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'sourceCommit': commit, 'runConclusion': 'failure', 'coreRunnersPassed': 4,
                      'originalReportsVerified': len(verified_reports), 'failedCases': failed}), flush=True)


if __name__ == '__main__':
    main()
