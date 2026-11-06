"""日期：2026-11-06；收验双Mac原生监听分流与原用例重复，保留诊断失败终态及原附件。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import xml.etree.ElementTree as ET


# 日期：2026-11-06；按精确诊断提交核对全部附件，独占失败与未复现的退出超时分别报告。
def main():
    root = Path.cwd()
    output = root / 'docs/validation/2026-11-06/listener-r94-native-diagnostic-terminal'
    api = runpy.run_path('.cache/github-actions-r28.py')
    request, base = api['request'], '/repos/29583855/dukto-next'
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    run = request(base + '/actions/runs/42242892900')
    assert run['head_sha'] == 'afe4a615dc7a1043080985d67f4927a201a6871b'
    assert run['status'] == 'completed' and run['conclusion'] == 'failure'
    jobs = request(base + '/actions/runs/42242892900/jobs?per_page=100')['jobs']
    assert len(jobs) == 2 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/42242892900/artifacts?per_page=100')['artifacts']
    assert len(artifacts) == 2
    output.mkdir(exist_ok=False)
    records = []
    for item in artifacts:
        raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert not item['expired'] and item['digest'] == 'sha256:' + digest
        (output / (item['name'] + '.zip')).write_bytes(raw)
        folder = output / item['name']
        helper['extract'](raw, folder)
        assert (folder / 'diagnostic-commit.txt').read_text('utf-8').strip() == run['head_sha']
        assert (folder / 'production-commit.txt').read_text('utf-8').strip() == 'dec40621cce2d223e46b343e0d3d345a67b80523'
        value = json.loads((folder / 'listener-probe.json').read_text('utf-8'))
        assert len(value['cases']) == 8
        for case in value['cases']:
            assert case['firstBound'] and case['secondBound']
            assert case['secondOptions']['ipv6Only'] == 0
            assert [route['owner'] for route in case['routes']] == ['first', 'second']
            assert all(route['connected'] and route['byteVerified'] for route in case['routes'])
        failures = []
        for attempt in range(1, 4):
            core = ET.parse(folder / ('core-' + str(attempt) + '.xml'))
            failures.extend(dict(row.attrib, failures=[child.attrib for child in row.findall('failure')])
                            for row in core.findall('.//testcase') if row.findall('failure'))
            parallel = ET.parse(folder / ('parallel-' + str(attempt) + '.xml'))
            assert not parallel.findall('.//failure') and not parallel.findall('.//error')
        assert failures
        assert (folder / 'parallel-exit-codes.txt').read_text('utf-8').splitlines() == ['1 0', '2 0', '3 0']
        records.append({'artifactId': item['id'], 'name': item['name'], 'sha256': digest,
                        'probe': helper['proof'](folder / 'listener-probe.json'),
                        'cases': 8, 'ipv4AndIpv6ReachDifferentListeners': True,
                        'nativeNoReuseAlsoSharesPort': True, 'originalCoreFailures': failures,
                        'originalParallelExitAttempts': 3, 'originalParallelExitFailures': 0})
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(),
               'productionCommit': 'dec40621cce2d223e46b343e0d3d345a67b80523',
               'diagnosticCommit': run['head_sha'],
               'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
               'artifacts': records, 'originalFailuresPreserved': True,
               'macCrossFamilyPortSharingReproduced': True, 'turningOffReuseFixesCrossFamilySharing': False,
               'intelParallelExitFailureReproduced': False, 'parallelExitRootCauseProven': False,
               'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'bothArchitectures': True, 'routingCases': 16,
                      'parallelExitAttempts': 6, 'parallelExitFailures': 0,
                      'originalRunConclusion': run['conclusion']}), flush=True)


if __name__ == '__main__':
    main()
