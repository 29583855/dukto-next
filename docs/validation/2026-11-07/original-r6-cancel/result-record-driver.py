"""日期：2026-11-07；按真实原版接收观察修正F18基线，保留工具失败及未完成的发送中止。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess

ROOT = Path.cwd()
COMMIT = 'ed4f5cf08c96f04671e49e5138eda8ce1790ead3'
PARENT = 'ea6f4ef76f1b5f6650384679b03b5b486d858e26'


# 日期：2026-11-07；只登记实际窗口、生成文件和原始源码片段；不发布桌面截图或用户目录列表。
def main():
    checkout = ROOT / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    output = ROOT / 'docs/validation/2026-11-07/original-r6-cancel'
    inputs = json.loads((output / 'input-manifest.json').read_text('utf-8'))
    assert inputs['referenceSha256'] == inputs['actualExecutableSha256'] == '45b78c1d078dd8775bed7be18089e8a60492aeb7a39fc9164f10b687c0a9634c'
    source_path, = list((ROOT / '.reference/archive-r6').rglob('ProgressPage.qml'))
    raw = source_path.read_bytes()
    lines = raw.decode('latin1').splitlines()
    selected = [index for index, line in enumerate(lines) if 'visible: guiBehind.currentTransferSending' in line]
    assert len(selected) == 1
    index = selected[0]
    snippet = '\n'.join(lines[index - 9:index + 1])
    assert 'id: abortButton' in snippet and 'label: "Abort"' in snippet and 'guiBehind.abortTransfer()' in snippet
    recovery_path = output / 'receive-after-peer-disconnect-receipt.json'
    recovery = json.loads(recovery_path.read_text('utf-8'))
    assert recovery['contentVerifiedAfterOriginalReturnedToRecentPage'] and recovery['bytes'] == 46
    cleanup = json.loads((output / 'generated-receive-files-cleanup.json').read_text('utf-8'))
    assert cleanup['onlyExactGeneratedRecoveryFileRemoved'] and not cleanup['partialFileExistsInLaterObservation']
    observation = {
        'date': '2026-11-07', 'observedUtc': datetime.now(timezone.utc).isoformat(),
        'referenceSha256': inputs['referenceSha256'], 'actualExecutableSha256': inputs['actualExecutableSha256'],
        'method': 'computer-use:computer-use @oai/sky actual native window observations; independent bounded Python R6 peer',
        'sourceReference': {'path': source_path.relative_to(ROOT).as_posix(),
                            'sha256': hashlib.sha256(raw).hexdigest(), 'originalBytesUnchanged': True,
                            'visibilityLine': index + 1, 'asciiAbortControlSnippet': snippet},
        'nativeReceivingObserved': True, 'nativeReceiveAbortControlPresent': False,
        'nativeReceiveAbortClickPerformed': False, 'nativeOriginalSenderAbortClickQualified': False,
        'peerIntentionallyDisconnected': True, 'nativeErrorPageObserved': True,
        'nativeErrorText': 'An error has occurred during the transfer... The data you received could be incomplete or broken.',
        'sameOriginalInstanceReceivedNextBatch': True, 'nextBatch': proof(recovery_path),
        'partialFileInitiallyObserved': True, 'partialFileAbsentInLaterObservation': True,
        'desktopScreenshotsPublished': False, 'referenceFilesOrSettingsChanged': False,
        'originalRecentContainsGeneratedRecoveryEntry': True,
        'newProductReceiveCancelStillRequired': True, 'wholeF18Qualified': False,
        'scope': 'Original Windows receive baseline and recovery after peer disconnect only; original send Abort, full new-product F18 and cross-platform interactions remain separate',
        'failureAndCleanupRecords': [proof(output / name) for name in (
            'send-attempt-not-started.json', 'receive-abort-not-present-observation.json',
            'recovery-first-immediate-check-failure.json', 'generated-receive-files-cleanup.json')],
        'deliveryComplete': False, 'releaseQualified': False}
    observation_path = output / 'observation.json'
    if observation_path.exists():
        previous = json.loads(observation_path.read_text('utf-8'))
        assert {key: value for key, value in previous.items() if key != 'observedUtc'} == {
            key: value for key, value in observation.items() if key != 'observedUtc'}
        observation = previous
    else:
        observation_path.write_text(json.dumps(observation, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    note = '''

## 原版F18接收基线补验（2026-11-07）

- [x] 实际Windows R6在接收128MiB自建文件的进度页没有Abort按钮；固定参考源码ProgressPage的abortButton仅在currentTransferSending时可见，二进制摘要与本机参考45b78c1d一致。原版接收侧主动中止对照因此记为“无此入口”，新版接收取消仍作为扩展要求继续验收。
- [x] 自建慢速对端主动断开后，原版实际显示“数据可能不完整或损坏”的错误；同一实例随后收到新的46字节批次，原生最近页与完整字节/摘要已核验。部分文件在初次短时观察存在，后续观察中已不存在；两份观察均保留，不将初始文件存在或TCP关闭当作最终落盘证明。
- [x] 生成的恢复文件在逐字节核对后单独清理，其余接收目录内容与原版程序/设置未改；原版最近页自然新增一个生成文件条目。桌面截图和用户目录列表不公开。
- [ ] 原版发送侧Abort实际点击、混合拖放和完整F18仍待完成。原生选择器的控件索引/坐标映射异常导致发送尚未开始，对端300秒accept超时原件保留；恢复夹具的首次即时读取断言失败也保留，随后同一次传输内容完成证据另记，均不改写为产品失败或整项通过。
'''

    # 日期：2026-11-07；只修正当前功能基线行，原版没有的入口不计为已实现，同时保留新版完整取消要求。
    def comparison_update(text):
        old = '| F18 | 原版首次目录发送时实例曾退出，原因未定；独立捕获和后续直接重试成功，保留两次记录 | 新端取消接收清临时文件后可再次接收；截断/异常/超时回归通过；原版双向中止对照待验 |'
        new = '| F18 | 原版发送有Abort；实际接收无中止按钮，源码仅发送时显示。对端断开显示错误，同实例后续46字节批次内容核验通过；此前目录退出记录保留 | 新端接收取消仍为扩展，已有清理/再接收、截断/异常/超时子项；原版发送Abort实际点击和完整三平台F18待验 |'
        assert text.count(old) == 1 or text.count(new) == 1
        result = text.replace(old, new, 1)
        return result if '## 原版F18接收基线补验（2026-11-07）' in result else result.rstrip() + note

    update(ROOT / 'docs/原版运行与功能对照.md', comparison_update)

    # 日期：2026-11-07；主计划F18维持进行中，将原版观察范围与新版主动取消目标分别注明。
    def plan_update(text):
        old = '| F18 | 发送中止及异常恢复 | B：发送侧 `Abort` 按钮、取消/失败信号；C：接收侧行为 | 主动中止、断网和对端退出均能结束任务、释放资源并允许后续传输 | 进行中：取消后再接收/截断/超时通过，原版中止对照待验 |'
        assert text.count(old) == 1
        new = '| F18 | 主动中止与异常恢复 | 原版发送有Abort，实际接收无中止入口；对端断开错误及下一批接收已实测 | 新版发送/接收均可取消；对端退出能结束任务、释放资源并再次传输 | 进行中；新端取消再接收/截断/超时子项通过，原版发送Abort和完整三平台仍待验 |'
        return text.replace(old, new, 1).rstrip() + note

    update(ROOT / '开发计划与进度.md', plan_update)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(ROOT / name, lambda text: text.rstrip() + note)
    index_path = ROOT / 'docs/current-validation.json'
    current = json.loads(index_path.read_text('utf-8'))
    assert current['productionCommit'] == current['testCommit'] == COMMIT
    current.update(observedUtc=observation['observedUtc'], originalR6ReceiveAbortBaseline={
        'evidence': proof(observation_path), 'nativeReceiveAbortControlPresent': False,
        'peerDisconnectRecoveryContentVerified': True, 'originalSenderAbortStillPending': True,
        'wholeF18Qualified': False}, releaseQualified=False, deliveryComplete=False)
    save(index_path, current)
    state_path = ROOT / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state['originalR6ReceiveAbortBaseline'] = current['originalR6ReceiveAbortBaseline']
    save(state_path, state)
    shutil.copyfile(Path(__file__), output / 'result-record-driver.py')
    names = {'开发计划与进度.md', 'docs/原版运行与功能对照.md', 'docs/执行进度.md',
             'docs/构建验证摘要.md', 'docs/current-validation.json',
             'docs/validation/2026-11-06/github-api-push-r100-deployed-packages-r99-native.json'}
    names.update(path.relative_to(ROOT).as_posix() for path in output.iterdir() if path.is_file())
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    listing = ROOT / '.cache/r100-original-receive-baseline-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (ROOT / '.cache/r100-original-receive-baseline-stage.nul').write_bytes(b'\0'.join(name.encode('utf-8') for name in names) + b'\0')
    stage = (ROOT / '.cache/stage-r100-core-windows-package.py').read_bytes().replace(b'r100-core-windows-package', b'r100-original-receive-baseline')
    (ROOT / '.cache/stage-r100-original-receive-baseline.py').write_bytes(stage)
    print(json.dumps({'explicitFilesPrepared': len(names), 'originalReceiveAbortControlPresent': False,
                      'peerDisconnectRecoveryVerified': True, 'wholeF18Qualified': False}), flush=True)


if __name__ == '__main__':
    main()
