"""日期：2026-11-07；公开双Mac实际盘满通过及首次原生报告上传失败，保持完整交付未完成。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
PARENT = 'ae30b4ba881464b5427ecbca9de5700912e65740'
BASE = ROOT / 'docs/validation/2026-11-07'


# 日期：2026-11-07；仅发布严格收验完成的子项，业务源码和运行中的长测冻结输入保持不变。
def main():
    checkout = ROOT / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    disk_folder = BASE / 'clipboard-r100-macos-disk-terminal'
    disk_path = disk_folder / 'receipt.json'
    disk = json.loads(disk_path.read_text('utf-8'))
    assert disk['sourceCommit'] == COMMIT and disk['passed'] and disk['run']['conclusion'] == 'success'
    assert disk['nativeArchitectures'] == 2 and disk['businessReports'] == disk['cleanupReports'] == 14
    assert disk['tlsDirections'] == 24 and disk['currentDiskSubsetQualified']
    assert not disk['completeDiskFaultMatrixQualified'] and not disk['fullNativeProtocolRegressionQualified']
    subset_folder = BASE / 'clipboard-r100-native-terminal'
    subset_path = subset_folder / 'first-attempt-qualified-subset.json'
    subset = json.loads(subset_path.read_text('utf-8'))
    assert subset['sourceCommit'] == COMMIT and subset['verifiedProtocolReports'] == 142
    assert subset['firstAttempt']['conclusion'] == 'failure' and not subset['intelProtocolQualified']
    assert not subset['fullNativeRegressionQualified']
    for source_name, target in (('r100-macos-disk-dispatch.json', disk_folder),
                                ('r100-intel-upload-retry.json', subset_folder)):
        destination = target / source_name
        assert not destination.exists()
        shutil.copyfile(ROOT / '.cache' / source_name, destination)
    retry = json.loads((subset_folder / 'r100-intel-upload-retry.json').read_text('utf-8'))
    assert retry['responseReceived'] and retry['originalJobId'] == 128115892367
    request = runpy.run_path('.cache/github-actions-r28.py')['request']
    run = request('/repos/29583855/dukto-next/actions/runs/42282812778')
    jobs = request('/repos/29583855/dukto-next/actions/runs/42282812778/jobs?per_page=100')['jobs']
    assert run['head_sha'] == COMMIT and run['run_attempt'] == 2 and len(jobs) == 4
    observation = {'observedUtc': datetime.now(timezone.utc).isoformat(),
                   'run': {k: run[k] for k in ('id', 'head_sha', 'status', 'conclusion', 'html_url', 'run_attempt')},
                   'jobs': [{'id': job['id'], 'name': job['name'], 'status': job['status'],
                             'conclusion': job['conclusion'],
                             'currentSteps': [step['name'] for step in job['steps'] if step['status'] == 'in_progress']}
                            for job in jobs], 'releaseQualified': False, 'deliveryComplete': False}
    observed_path = subset_folder / 'retry-start-observation.json'
    assert not observed_path.exists()
    observed_path.write_text(json.dumps(observation, indent=2) + '\n', 'utf-8')
    for name, target, output_name in (
        ('dispatch-r100-macos-disk.py', disk_folder, 'dispatch-driver.py'),
        ('rerun-r100-intel-upload-job.py', subset_folder, 'retry-driver.py'),
        ('collect-r100-native-retry-terminal.py', subset_folder, 'prepared-retry-collector.py'),
        ('prepare-r100-native-retry-collector.py', subset_folder, 'retry-collector-preparation-driver.py')):
        shutil.copyfile(ROOT / '.cache' / name, target / output_name)
    failure_path = subset_folder / 'retry-collector-preparation-first-failure.json'
    assert not failure_path.exists()
    failure_path.write_text(json.dumps({'date': '2026-11-07', 'exitCode': 1,
        'stage': 'Before output creation; no product or CI was run',
        'reason': 'Preparation incorrectly assumed original collector CRLF; original bytes were LF',
        'correction': 'Detect original newline and preserve it; prepared collector syntax passed',
        'businessThresholdChanged': False}, indent=2) + '\n', 'utf-8')
    report_path = ROOT / 'docs/ci-verification-20261107-r100.json'
    report = json.loads(report_path.read_text('utf-8'))
    assert report['sourceCommit'] == COMMIT and len(report['buildInputs']) == 210
    for row in report['buildInputs']:
        assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256']
    report.update(observedUtc=observation['observedUtc'], macosDiskEvidence=proof(disk_path),
                  macosDiskNativeArchitectures=2, macosDiskBusinessReports=14, macosDiskTlsDirections=24,
                  fullNativeFirstAttemptEvidence=proof(subset_path),
                  fullNativeRunObservation=proof(observed_path), fullNativeRegressionQualified=False,
                  fullNativeIntelOnlyRetryPending=True, originalThreePlatformProtocolReports=142,
                  releaseQualified=False, deliveryComplete=False)
    save(report_path, report)
    index_path = ROOT / 'docs/current-validation.json'
    current = json.loads(index_path.read_text('utf-8'))
    assert current['productionCommit'] == current['testCommit'] == COMMIT
    current['macOSDiskR100'] = {'sourceCommit': COMMIT, 'evidence': proof(disk_path),
        'runUrl': disk['run']['html_url'], 'nativeArchitectures': 2, 'businessReports': 14,
        'cleanupReports': 14, 'tlsDirections': 24, 'physicalEnospcAndOriginalProtectionVerified': True,
        'ownedImagesNormallyDetached': True, 'completeDiskFaultMatrixQualified': False}
    current['nativeR100FirstAttempt'] = {'evidence': proof(subset_path), 'conclusion': 'failure',
        'failedStep': 'Preserve validation logs', 'failureJobId': 128115892367,
        'failureCategory': subset['failureCategory'], 'verifiedOriginalProtocolReports': 142,
        'intelBusinessMetadataPassedButOriginalProtocolReportsMissing': True,
        'wholeRegressionQualified': False, 'intelOnlyRetry': proof(observed_path)}
    current['clipboardAvailabilityR100'].update(manifest=proof(report_path), nativeRun=observation['run'])
    current.update(observedUtc=observation['observedUtc'],
        currentSourceStage='R100 current packages and dual macOS APFS disk subset verified; first native run artifact upload failed on Intel, only that job retried; full delivery and long tests remain pending',
        releaseQualified=False, deliveryComplete=False)
    save(index_path, current)
    note = '''

## R100双Mac真实盘满及原生报告上传故障（2026-11-07）

- [x] 精确ed4f5cf的独立APFS运行42293178190终态success；Apple Silicon/Intel各七个256MiB自建镜像，合计14份业务/14份清理/24个TLS方向原件逐项核验。真实F_PREALLOCATE物理预留和内核ENOSPC均存在，R6及TLS的1/4/16通道默认保名、显式覆盖均验证原件保护、错误5和释放空间后的恢复内容；全部镜像普通退出且挂载/设备最终不存在，没有强制卸载或耗尽宿主卷。见`docs/validation/2026-11-07/clipboard-r100-macos-disk-terminal/receipt.json`。
- [x] R100完整原生首轮42282812778原终态failure已保留：Intel编译、23核心、原生导航及完整协议步骤均success，唯一失败为GitHub CreateArtifact连续五次请求超时，最终协议附件缺失。其他Windows/Ubuntu/ARM的142份协议原报告和所有现存附件SHA逐份核验；四平台核心原有资格保持，不能用Intel步骤元数据替代缺失原报告。
- [x] 首轮原件和四份原job日志收存后，只补原Intel job128115892367；同运行第二次attempt已实际开始，三个成功平台继承原时间而不冒充重跑。补跑收验器保留各23核心/188协议/剪贴板草稿QML/精确两条Darwin XFAIL全部门槛，终态原件待收验。准备器首次假定CRLF的断言失败发生在输出创建前，已记录并改为识别原换行，无业务门槛变化。
- [ ] 本轮没有修改生产/测试210输入，未重新授予整个故障矩阵、完整原生回归或24h资格。Windows/Linux冻结CLI长测仍运行；完整编辑器和OS剪贴板、原版发送Abort/拖放及全原生交互、全部资源/公平性/安全GC、物理LAN/3×3、各平台长期、依赖源码独立重建及正式签名发布继续。
'''

    # 日期：2026-11-07；更新当前快照而保留历史各轮状态，缺失报告不标成通过。
    def plan_update(text):
        old = '当前阶段：R100四平台各23核心和三平台当前GUI/独立CLI部署包已验；完整协议、Windows/Linux长测及交付继续。'
        new = '当前阶段：R100当前三平台部署包、四平台核心及双Mac真实APFS盘满子集已验；完整回归Intel报告上传故障定向补跑，Windows/Linux长测及交付继续。'
        assert text.count(old) == 1
        text = text.replace(old, new, 1)
        old = '剪贴板/草稿QML、三平台当前GUI/独立CLI部署包及原迁移业务通过，完整协议仍待终态收验。'
        new = '剪贴板/草稿QML、当前三平台部署及双Mac真实盘满恢复子集通过。完整原生首轮仅Intel上传报告连续超时，其他三平台142协议原件已验；首轮failure保留，已只补Intel任务，完整资格仍待原件。'
        assert text.count(old) == 1
        text = text.replace(old, new, 1)
        text = text.replace('| 完整协议、完整原生交互和真实24h终态 |',
                            '| 完整原生交互、真实24h终态和完整故障矩阵 |', 1)
        text = text.replace('R100各23核心、剪贴板/草稿QML及含依赖双部署包已验；各338源码、5迁移业务及Cocoa/高DPI导航通过',
                            'R100各23核心、含依赖双部署包及双Mac APFS盘满恢复已验；ARM完整46协议通过，Intel原报告缺失补跑', 1)
        text = text.replace('R99完整回归已验，R100原生回归继续',
                            'R99完整回归已验；R100首轮Intel仅报告上传失败、现只补该任务', 1)
        old = 'Linux 目录句柄/替换与真实磁盘满通过；macOS 待验'
        new = 'Linux 目录句柄/替换与真实磁盘满通过；双Mac APFS盘满原件保护/恢复子集通过，完整交互与故障矩阵待验'
        assert text.count(old) == 1
        return text.replace(old, new, 1).rstrip() + note

    update(ROOT / '开发计划与进度.md', plan_update)
    update(ROOT / 'docs/执行进度.md', lambda text: text.replace('更新日期：2026-11-06', '更新日期：2026-11-07', 1).rstrip() + note)

    # 日期：2026-11-07；摘要首段展示最新事实，历史结果按原文保留。
    def summary_update(text):
        lines = text.splitlines()
        assert lines[2].startswith('更新日期：')
        lines[2] = '更新日期：2026-11-07，计划v0.100。R100三平台当前部署包、四平台23核心和双Mac真实APFS盘满/恢复子集已验；完整回归首轮仅Intel报告上传超时，已保存原件并定向补跑。Windows/Linux真实24h继续，整体及正式发布未完成。'
        return '\n'.join(lines).rstrip() + note

    update(ROOT / 'docs/构建验证摘要.md', summary_update)
    state_path = ROOT / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(macosDiskR100=current['macOSDiskR100'], nativeR100FirstAttempt=current['nativeR100FirstAttempt'])
    save(state_path, state)
    shutil.copyfile(__file__, disk_folder / 'result-record-driver.py')
    names = {'开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/current-validation.json', 'docs/ci-verification-20261107-r100.json',
             'docs/validation/2026-11-06/github-api-push-r100-original-receive-baseline.json'}
    for folder in (disk_folder, subset_folder):
        names.update(path.relative_to(ROOT).as_posix() for path in folder.rglob('*')
                     if path.is_file() and path.suffix != '.zip')
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    listing = ROOT / '.cache/r100-apfs-native-retry-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (ROOT / '.cache/r100-apfs-native-retry-stage.nul').write_bytes(b'\0'.join(name.encode('utf-8') for name in names) + b'\0')
    stage = (ROOT / '.cache/stage-r100-deployed-packages.py').read_bytes().replace(b'r100-deployed-packages', b'r100-apfs-native-retry')
    (ROOT / '.cache/stage-r100-apfs-native-retry.py').write_bytes(stage)
    print(json.dumps({'explicitFilesPrepared': len(names), 'sourceInputsUnchanged': 210,
                      'macosDiskReports': 14, 'macosDiskTlsDirections': 24,
                      'originalNativeFailurePreserved': True, 'wholeDeliveryComplete': False}))


if __name__ == '__main__':
    main()
