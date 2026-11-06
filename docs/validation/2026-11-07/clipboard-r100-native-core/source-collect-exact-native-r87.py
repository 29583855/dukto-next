"""日期：2026-11-06；收取指定精确提交终态原生CI，逐核验核心与全部独立协议原件。"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import runpy
import stat
import subprocess
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile


# 日期：2026-11-06；原始日志/报告按逐字节摘要绑定，不把包成功当作核心或协议通过。
def proof(path):
    return {'path': path.as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


# 日期：2026-11-06；只把有界普通证据写入新目录，拒绝链接、重名、路径逃逸与可执行对象。
def extract(raw, output):
    names = set()
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for member in archive.infolist():
            path = PurePosixPath(member.filename)
            assert not path.is_absolute() and '..' not in path.parts and ':' not in member.filename
            assert member.filename not in names and not stat.S_ISLNK(member.external_attr >> 16)
            names.add(member.filename)
            if member.is_dir():
                continue
            assert member.file_size <= 32 * 1024**2
            target = output / member.filename
            assert target.suffix in ('.json', '.xml', '.log', '.txt', '.sha256', '.png')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(member))


# 日期：2026-11-06；递归拒绝业务报告中的失败结论，保留全部原始结构供独立复查。
def verify_passed(value):
    if isinstance(value, dict):
        assert value.get('passed') is not False
        for child in value.values():
            verify_passed(child)
    elif isinstance(value, list):
        for child in value:
            verify_passed(child)


# 日期：2026-11-06；严格核对执行清单、精确脚本及每份实际报告的原始SHA，不接受缺件。
def protocol(path, commit):
    value = json.loads(path.read_text('utf-8'))
    assert value['completed'] and value['passed'] and value['sourceCommit'] == commit
    source = subprocess.check_output(['git', 'show', commit + ':scripts/ci_protocol.py'],
                                     cwd='.cache/github-29583855-dukto-next-r28')
    if value['platform'] == 'win32':
        source = source.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
    assert value['scriptSha256'] == hashlib.sha256(source).hexdigest()
    module = {'__name__': 'exact_committed_ci_protocol'}
    exec(compile(source, commit + ':scripts/ci_protocol.py', 'exec'), module)
    module['commands'].__globals__['sys'] = SimpleNamespace(platform=value['platform'], executable='python')
    names = [case[0] for case in module['commands'](Path('build'))]
    assert [case['name'] for case in value['cases']] == names
    reports = []
    for case in value['cases']:
        report = path.parent / case['report'].replace('\\', '/').split('/')[-1]
        assert case['reportCreated'] and case['passed'] and case['exitCode'] == 0
        assert proof(report)['sha256'] == case['reportSha256']
        verify_passed(json.loads(report.read_text('utf-8')))
        reports.append(dict(proof(report), name=case['name']))
    return {'suite': proof(path), 'cases': len(reports), 'reports': reports, 'passed': True}


# 日期：2026-11-06；仅收取所有job成功的终态运行，一次新目录保留完整证据和核验范围。
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run', required=True, type=int)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--runners', required=True, type=int)
    args = parser.parse_args()
    api = runpy.run_path('.cache/github-actions-r28.py')
    request, base = api['request'], '/repos/' + api['REPOSITORY']
    run = request(base + '/actions/runs/' + str(args.run))
    assert run['head_sha'] == args.commit and run['status'] == 'completed' and run['conclusion'] == 'success'
    jobs = request(base + '/actions/runs/' + str(args.run) + '/jobs?per_page=100')['jobs']
    assert len(jobs) == args.runners and all(job['conclusion'] == 'success' for job in jobs)
    args.output.mkdir(exist_ok=False)
    artifacts = request(base + '/actions/runs/' + str(args.run) + '/artifacts?per_page=100')['artifacts']
    records = []
    for item in artifacts:
        if item['name'].startswith('macos-compiled-'):
            continue
        raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        (args.output / (item['name'] + '.zip')).write_bytes(raw)
        extract(raw, args.output / item['name'])
        records.append({'name': item['name'], 'id': item['id'], 'sha256': digest})
    cores = []
    for directory in args.output.iterdir():
        if not directory.is_dir() or not directory.name.startswith(('core-validation-', 'musl-native-core-validation')):
            continue
        ctest = directory / 'ctest.log'
        assert '100% tests passed' in ctest.read_text('utf-8') and 'out of 23' in ctest.read_text('utf-8')
        xmls = list((directory / 'Testing/QtTest').glob('*.xml'))
        for path in xmls:
            tree = ET.parse(path)
            assert not tree.findall('.//failure') and not tree.findall('.//error')
            assert int(tree.getroot().get('failures', '0')) == 0
            assert all(case.get('result') == 'pass' for case in tree.findall('.//testcase'))
        assert len(xmls) >= 22
        cores.append({'runner': directory.name, 'ctest': proof(ctest), 'xmls': [proof(path) for path in xmls], 'passed': True})
    suites = [protocol(path, args.commit) for path in args.output.rglob('protocol-suite.json')]
    assert len(cores) == len(suites) == args.runners
    result = {'date': datetime.now(timezone.utc).isoformat(), 'sourceCommit': args.commit,
              'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
              'artifacts': records, 'cores': cores, 'protocolSuites': suites,
              'allOriginalCoreAndProtocolReportsVerified': True,
              'publicSkipEnabled': all(any(report['name'] == 'conflict-skip' for report in suite['reports']) for suite in suites),
              'releaseQualified': False, 'deliveryComplete': False}
    (args.output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'sourceCommit': args.commit, 'runners': args.runners,
                      'protocolReports': sum(suite['cases'] for suite in suites),
                      'receipt': str(args.output / 'receipt.json'), 'passed': True}), flush=True)


if __name__ == '__main__':
    main()
