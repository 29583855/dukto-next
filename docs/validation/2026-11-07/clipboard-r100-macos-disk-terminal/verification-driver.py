"""日期：2026-11-07；严格收验R100双Mac原生APFS真实盘满、物理预留、恢复及镜像退出原件。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import plistlib
import runpy
import shutil
import subprocess

COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
ROOT = Path.cwd()
OUTPUT = ROOT / 'docs/validation/2026-11-07/clipboard-r100-macos-disk-terminal'


# 日期：2026-11-07；已保存原件只允许相同字节复用，终态失败和首次观察不被后续成功覆盖。
def preserve(path, raw):
    if path.exists():
        assert path.read_bytes() == raw, str(path)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)


# 日期：2026-11-07；真实物理空间预留及内核ENOSPC必须存在，不能用逻辑文件大小冒充真实盘满。
def exhaustion(value):
    assert value['method'] == 'Darwin F_PREALLOCATE physical reservation'
    assert value['kernelError'] == 'ENOSPC' and value['physicalBytes'] > 0 and value['fillerBytes'] > 0
    assert value['elapsedSeconds'] >= 0


# 日期：2026-11-07；每个自建镜像必须由普通退出释放；已卸载路径不等同于镜像设备已退出。
def cleanup(value):
    assert value['passed'] and value['ownershipVerified'] and value['forced'] is False
    assert value['budgetSeconds'] == 20 and value['maximumAttempts'] == 8
    assert len(value['attempts']) <= 8 and value['observations']
    assert value['completion'] == 'owned image absent and mount released'
    final = value['observations'][-1]
    assert final['attached'] is False and final['devices'] == final['mountPoints'] == []


# 日期：2026-11-07；工作流终态原件先保存，再逐核对七组磁盘业务和七份独立镜像清理。
def main():
    assert not (OUTPUT / 'receipt.json').exists()
    ledger = json.loads((ROOT / '.cache/r100-macos-disk-dispatch.json').read_text('utf-8'))
    assert ledger['sourceCommit'] == COMMIT and ledger['responseReceived']
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    base = '/repos/29583855/dukto-next'
    runs = request(base + '/actions/workflows/macos-disk.yml/runs?per_page=100&head_sha=' + COMMIT)['workflow_runs']
    run, = [value for value in runs if value['head_sha'] == COMMIT]
    assert run['status'] == 'completed'
    if 'runId' in ledger:
        assert run['id'] == ledger['runId']
    jobs = request(base + '/actions/runs/' + str(run['id']) + '/jobs?per_page=100')['jobs']
    assert len(jobs) == 2 and all(job['status'] == 'completed' for job in jobs)
    artifacts = request(base + '/actions/runs/' + str(run['id']) + '/artifacts?per_page=100')['artifacts']
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': COMMIT,
                   'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                   'jobs': jobs, 'releaseQualified': False, 'deliveryComplete': False}
    initial = OUTPUT / 'terminal-observation.json'
    if initial.exists():
        previous = json.loads(initial.read_text('utf-8'))
        assert {key: value for key, value in previous.items() if key != 'observedUtc'} == {
            key: value for key, value in observation.items() if key != 'observedUtc'}
        observation = previous
    else:
        preserve(initial, (json.dumps(observation, indent=2) + '\n').encode('utf-8'))
    helper = runpy.run_path('.cache/verify-client-history-r80-packages.py')
    downloads = {}
    for item in artifacts:
        assert item['name'] in ('macos-apfs-ARM64', 'macos-apfs-X64') and not item['expired']
        archive = OUTPUT / (item['name'] + '.zip')
        raw = archive.read_bytes() if archive.exists() else request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        checksum = hashlib.sha256(raw).hexdigest()
        assert item['digest'] == 'sha256:' + checksum
        preserve(archive, raw)
        files = helper['checked_zip'](raw, max_bytes=32 * 1024**2)
        for name, content in files.items():
            assert Path(name).suffix in ('.json', '.log')
            preserve(OUTPUT / item['name'] / name, content)
        assert item['name'] not in downloads
        downloads[item['name']] = {'artifact': {key: item[key] for key in ('id', 'name', 'digest')}, 'files': files}
    for job in jobs:
        path = OUTPUT / ('job-' + str(job['id']) + '.log')
        if not path.exists():
            preserve(path, request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True))
    assert run['conclusion'] == 'success' and all(job['conclusion'] == 'success' for job in jobs), \
        'Original failure preserved; inspect raw business and cleanup evidence before any retry'
    assert set(downloads) == {'macos-apfs-ARM64', 'macos-apfs-X64'}
    checkout = ROOT / '.cache/github-29583855-dukto-next-r28'
    script = subprocess.check_output(['git', 'show', COMMIT + ':tests/parallel_disk_integration.py'], cwd=checkout)
    script_sha = hashlib.sha256(script).hexdigest()
    proof = runpy.run_path('.cache/finalize-skip-items-r84.py')['proof']
    names = ('r6', 'tls1', 'tls4', 'tls16', 'overwrite-1', 'overwrite-4', 'overwrite-16')
    records = []
    for label, downloaded in downloads.items():
        files = downloaded['files']
        disk_names = {name for name in files if name.startswith('apfs-') and name.endswith('-disk.json')}
        prefix = '' if disk_names else 'build/'
        assert {name for name in files if name.endswith('-disk.json')} == {
            prefix + 'apfs-' + name + '-disk.json' for name in names}
        assert not any(name.endswith('-failure.json') for name in files)
        reports, binary_hashes = [], set()
        for name in names:
            report_name = prefix + 'apfs-' + name + '-disk.json'
            value = json.loads(files[report_name])
            assert value['passed'] and 4 * 1024**2 <= value['filesystemBytes'] <= 512 * 1024**2
            filesystem_name = prefix + 'apfs-' + name + '-filesystem.log'
            filesystem = plistlib.loads(files[filesystem_name])
            assert filesystem.get('FilesystemType', '').lower() == 'apfs', filesystem_name
            cleaned = json.loads(files[prefix + 'apfs-' + name + '-cleanup.json'])
            cleanup(cleaned)
            if name == 'r6':
                assert value['kernelError'] == 'ENOSPC' and value['receiverExitCode'] == 5
                assert value['failureResult']['stage'] == 'write'
                assert value['preflight']['passed'] and value['preflight']['stage'] == 'space'
                assert value['preflight']['receiverExitCode'] == 5 and value['preflight']['noTemporaryCreated']
                assert value['originalPreserved'] and value['temporaryCleaned'] and value['nextReceivePassed']
                exhaustion(value['exhaustion'])
            else:
                channels = int(name.removeprefix('tls').removeprefix('overwrite-'))
                policy = 'overwrite' if name.startswith('overwrite-') else 'rename'
                assert value['platform'] == 'Darwin' and value['conflictPolicy'] == policy
                assert value['scriptSha256'] == script_sha and len(value['executableSha256']) == 64
                binary_hashes.add(value['executableSha256'])
                assert len(value['cases']) == 2 and {case['direction'] for case in value['cases']} == {'upload', 'download'}
                for case in value['cases']:
                    assert case['passed'] and case['channels'] == channels and case['conflictPolicy'] == policy
                    assert case['kernelError'] == 'ENOSPC' and case['failure']['code'] == 5
                    assert 0 < case['confirmedBeforeFull'] < int(case['bytes'])
                    assert case['originalPreservedBeforePublication'] and case['retainedPartCountAfterFailure'] == 1
                    assert len(case['sha256']) == 64
                    assert case['originalReplacedAfterRecovery'] if policy == 'overwrite' else case['sameNameOriginalPreserved']
                    exhaustion(case['exhaustion'])
            reports.append({'name': name, 'report': proof(OUTPUT / label / report_name),
                            'cleanup': proof(OUTPUT / label / (prefix + 'apfs-' + name + '-cleanup.json')),
                            'filesystem': proof(OUTPUT / label / filesystem_name),
                            'tlsDirections': 0 if name == 'r6' else 2})
        assert len(binary_hashes) == 1
        records.append({'artifact': downloaded['artifact'], 'reports': reports,
                        'observedTlsCliSha256': next(iter(binary_hashes)),
                        'independentDiskImages': 7, 'tlsDirections': 12,
                        'physicalReservationEnospcVerified': True, 'allOwnedImagesDetached': True})
    receipt = dict(observation, platforms=records, nativeArchitectures=2,
                   businessReports=14, cleanupReports=14, tlsDirections=24,
                   currentDiskSubsetQualified=True, completeDiskFaultMatrixQualified=False,
                   fullNativeProtocolRegressionQualified=False, passed=True)
    preserve(OUTPUT / 'receipt.json', (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    shutil.copyfile(Path(__file__), OUTPUT / 'verification-driver.py')
    print(json.dumps({'sourceCommit': COMMIT, 'nativeArchitectures': 2, 'businessReports': 14,
                      'tlsDirections': 24, 'ownedImagesDetached': 14, 'passed': True}), flush=True)


if __name__ == '__main__':
    main()
