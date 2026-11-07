"""日期：2026-11-07；收验真实诊断原件并明确采样/跟踪影响，不把超时或部分文件当成成功。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics


# 日期：2026-11-07；只依据原始时序和真实退出码生成诊断收验；原超时根因继续保留未定。
def main():
    root = Path.cwd()
    base = root / 'docs/validation/2026-11-07'
    cases = []
    for name, traced, copied in [('task-items-r106-glibc-diagnostic', True, 0),
                                 ('task-items-r106-glibc-untraced', False, 126)]:
        folder = base / name
        result = json.loads((folder / 'diagnostic-result.json').read_text('utf-8'))
        assert json.loads((folder / 'driver-exit.json').read_text('utf-8'))['exitCode'] == 0
        assert json.loads((folder / 'collection-exit.json').read_text('utf-8'))['exitCode'] == 0
        assert result['timedOut'] and result['deadlineSeconds'] == 90 and result['exitCode'] == 7
        assert 90 <= result['elapsedSeconds'] < 93 and result['expectedFiles'] == 201
        assert result['binaryUnchanged'] and result['binarySha256'] == 'cefa0b54a009461d78f968160ea8bfdd46cf9b1690e52aadfafb76ed06bdd157'
        assert result['publishedFileCount'] == copied and result['tracedDiagnosticOnly'] == traced
        samples = [json.loads(row) for row in (folder / 'samples.jsonl').read_text('utf-8').splitlines()]
        events = [json.loads(row) for row in (folder / 'events.jsonl').read_text('utf-8').splitlines()]
        assert samples and events and events[0]['event']['event'] == 'transfer-started'
        assert all(a['seconds'] <= b['seconds'] for a, b in zip(samples, samples[1:]))
        assert all(a['seconds'] <= b['seconds'] for a, b in zip(events, events[1:]))
        assert not any(row['event']['event'] == 'transfer-completed' for row in events)
        assert events[-1]['event']['event'] == 'error' and events[-1]['event']['code'] == 7
        psi = [float(row['pressure']['cpu'].split('avg10=')[1].split()[0]) for row in samples]
        item = {'diagnostic': name, 'straceEnabled': traced, 'samples': len(samples),
                'events': len(events), 'publishedFiles': copied,
                'publishedHashesVerifiedOnlyForNonemptySubset': bool(copied) and result['publishedFileHashesVerified'],
                'cpuPsiSomeAvg10Percent': {'minimum': min(psi), 'median': statistics.median(psi), 'maximum': max(psi)},
                'actualTransferDeadlineSeconds': result['deadlineSeconds'], 'timedOut': True,
                'deadlineTriggeredCancellationCode': 7, 'driverAndCollectionActuallyExitedZero': True,
                'diagnosticBinaryUnchanged': True, 'fullTaskItemsQualified': False}
        if traced:
            for kind in ('client', 'server'):
                raw = (folder / (kind + '-sync.trace')).read_text('utf-8')
                durations = [float(value) for value in re.findall(r'<([0-9.]+)>', raw)]
                assert len(durations) == result[kind + 'Sync']['finishedCalls']
                assert abs(sum(durations) - result[kind + 'Sync']['sumSeconds']) < 1e-6
            item['stracePerturbsSchedulingAndNotTimingBaseline'] = True
        cases.append(item)
    output = base / 'task-items-r106-diagnostic-qualified'
    output.mkdir(exist_ok=False)
    paths = sorted(path for name in ('task-items-r106-glibc-diagnostic', 'task-items-r106-glibc-untraced')
                   for path in (base / name).iterdir() if path.is_file())
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(),
               'productionSourceCommit': '9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6',
               'productionCodeChanged': False, 'diagnostics': cases,
               'originalTimeoutCauseEstablished': False, 'cpuPressureObservedDuringDiagnosticOnly': True,
               'automaticRetriesNotAdded': True, 'original90SecondDeadlineNotIncreased': True,
               'independentUbuntuFullTaskItemsQualified': False,
               'evidence': [{'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                            for path in paths], 'diagnosticEvidenceVerified': True,
               'releaseQualified': False, 'deliveryComplete': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    shutil.copyfile(__file__, output / 'verification-driver.py')
    print(json.dumps({'diagnosticsVerified': len(cases), 'bothTimedOut': True,
                      'originalTimeoutCauseEstablished': False, 'fullTaskItemsQualified': False}))


if __name__ == '__main__':
    main()
