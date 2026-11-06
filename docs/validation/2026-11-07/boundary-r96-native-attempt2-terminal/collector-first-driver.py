"""日期：2026-11-07；单独收验R96容量补跑后的完整矩阵，原首轮取消和142协议原件保持。"""
import hashlib
import json
from pathlib import Path
import runpy


# 日期：2026-11-07；只使用新attempt2目录；旧三平台继承成功记录与新ARM结果仍须逐份原件核验。
def main():
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    run = request('/repos/29583855/dukto-next/actions/runs/42252931531')
    assert run['run_attempt'] == 2 and run['head_sha'] == '88f33b2c83f2950307c362fb64c693f7e9e5929d'
    assert run['status'] == 'completed'
    source = Path('.cache/collect-r96-complete-native.py').read_text('utf-8')
    old = "'boundary-r96-' + args.kind + '-terminal'"
    assert source.count(old) == 1
    source = source.replace(old, "'boundary-r96-' + args.kind + '-attempt2-terminal'")
    scope = {'__name__': 'r96_capacity_attempt2', '__file__': str(Path(__file__))}
    exec(compile(source, 'r96_capacity_attempt2', 'exec'), scope)
    scope['main']()
    output = Path('docs/validation/2026-11-07/boundary-r96-native-attempt2-terminal')
    receipt = json.loads((output / 'receipt.json').read_text('utf-8'))
    assert receipt['allOriginalCoreAndProtocolReportsVerified']
    assert len(receipt['cores']) == len(receipt['protocolSuites']) == 4
    assert sum(row['cases'] for row in receipt['protocolSuites']) == 188
    first_path = Path('docs/validation/2026-11-07/boundary-r96-native-terminal/attempt-1-partial-verification.json')
    first = json.loads(first_path.read_text('utf-8'))
    assert first['sourceCommit'] == receipt['sourceCommit']
    assert not first['originalRunQualified'] and first['remainingThreePlatformsOriginalReportsVerified']
    assert sum(row['cases'] for row in first['protocolSuites']) == 142
    value = {'sourceCommit': receipt['sourceCommit'], 'runAttempt': 2,
             'originalAttemptOneConclusion': first['run']['conclusion'],
             'originalCancelledArmJobId': 128012531171,
             'originalAttemptOneProof': {'path': first_path.as_posix(),
                                        'sha256': hashlib.sha256(first_path.read_bytes()).hexdigest()},
             'fullCurrentReceipt': {'path': (output / 'receipt.json').as_posix(),
                                    'sha256': hashlib.sha256((output / 'receipt.json').read_bytes()).hexdigest()},
             'coreTargetsEach': 23, 'protocolReports': 188, 'knownDarwinXfailInstances': 2,
             'allCurrentOriginalCoreAndProtocolReportsVerified': True,
             'releaseQualified': False, 'deliveryComplete': False}
    path = output / 'complete-attempt-receipt.json'
    assert not path.exists()
    path.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps({'attempt': 2, 'protocolReports': 188,
                      'originalCancelledAttemptPreserved': True, 'passedWithExplicitDarwinBoundary': True}), flush=True)


if __name__ == '__main__':
    main()
