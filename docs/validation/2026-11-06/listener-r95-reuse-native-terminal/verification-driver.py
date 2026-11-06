"""日期：2026-11-07；严格收验Darwin复用位关闭前后的原生共享与正常FIN重启边界。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy


# 日期：2026-11-07；全部16组正文和FIN均须通过，记录真实第二监听成功，不能解释为排他保证。
def main():
    output = Path('docs/validation/2026-11-06/listener-r95-reuse-native-terminal')
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/42248525450')
    assert run['head_sha'] == 'c640e707408366af35904e97c3315888360cdcd6'
    assert run['status'] == 'completed' and run['conclusion'] == 'success'
    items = request(base + '/actions/runs/42248525450/artifacts?per_page=100')['artifacts']
    assert len(items) == 2
    output.mkdir(exist_ok=False)
    records = []
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    for item in items:
        raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + digest and not item['expired']
        (output / (item['name'] + '.zip')).write_bytes(raw)
        folder = output / item['name']
        helper['extract'](raw, folder)
        assert (folder / 'diagnostic-commit.txt').read_text('utf-8').strip() == run['head_sha']
        value = json.loads((folder / 'reuse-probe.json').read_text('utf-8'))
        assert len(value['cases']) == 8
        assert [row['mode'] for row in value['cases']] == [0, 0, 1, 1, 2, 2, 3, 3]
        for row in value['cases']:
            assert row['secondBound'] and row['bodyVerified'] and row['gracefulClosed'] and row['restartBound']
            assert row['firstReuse'] == row['acceptedReuse']
            assert (row['firstReuse'] == 0) == (row['mode'] in (1, 2))
        records.append({'name': item['name'], 'id': item['id'], 'sha256': digest,
                        'report': helper['proof'](folder / 'reuse-probe.json'),
                        'cases': 8, 'allSecondQtListenersBound': True,
                        'allGracefulBodiesAndRestartsPassed': True})
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(),
              'productionCommit': '5dd243fbad36da36568943513deed95ee124ba2d',
              'diagnosticCommit': run['head_sha'],
              'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
              'artifacts': records, 'allOriginalArtifactsVerified': True,
              'disablingReuseDoesNotPreventLaterQtWildcardSpecificBinding': True,
              'kernelPortExclusivityQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (output / 'verification-driver.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps({'architectures': 2, 'actualCases': 16, 'reuseDisableFixesExternalSharing': False,
                      'allGracefulRestartsPassed': True}), flush=True)


if __name__ == '__main__':
    main()
