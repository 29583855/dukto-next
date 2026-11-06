"""日期：2026-11-07；收验R97双Mac退出夹具回归，精确保留Darwin预期失败并拒绝skip。"""
import json
from pathlib import Path
import runpy


# 日期：2026-11-07；复用既有原件完整性检查，再核新四状态、原16组和每架构六条明确XFAIL。
def main():
    commit = '38f2384524bfdefa2ffefcc4c737224185a53266'
    text = Path('.cache/collect-r96-native-regression.py').read_text('utf-8')
    for old, new in (
            ('88f33b2c83f2950307c362fb64c693f7e9e5929d', commit),
            ('boundary-r96-native-regression-terminal', 'exit-state-r97-native-regression-terminal')):
        assert old in text
        text = text.replace(old, new)
    scope = {'__name__': 'r97_native_regression', '__file__': str(Path(__file__))}
    exec(compile(text, 'r97_native_regression', 'exec'), scope)
    scope['main']()
    output = Path('docs/validation/2026-11-07/exit-state-r97-native-regression-terminal')
    receipt = json.loads((output / 'receipt.json').read_text('utf-8'))
    if not receipt['nativeListenerRegressionQualifiedWithExplicitBoundary']:
        print(json.dumps({'originalFailurePreserved': True, 'newFixtureQualified': False}), flush=True)
        return
    qualifier = runpy.run_path('.cache/record-r96-regression-and-dispatches.py')['verify_reports']
    checks = []
    for item in receipt['artifacts']:
        folder = output / item['name']
        reports = qualifier(folder)
        log = (folder / 'build/Testing/QtTest/file-exchange-tests.log').read_text('utf-8')
        for row in ('already-finished', 'already-finished-error', 'running-finishes', 'real-deadline'):
            assert 'PASS   : FileExchangeTests::childExitWait(' + row + ')' in log
        assert log.count('PASS   : FileExchangeTests::parallelDispositions(') == 16
        checks.append({'architecture': item['architecture'], 'reports': reports,
                       'newExitStateRows': 4, 'originalParallelRows': 16,
                       'allUnknownOrSkippedResultsRejected': True})
    value = {'sourceCommit': commit, 'architectures': checks,
             'explicitDarwinExpectedFailureInstances': 12, 'originalWaitMs': 10000,
             'originalHistoricalFailureCausesAllProven': False,
             'newFixtureQualified': True, 'releaseQualified': False, 'deliveryComplete': False}
    path = output / 'fixture-qualification.json'
    assert not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    print(json.dumps({'newFixtureQualified': True, 'architectures': 2,
                      'newExitStateRowsEach': 4, 'originalParallelRowsEach': 16}), flush=True)


if __name__ == '__main__':
    main()
