"""日期：2026-11-07；记录原版发送Abort实际点击、网络EOF及下一批原版Qt4崩溃，不继承新版资格。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path.cwd()
PARENT = '08c022bddabbb36d281198f08e800149eceb96af'
OUTPUT = ROOT / 'docs/validation/2026-11-07/original-r6-send-abort-retry'


# 日期：2026-11-07；本机事件原件只公开必要故障字段，避免发布桌面截图及系统其他事件。
def main():
    checkout = ROOT / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    manifest_path = ROOT / 'docs/validation/2026-11-07/original-r6-cancel/input-manifest.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    original = ROOT / 'Dukto/dukto.exe'
    actual = Path('D:/Program Files (x86)/Dukto/dukto.exe')
    assert hashlib.sha256(original.read_bytes()).hexdigest() == manifest['referenceSha256']
    assert hashlib.sha256(actual.read_bytes()).hexdigest() == manifest['actualExecutableSha256']
    peer_path = OUTPUT / 'original-send-cancel-peer.json'
    peer = json.loads(peer_path.read_text('utf-8'))
    assert peer['declaredBytes'] == 134217728 and peer['receivedBytes'] == 6840000
    assert peer['partialBodyThenDisconnected'] and peer['ending'] == 'eof'
    digest = hashlib.sha256()
    source = ROOT / '.cache/original-r6-cancel-20261107' / manifest['fileName']
    remaining = peer['receivedBytes']
    with source.open('rb') as stream:
        while remaining:
            block = stream.read(min(remaining, 1024 * 1024))
            assert block
            digest.update(block)
            remaining -= len(block)
    assert digest.hexdigest() == peer['receivedPrefixSha256']
    event_path = ROOT / '.cache/original-r6-send-after-abort-event.xml'
    event = ET.parse(event_path)
    ns = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event'}
    values = {node.attrib['Name']: node.text for node in event.findall('.//e:EventData/e:Data', ns)}
    assert values['AppName'] == 'dukto.exe' and values['AppVersion'] == '6.0.0.0'
    assert values['ModuleName'] == 'QtGui4.dll' and values['ExceptionCode'] == 'c000041d'
    assert values['ProcessId'] == '0x947c'
    crash = {name: values[name] for name in ('AppName', 'AppVersion', 'ModuleName', 'ModuleVersion',
                                            'ExceptionCode', 'FaultingOffset', 'ProcessId')}
    crash.update(eventId=int(event.find('./e:System/e:EventID', ns).text),
                 systemTime=event.find('./e:System/e:TimeCreated', ns).attrib['SystemTime'],
                 originalEventXmlSha256=hashlib.sha256(event_path.read_bytes()).hexdigest(),
                 originalEventStoredLocally=True, systemUserAndMachineFieldsPublished=False)
    save(OUTPUT / 'original-after-abort-crash-event.json', crash)
    recovery = {'date': '2026-11-07', 'fixtureExitCode': 1, 'stage': 'reading next batch 16-byte R6 header',
        'exception': 'ConnectionResetError [WinError 10054]', 'nativeNewFilePathEnteredAndSubmitted': True,
        'sameOriginalWindowIdBeforeExit': 5642430, 'actualOriginalProcessId': 38012,
        'sameInstanceNextBatchQualified': False, 'nextBatchFinalContentNotAvailable': True,
        'originalWindowAndProcessAbsentAfterFailure': True, 'windowsCrashEvent': proof(OUTPUT / 'original-after-abort-crash-event.json'),
        'causeNotEstablished': True, 'newProductFailureClaimed': False,
        'wholeF18Qualified': False, 'referenceFilesModified': False}
    save(OUTPUT / 'same-instance-next-send-failure.json', recovery)
    observation = {'date': '2026-11-07', 'observedUtc': datetime.now(timezone.utc).isoformat(),
        'referenceSha256': manifest['referenceSha256'], 'actualExecutableSha256': manifest['actualExecutableSha256'],
        'method': 'computer-use:computer-use @oai/sky actual native file chooser/Abort clicks; independent bounded local R6 receiver',
        'onlyOwnedGeneratedInputUsed': True, 'destination': '127.0.0.1:24367',
        'nativeOriginalSendProgressObserved': True, 'nativeOriginalAbortButtonActuallyClicked': True,
        'nativeOriginalReturnedToSendPageAfterClick': True, 'independentPrefixContentAndEofVerified': True,
        'originalCancelPeerEvidence': proof(peer_path), 'actualCancelClickQualificationAddedSeparately': True,
        'originalPeerReportUnchanged': True, 'originalSendAbortBaselineObserved': True,
        'sameInstanceNextSendEvidence': proof(OUTPUT / 'same-instance-next-send-failure.json'),
        'sameInstanceNextSendQualified': False, 'originalQt4CrashObserved': True, 'crashRootCauseEstablished': False,
        'referenceFilesOrExplicitAppSettingsModified': False, 'nativeChooserMayPersistItsOwnRecentPath': True,
        'desktopScreenshotsOrDirectoryListsPublished': False,
        'newProductSendAndReceiveCancelStillRequired': True, 'wholeF18Qualified': False,
        'deliveryComplete': False, 'releaseQualified': False}
    save(OUTPUT / 'observation.json', observation)
    shutil.copyfile(ROOT / '.cache/original-r6-send-abort-retry.py', OUTPUT / 'validation-driver.py')
    shutil.copyfile(__file__, OUTPUT / 'result-record-driver.py')
    note = '''

## 原版F18发送中止实际对照与后续崩溃（2026-11-07）

- [x] 实际通过原版文件选择器输入自建128MiB文件，向127.0.0.1:24367独立慢读端发送；原生进度页可见Abort并实际点击，随后返回发送页。对端收得6,840,000字节后EOF，前缀SHA与自建输入一致；原始对端报告保持不变，实际点击资格另由观察记录补充。见`docs/validation/2026-11-07/original-r6-send-abort-retry/observation.json`。
- [x] 保留失败：同一原版实例随后通过选择器提交58字节新批次，独立对端在16字节头阶段收到WinError10054；原版窗口/进程随后消失。Windows事件1000记录原版6.0.0.0、QtGui4.dll4.8.4、异常c000041d/偏移004a20d8。仅公开必要事件字段和本机XML摘要；根因未确定，不能把该批记成功或归因于新版。
- [ ] 原版发送Abort入口与实际行为基线现已观察，但下一批恢复失败原件保留；新版仍要求发送/接收主动取消、完整资源释放且能再次传输，完整三平台F18及原版混合拖放继续未完成。未修改原版程序或主动改其设置，原生选择器可能自然保存本次测试路径；桌面截图和目录列表不公开。
'''

    # 日期：2026-11-07；原版恢复故障是基线事实，不改变新版中止后可再次传输的目标。
    def plan_update(text):
        old = '| F18 | 主动中止与异常恢复 | 原版发送有Abort，实际接收无中止入口；对端断开错误及下一批接收已实测 | 新版发送/接收均可取消；对端退出能结束任务、释放资源并再次传输 | 进行中；新端取消再接收/截断/超时子项通过，原版发送Abort和完整三平台仍待验 |'
        new = '| F18 | 主动中止与异常恢复 | 原版发送Abort已实际点及EOF核验；随后新批次原版Qt4崩溃，根因未定；接收无主动入口 | 新版发送/接收均可取消，释放资源并再次传输；原版恢复故障不复制 | 进行中：新端取消再接收/截断/超时子项通过，完整三平台仍待验；原版失败保留 |'
        assert text.count(old) == 1
        return text.replace(old, new, 1).rstrip() + note

    update(ROOT / '开发计划与进度.md', plan_update)

    # 日期：2026-11-07；固定参考对照行补充实际崩溃，所有历史观察保留。
    def comparison_update(text):
        old = '| F18 | 原版发送有Abort；实际接收无中止按钮，源码仅发送时显示。对端断开显示错误，同实例后续46字节批次内容核验通过；此前目录退出记录保留 | 新端接收取消仍为扩展，已有清理/再接收、截断/异常/超时子项；原版发送Abort实际点击和完整三平台F18待验 |'
        new = '| F18 | 原版发送Abort实际点击及部分EOF已验；下一58字节批次在头阶段reset，原版QtGui4崩溃事件保留，根因未定。接收无主动入口，断开后后续46字节接收通过 | 新版发送/接收取消仍要求释放资源和下一任务成功，原版恢复故障不复制；完整三平台F18待验 |'
        assert text.count(old) == 1
        return text.replace(old, new, 1).rstrip() + note

    update(ROOT / 'docs/原版运行与功能对照.md', comparison_update)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(ROOT / name, lambda text: text.rstrip() + note)
    index_path = ROOT / 'docs/current-validation.json'
    current = json.loads(index_path.read_text('utf-8'))
    current['originalR6SendAbortBaseline'] = {'evidence': proof(OUTPUT / 'observation.json'),
        'actualAbortClickAndPrefixEofVerified': True, 'sameInstanceNextSendQualified': False,
        'originalQt4CrashObserved': True, 'crashRootCauseEstablished': False, 'wholeF18Qualified': False}
    current['originalR6ReceiveAbortBaseline']['originalSenderAbortStillPending'] = False
    current.update(observedUtc=observation['observedUtc'], releaseQualified=False, deliveryComplete=False)
    save(index_path, current)
    state_path = ROOT / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state['originalR6SendAbortBaseline'] = current['originalR6SendAbortBaseline']
    save(state_path, state)
    names = {'开发计划与进度.md', 'docs/原版运行与功能对照.md', 'docs/执行进度.md',
             'docs/构建验证摘要.md', 'docs/current-validation.json',
             'docs/validation/2026-11-06/github-api-push-r100-apfs-native-retry.json'}
    names.update(path.relative_to(ROOT).as_posix() for path in OUTPUT.iterdir() if path.is_file())
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    listing = ROOT / '.cache/r100-original-send-abort-publish-files.json'
    assert not listing.exists()
    listing.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (ROOT / '.cache/r100-original-send-abort-stage.nul').write_bytes(b'\0'.join(name.encode('utf-8') for name in names) + b'\0')
    stage = (ROOT / '.cache/stage-r100-deployed-packages.py').read_bytes().replace(b'r100-deployed-packages', b'r100-original-send-abort')
    (ROOT / '.cache/stage-r100-original-send-abort.py').write_bytes(stage)
    print(json.dumps({'explicitFilesPrepared': len(names), 'originalAbortClickAndPrefixVerified': True,
                      'originalNextBatchCrashPreserved': True, 'wholeF18Qualified': False}))


if __name__ == '__main__':
    main()
