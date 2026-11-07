"""日期：2026-11-08；收取原24小时终态，保留运行库漂移导致的原驱动失败，不重跑或修改断言。"""
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import shutil


# 日期：2026-11-08；原报告与逐轮资源独立核对，只授予业务子集，整个冻结依赖验收仍失败。
def main():
    root = Path.cwd()
    source = root / 'docs/validation/2026-11-07/current-linux-r98-long/results'
    target = root / 'docs/validation/2026-11-08/r98-ubuntu-long-terminal'
    target.mkdir(exist_ok=True)
    assert not (target / 'receipt.json').exists()
    observation = json.loads((root / '.cache/r123-long-observation.json').read_bytes())
    driver = json.loads((source / 'driver-result.json').read_bytes())
    value = json.loads((source / 'summary24h.json').read_bytes())
    launch = json.loads((source / 'launch.json').read_bytes())
    assert not driver['passed'] and not driver['frozenInputsAndDependenciesUnchanged']
    assert driver['cases'] == [{'name': name, 'exitCode': 0} for name in ['sampling', 'smoke20', 'summary24h']]
    assert value['passed'] and value['status'] == 'passed'
    assert value['durationRequestedSeconds'] == 86400 and value['elapsedSeconds'] == 86400.021
    assert value['rounds'] == 262 and value['requestedChannels'] == 16
    assert observation['ubuntu']['allFrozenInputsUnchanged'] and not observation['ubuntu']['allRuntimeDependenciesUnchanged']
    assert not observation['ubuntu']['originalServiceProcessAlive']
    assert value['executableSha256'] == launch['binarySha256'] == observation['ubuntu']['executableSha256']
    tests = json.loads((source / 'summary24h-test-inputs.json').read_bytes())['files']
    for name, sha in tests.items():
        assert launch['frozenFiles']['tests/' + name] == sha
    assert tests['parallel_soak_integration.py'] == value['testScriptSha256']
    with (source / 'summary24h-samples.csv').open(encoding='utf-8', newline='') as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == value['rounds']
    baseline = {name: max(int(row[name]) for row in rows[:10]) for name in ['rss', 'private', 'threads', 'handles']}
    assert baseline == value['warmBaseline']
    previous = -1
    for index, row in enumerate(rows, 1):
        elapsed = float(row['elapsedSeconds'])
        assert int(row['round']) == index and previous < elapsed <= value['elapsedSeconds']
        assert row['phase'] == 'idle-after-duplex'
        previous = elapsed
        assert int(row['rss']) < 512 * 1024**2 and int(row['private']) < 512 * 1024**2
        if index >= 20:
            assert all(int(row[name]) <= baseline[name] + 16 * 1024**2 for name in ['rss', 'private'])
            assert int(row['handles']) <= baseline['handles'] + 8
            assert int(row['threads']) <= baseline['threads'] + 1
    originals = []
    for path in sorted(source.iterdir()):
        if path.is_file() and path.suffix in ['.json', '.csv', '.log', '.txt']:
            raw = path.read_bytes()
            assert len(raw) <= 32 * 1024**2
            (target / path.name).write_bytes(raw)
            originals.append({'path': path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    shutil.copyfile(root / '.cache/r123-long-observation.json', target / 'final-observation.json')
    shutil.copyfile(Path(__file__), target / 'verification-driver.py')
    result = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': launch['sourceCommit'],
              'elapsedSeconds': value['elapsedSeconds'], 'rounds': value['rounds'], 'requestedChannels': 16,
              'businessSubtestsPassed': True, 'allFrozenSourceAndBinariesUnchanged': True,
              'allRuntimeDependenciesUnchanged': False, 'originalDriverPassed': False,
              'longQualificationGranted': False, 'currentR123LongQualified': False,
              'qualificationScope': launch['qualificationScope'], 'originals': originals,
              'changedRuntimeDependencies': observation['ubuntu']['changedRuntimeDependencies'],
              'deliveryComplete': False, 'releaseQualified': False}
    (target / 'receipt.json').write_text(json.dumps(result, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: result[key] for key in ['businessSubtestsPassed', 'elapsedSeconds', 'rounds',
                                                 'originalDriverPassed', 'longQualificationGranted']}))


if __name__ == '__main__':
    main()
