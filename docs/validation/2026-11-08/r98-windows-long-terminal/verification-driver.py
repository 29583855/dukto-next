"""日期：2026-11-08；独立收验冻结R98 Windows的24小时终态，不转授当前产品资格。"""
from datetime import datetime, timezone
import csv
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path.cwd()


# 日期：2026-11-08；按启动清单和原始采样重新核对时长、全部输入及稳定门槛，不重新运行或修改原件。
def main():
    report = ROOT / 'docs/validation/2026-11-07/current-windows-r98-long'
    frozen = ROOT / '.cache/current-windows-r98-long'
    output = ROOT / 'docs/validation/2026-11-08/r98-windows-long-terminal'
    output.mkdir(exist_ok=False)
    launch = json.loads((report / 'launch.json').read_bytes())
    driver = json.loads((report / 'driver-result.json').read_bytes())
    value = json.loads((report / 'summary24h.json').read_bytes())
    assert driver['passed'] and driver['frozenInputsUnchanged']
    assert driver['cases'] == [{'name': name, 'exitCode': 0} for name in ['sampling', 'smoke100', 'summary24h']]
    assert value['status'] == 'passed' and value['passed'] and value['durationRequestedSeconds'] == 86400
    assert 86400 <= value['elapsedSeconds'] < 93000 and value['rounds'] >= 20
    assert value['requestedChannels'] == 16 and launch['requestedSeconds'] == 86400
    expected = '2fdecefae477b2415dd9282964eee85ece9d50e582027fe2012f2828a91c394b'
    assert value['executableSha256'] == expected
    for name, sha in launch['files'].items():
        assert hashlib.sha256((frozen / name).read_bytes()).hexdigest() == sha, name
    assert hashlib.sha256((frozen / 'runtime/dukto-cli.exe').read_bytes()).hexdigest() == expected
    tests = json.loads((report / 'summary24h-test-inputs.json').read_bytes())['files']
    for name, sha in tests.items():
        assert hashlib.sha256((frozen / 'tests' / name).read_bytes()).hexdigest() == sha, name
    assert tests['parallel_soak_integration.py'] == value['testScriptSha256']
    with (report / 'summary24h-samples.csv').open(encoding='utf-8', newline='') as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == value['rounds'] == 285
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
            for name in ['rss', 'private']:
                assert int(row[name]) <= baseline[name] + 16 * 1024**2
            assert int(row['handles']) <= baseline['handles'] + 8
    for side in value['peaks'].values():
        assert side['rss'] < 512 * 1024**2 and side['private'] < 512 * 1024**2
    assert value['warmApplicationThreads'] == 1
    application = sum(item['startModule'].lower() not in ['ntdll.dll', 'mswsock.dll', 'kernel32.dll'] for item in value['lastThreads'])
    assert application <= value['warmApplicationThreads'] + 1
    assert len(value['lastThreads']) - application <= 16
    originals = []
    for path in report.iterdir():
        if path.is_file() and path.suffix in ['.json', '.csv', '.log']:
            raw = path.read_bytes()
            assert len(raw) <= 32 * 1024**2
            (output / path.name).write_bytes(raw)
            originals.append({'path': path.name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
    shutil.copyfile(Path(__file__), output / 'verification-driver.py')
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': launch['sourceCommit'],
               'productionCommit': launch['productionCommit'], 'passed': True, 'elapsedSeconds': value['elapsedSeconds'],
               'rounds': value['rounds'], 'requestedChannels': 16, 'frozenInputCount': len(launch['files']),
               'allFrozenInputsUnchanged': True, 'executableSha256': expected, 'originals': originals,
               'qualificationScope': 'frozen R98 Windows bounded-task duplex only',
               'currentR121LongQualified': False, 'arbitraryGrowthQualified': False, 'automaticGcQualified': False,
               'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    print(json.dumps({key: receipt[key] for key in ['passed', 'elapsedSeconds', 'rounds', 'frozenInputCount']}))


if __name__ == '__main__':
    main()
