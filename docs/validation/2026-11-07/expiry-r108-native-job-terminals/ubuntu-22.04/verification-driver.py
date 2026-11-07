"""日期：2026-11-07；分别收验真实完成的原生作业，不提前宣布其余作业或整个运行通过。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

SOURCE = '73cd10ac95be6c97fd67134ba14b6edee4b2c189'
RUN = 42332515396


# 日期：2026-11-07；每个成功作业单独保存官方附件与日志，并重验精确提交的全协议报告和新增保护。
def main():
    root = Path.cwd()
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    helper = runpy.run_path('.cache/collect-exact-native-r87.py')
    base = '/repos/29583855/dukto-next'
    run = request(base + '/actions/runs/' + str(RUN))
    assert run['head_sha'] == SOURCE and run['run_attempt'] == 1
    jobs = request(base + '/actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']
    artifacts = request(base + '/actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    output = root / 'docs/validation/2026-11-07/expiry-r108-native-job-terminals'
    output.mkdir(exist_ok=True)
    selected = {'native (macos-15, brew)': 'macos-15',
                'native (macos-15-intel, brew)': 'macos-15-intel',
                'native (ubuntu-22.04, system)': 'ubuntu-22.04',
                'native (windows-2022, 5.15.2, win64_msvc2019_64)': 'windows-2022'}
    for job in jobs:
        if job['status'] != 'completed' or job['conclusion'] != 'success':
            continue
        runner = selected[job['name']]
        folder = output / runner
        if (folder / 'receipt.json').exists():
            continue
        folder.mkdir(exist_ok=False)
        item, = [item for item in artifacts if item['name'] == 'validation-' + runner]
        raw = request(base + '/actions/artifacts/' + str(item['id']) + '/zip', binary=True)
        digest = hashlib.sha256(raw).hexdigest()
        assert not item['expired'] and item['digest'] == 'sha256:' + digest
        (folder / (item['name'] + '.zip')).write_bytes(raw)
        destination = folder / item['name']
        helper['extract'](raw, destination)
        log = request(base + '/actions/jobs/' + str(job['id']) + '/logs', binary=True)
        (folder / 'job.log').write_bytes(log)
        observation = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': SOURCE,
                       'run': {key: run[key] for key in ('id', 'head_sha', 'status', 'conclusion', 'html_url')},
                       'job': {key: job[key] for key in ('id', 'name', 'status', 'conclusion', 'steps')},
                       'artifact': {key: item[key] for key in ('id', 'name', 'digest', 'expired')},
                       'archiveSha256': digest, 'jobLogSha256': hashlib.sha256(log).hexdigest()}
        (folder / 'observation.json').write_text(json.dumps(observation, indent=2) + '\n', 'utf-8')
        suite = helper['protocol']((destination / 'build/protocol-suite.json').relative_to(root), SOURCE)
        task_items = json.loads((destination / 'build/task-items.json').read_text('utf-8'))
        fixture = subprocess.check_output(['git', 'show', SOURCE + ':tests/task_items_integration.py'],
                                         cwd=root / '.cache/github-29583855-dukto-next-r28')
        if runner == 'windows-2022':
            fixture = fixture.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        assert task_items['passed'] and task_items['scriptSha256'] == hashlib.sha256(fixture).hexdigest()
        assert len(task_items['cases']) == 4 and task_items['missingLocalReceiptExplicit']
        # 日期：2026-11-07；新31项TLS报告必须覆盖512帧和缓冲取消，不能只接受旧28项报告。
        tls = json.loads((destination / 'build/secure-channel.json').read_text('utf-8'))
        assert tls['passed'] and len(tls['cases']) == 31
        for name, code in [('bufferedBurst', 0), ('bufferedBurstAfterDisconnect', 0), ('bufferedBurstCancellation', 7)]:
            assert tls['cases'][name]['passed'] and tls['cases'][name]['exitCode'] == code
        guard = json.loads((destination / 'build/task-store.json').read_text('utf-8'))
        assert guard['passed'] and guard['competingProcesses'] == 8 and guard['leaseRecoveredAfterKill']
        state = guard['stateDirectoryUse']
        assert state['sharedProcesses'] == 8 and state['firstRefusalSeconds'] < 2
        for key in ('exclusiveRefusedUntilLastReaderExited', 'sharedAndExclusiveRefusedDuringMaintenance',
                    'recoveredAfterKill', 'ordinaryDataUnchanged', 'nonemptyGuardRefusedWithoutTruncation'):
            assert state[key]
        doctor = json.loads((destination / 'build/doctor.json').read_text('utf-8'))
        assert doctor['passed'] and doctor['binaryUnchanged'] and len(doctor['checks']) == 12
        navigation = json.loads((destination / 'build/main-window-navigation.json').read_text('utf-8'))
        assert navigation['passed'] and navigation['sourceCommit'] == SOURCE and navigation['binaryUnchanged']
        extras = [destination / 'build/main-window-navigation.json', destination / 'proxy-pacing.json']
        if runner.startswith('macos-'):
            extras += [destination / 'build/macos-native-render.json', destination / 'build/macos-native-process-recovery.json']
        if runner == 'ubuntu-22.04':
            extras += [destination / 'build/disk.json', destination / 'build/parallel-disk.json']
        for path in extras:
            value = json.loads(path.read_text('utf-8'))
            assert value['passed']
            helper['verify_passed'](value)
        receipt = dict(observation, verifiedProtocol=suite, taskItemsCorrectedFixturePassed=True,
                       stateUseEightProcessPassed=True, diagnosticsChecks=12, secureChannelCases=31,
                       additionalReports=[helper['proof'](path.relative_to(root)) for path in extras],
                       thisNativeJobVerified=True, entireRunQualified=False,
                       independentUbuntuTimeoutNotResolved=True, releaseQualified=False, deliveryComplete=False)
        (folder / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
        shutil.copyfile(__file__, folder / 'verification-driver.py')
        print(json.dumps({'runner': runner, 'job': job['id'], 'protocolCases': suite['cases'],
                          'taskItemsCorrectedFixturePassed': True, 'entireRunQualified': False}), flush=True)


if __name__ == '__main__':
    main()
