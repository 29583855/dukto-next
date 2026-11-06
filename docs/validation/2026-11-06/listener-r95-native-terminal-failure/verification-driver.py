"""日期：2026-11-06；按R95精确提交保存双Mac回归失败终态及全部原附件，不改写为成功。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET


# 日期：2026-11-06；逐附件摘要、源码身份与原XML核对，分别报告核心、重启和未复现的退出超时。
def main():
    output = Path('docs/validation/2026-11-06/listener-r95-native-terminal-failure')
    api = runpy.run_path('.cache/github-actions-r28.py')
    request, base = api['request'], '/repos/29583855/dukto-next'
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    run = request(base + '/actions/runs/42245971316')
    assert run['head_sha'] == '5dd243fbad36da36568943513deed95ee124ba2d'
    assert run['status'] == 'completed' and run['conclusion'] == 'failure'
    jobs = request(base + '/actions/runs/42245971316/jobs?per_page=100')['jobs']
    assert len(jobs) == 2 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/42245971316/artifacts?per_page=100')['artifacts']
    assert len(artifacts) == 2
    output.mkdir(exist_ok=False)
    records = []
    for item in artifacts:
        raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        (output / (item['name'] + '.zip')).write_bytes(raw)
        folder = output / item['name']
        helper['extract'](raw, folder)
        evidence = folder / 'evidence'
        assert (evidence / 'source-commit.txt').read_text('utf-8').strip() == run['head_sha']
        xmls = sorted((folder / 'build/Testing/QtTest').glob('*.xml'))
        assert len(xmls) == 22
        failures = []
        for path in xmls:
            tree = ET.parse(path)
            for row in tree.findall('.//testcase'):
                if row.findall('failure') or row.findall('error'):
                    failures.append({'report': helper['proof'](path), 'method': row.get('name'),
                                     'details': [child.attrib for child in row.findall('failure') + row.findall('error')]})
        assert failures
        focused = []
        for number in range(1, 6):
            tree = ET.parse(evidence / ('core-' + str(number) + '.xml'))
            text = (evidence / ('core-' + str(number) + '.log')).read_text('utf-8')
            focused.append({'attempt': number, 'failures': [row.attrib for row in tree.findall('.//failure')],
                            'gracefulRestartRowsPassed': text.count('PASS   : CoreTests::tcpGracefulRestart(')})
        parallel = json.loads((evidence / 'parallel-exit/report.json').read_text('utf-8'))
        assert parallel['completed'] and len(parallel['cases']) == 10
        records.append({'name': item['name'], 'id': item['id'], 'sha256': digest,
                        'coreQtReports': [helper['proof'](path) for path in xmls],
                        'coreFailures': failures, 'focused': focused,
                        'parallelExitPassed': parallel['passed'],
                        'parallelExitFailures': sum(not row['passed'] for row in parallel['cases']),
                        'parallelExitReport': helper['proof'](evidence / 'parallel-exit/report.json')})
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': run['head_sha'],
             'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
             'jobs': [{key: job[key] for key in ('id', 'name', 'status', 'conclusion')} for job in jobs],
             'artifacts': records, 'allOriginalArtifactsVerified': True,
             'runPassed': False, 'snapshotGuardPreventsProductConflictButExternalQtSharingRemains': True,
             'allGracefulRestartRowsPassed': all(row['gracefulRestartRowsPassed'] == 3 for item in records for row in item['focused']),
             'parallelExitRootCauseProven': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'originalRunConclusion': 'failure', 'architectures': len(records),
                      'gracefulRestartPassed': value['allGracefulRestartRowsPassed'],
                      'parallelExitFailures': sum(item['parallelExitFailures'] for item in records)}), flush=True)


if __name__ == '__main__':
    main()
