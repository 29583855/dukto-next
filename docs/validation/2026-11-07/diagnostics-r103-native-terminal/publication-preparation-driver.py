"""日期：2026-11-07；归档R103真实完整终态，当前R104代码及未完成交付资格不变。"""
from datetime import datetime,timezone
from pathlib import Path
import json,runpy,shutil,subprocess
PARENT='2ba3f142ff444a1cf01a962fabe1c3831ddf4f44'
LABEL='r103-terminal-evidence'

# 日期：2026-11-07；先验证严格收验回执，再更新当前快照及显式文档发布清单。
def main():
 root=Path.cwd();checkout=root/'.cache/github-29583855-dukto-next-r28';base=root/'docs/validation/2026-11-07'
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout).decode().strip()==PARENT
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=checkout)
 helper=runpy.run_path('.cache/finalize-skip-items-r84.py');update,save,proof=helper['update'],helper['save'],helper['proof']
 receipt_path=base/'diagnostics-r103-native-terminal/receipt.json';receipt=json.loads(receipt_path.read_text('utf-8'));assert receipt['sourceCommit']=='cd92c43f301e5a60584b7896a450247855f0bdfd' and receipt['allOriginalCoreAndProtocolReportsVerified'] and receipt['verifiedProtocolReports']==192 and receipt['verifiedCancellationRows']==48 and len(receipt['diagnosticReports'])==4 and receipt['nativeSelectorNegativeGuardsVerified']==4 and receipt['explicitDarwinExpectedFailures']==2
 note='''

## R103完整四平台终态收验（2026-11-07）

- [x] 精确cd92c43的原生CI42311369310四runner均已真实终态success，8份原附件摘要、各23核心、192份协议、48行取消和4个原生选择器负例已严格核对。[完整终态回执](docs/validation/2026-11-07/diagnostics-r103-native-terminal/receipt.json)。
- [x] 四平台真实CLI doctor各12类专项均通过，Linux/双Mac各2个链接拒绝实测；原生渲染、进程恢复和Ubuntu两项磁盘耗尽报告逐件通过。两条精确Darwin XFAIL及历史失败保持，不宣称整个R10/F18或旧间歇失败根因已证明。
- [ ] 当前应用源码仍为R104的9c1e941，双Mac编译/四原生核心已有独立回执；R104完整协议/POSIX八进程和独立Ubuntu复验继续，R103旧源码完整通过不直接转授新代码全部资格。冻结86400秒、过期安全回收、完整R6/GUI/选择器、全部预算/公平性、物理LAN/3×3、各平台长期、依赖源码重建、最低干净系统与正式发布继续；deliveryComplete=false、releaseQualified=false。
'''
 update(root/'开发计划与进度.md',lambda t:t.replace('R102完整终态/188协议与R103已有诊断子项保持各自身份','R102完整终态/188协议及R103完整终态/192协议保持各自身份',1).replace('R98 Windows/Ubuntu冻结CLI执行86400秒；R102完整终态通过，R103协议与R104新原生继续','R98 Windows/Ubuntu冻结CLI执行86400秒；R102/R103完整终态通过，R104完整协议与独立Ubuntu继续',1).rstrip()+note)
 for name in ['docs/执行进度.md','docs/构建验证摘要.md']:update(root/name,lambda t:t.rstrip()+note.replace('(docs/','('))
 update(root/'README.md',lambda t:t.replace('R102四平台完整终态success及188协议已严格收验。','R102的188协议及R103的192协议四平台完整终态success均已严格收验。',1))
 path=root/'docs/ci-verification-20261107-r103.json';report=json.loads(path.read_text('utf-8'));report.update(observedUtc=datetime.now(timezone.utc).isoformat(),nativeCIPending=False,fullProtocolTerminalPending=False,nativeGuardOriginalJsonPending=False,fullNativeRegressionQualified=True,completeTerminalEvidence=proof(receipt_path),verifiedProtocolReports=192,verifiedCancellationRows=48,nativeSaveDialogVerified=False,entireR10Qualified=False,releaseQualified=False,deliveryComplete=False);save(path,report)
 path=root/'docs/current-validation.json';index=json.loads(path.read_text('utf-8'));index.update(observedUtc=report['observedUtc'],r103CompleteTerminal=proof(receipt_path),releaseQualified=False,deliveryComplete=False);save(path,index)
 path=root/'.cache/execution-current.json';state=json.loads(path.read_text('utf-8'));assert state['currentRepositoryCommit']==PARENT;state.update(r103CompleteTerminal=proof(receipt_path),goalStatus='active',releaseQualified=False,deliveryComplete=False);save(path,state)
 shutil.copyfile(Path(__file__),receipt_path.parent/'publication-preparation-driver.py')
 names={'开发计划与进度.md','README.md','docs/执行进度.md','docs/构建验证摘要.md','docs/current-validation.json','docs/ci-verification-20261107-r103.json','docs/validation/2026-11-06/github-api-push-r104-native-evidence.json'}
 names.update(p.relative_to(root).as_posix() for p in receipt_path.parent.rglob('*') if p.is_file() and p.suffix not in ('.zip','.gz','.png'));names=sorted(names)
 for name in names:
  target=checkout/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
 (root/('.cache/'+LABEL+'-publish-files.json')).write_text(json.dumps(names,ensure_ascii=False,indent=2)+'\n','utf-8');(root/('.cache/'+LABEL+'-stage.nul')).write_bytes(b''.join(name.encode('utf-8')+b'\0' for name in names));(root/('.cache/stage-'+LABEL+'.py')).write_bytes((root/'.cache/stage-r104-native-evidence.py').read_bytes().replace(b'r104-native-evidence',LABEL.encode()));print(json.dumps({'explicitFiles':len(names),'verifiedProtocolReports':192,'currentApplicationSourceUnchanged':True}))
if __name__=='__main__':main()
