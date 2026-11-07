"""日期：2026-11-07；已验证后才更新R104计划和显式发布清单，保留全部首次失败。"""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,re,runpy,shutil,subprocess
PARENT='8820a2e0a6e7f386be869881402d760dbb1ec491'
LABEL='r104-state-use'

# 日期：2026-11-07；构建输入、原始回执与发布父提交逐项核对，清理及整体资格继续未完成。
def main():
 root=Path.cwd();checkout=root/'.cache/github-29583855-dukto-next-r28';base=root/'docs/validation/2026-11-07'
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout).decode().strip()==PARENT
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=checkout)
 helper=runpy.run_path('.cache/finalize-skip-items-r84.py');update,save,proof=helper['update'],helper['save'],helper['proof']
 receipt_path=base/'state-use-r104-qualified/receipt.json';receipt=json.loads(receipt_path.read_text('utf-8'));assert receipt['passed'] and len(receipt['windows'])==2
 assert not receipt['expiredTaskCollectionImplemented'] and not receipt['entireR04Qualified']
 for row in receipt['buildInputs']:assert hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256']
 terminal_path=base/'cancel-r102-native-terminal/receipt.json';terminal=json.loads(terminal_path.read_text('utf-8'));assert terminal['allOriginalCoreAndProtocolReportsVerified'] and terminal['verifiedProtocolReports']==188 and terminal['verifiedCancellationRows']==48
 manifest_path=root/'docs/ci-verification-20261107-r104.json';assert not manifest_path.exists()
 manifest={'planVersion':'v0.104','observedUtc':datetime.now(timezone.utc).isoformat(),'basedOnPublishedCommit':PARENT,'buildInputs':receipt['buildInputs'],'windowsEvidence':proof(receipt_path),'nativeCIPending':True,'qualifiedScope':'directory shared/exclusive use guard, Windows full core and corrected real-process fixture; no task deletion or old-version lock claim','releaseQualified':False,'deliveryComplete':False}
 manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n','utf-8')
 note='''

## R104状态目录占用保护与R102完整终态（2026-11-07）

- [x] 普通PrivateStore持有共享内核锁，维护模式非阻塞独占；Windows LockFileEx、POSIX flock，锁文件私有/零字节/单链接，禁止普通状态接口读取或替换。每个实例增加一个句柄，无新增后台线程，退出由内核释放。[边界与后续](docs/状态目录维护保护.md)。
- [x] 双Windows各23核心原件通过，新增同进程互斥方法通过；真实八进程共享、最后使用者退出前拒绝维护、维护期间拒绝新使用、强退恢复、数据保持及非空锁拒绝完成复验。新测试的C++临时对象写法及Python进程分组两次夹具失败均保留，修正未改生产代码或放宽原门槛。[本轮回执](docs/validation/2026-11-07/state-use-r104-qualified/receipt.json)。
- [x] R102精确c1325b0四runner终态success，8份核心/最终附件摘要、各23核心、188份协议、48行取消、4个选择器负例及附加磁盘/原生报告已验；两条精确Darwin XFAIL继续披露，未证明旧夹具间歇失败根因。[终态原件](docs/validation/2026-11-07/cancel-r102-native-terminal/receipt.json)。
- [ ] R104新Mac/Linux原生复验待精确公开后按原件收验。旧版进程/外部SQLite不参与新增锁；暂不提供清理命令，过期回收、恢复临时项清理、有效幂等保留及全局磁盘预算仍须完整实现。R103完整协议、冻结86400秒、完整R6/GUI及选择器、全部资源/公平性、物理LAN/3×3、各平台长期、依赖源码独立重建、最低干净系统与正式分发继续；deliveryComplete=false、releaseQualified=false。
'''
 def plan(text):
  assert '文档版本：v0.103' in text;text=text.replace('文档版本：v0.103','文档版本：v0.104',1)
  text=re.sub(r'^当前阶段：.*$','当前阶段：R104状态目录维护互斥通过双Windows子项；R102四平台完整终态已验，新原生和安全回收/长期交付继续。',text,count=1,flags=re.M)
  text=text.replace('v0.103 / 本地诊断与原子导出','v0.104 / 状态目录维护互斥',1)
  start=text.index('公开仓库：',text.index('## 当前验收快照'));end=text.index('\n\n| 范围',start)
  text=text[:start]+'公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R104状态目录维护互斥通过双Windows子项，213份构建输入见[本轮清单](docs/ci-verification-20261107-r104.json)，新Mac/Linux原生结果待验。R102四平台完整终态success、188协议和48行取消已验；R103双Mac编译和四原生核心已验，完整协议继续。含依赖部署包仍为R100，过期回收与整体交付尚未完成。'+text[end:]
  text=text.replace('R103云原生23核心及本机双工具链诊断子项通过；初轮UI夹具失败保留；R100部署另验','R104双工具链各23核心及占用/崩溃恢复专项通过，原测试夹具失败保留；R100部署另验',1)
  text=text.replace('R98 Windows/Ubuntu冻结CLI执行86400秒；R102/R103完整协议继续，R101原终态失败保留','R98 Windows/Ubuntu冻结CLI执行86400秒；R102完整终态通过，R103协议与R104新原生继续',1)
  return text.rstrip()+note
 update(root/'开发计划与进度.md',plan)
 for name in ['docs/执行进度.md','docs/构建验证摘要.md']:update(root/name,lambda text:text.rstrip()+note.replace('(docs/','('))
 update(root/'docs/补充需求与关键设计.md',lambda text:text.rstrip()+'\n\n## 状态维护互斥补充（2026-11-07）\n\nR104先建立共享使用/独占维护保护。锁不能追溯保护旧版本或外部数据库读取者，不能据此删除有效幂等结果、活动/可恢复数据及用户文件；详见[状态目录维护保护](状态目录维护保护.md)。安全回收和全局磁盘预算仍未完成。\n')
 update(root/'README.md',lambda text:text.replace('## 文档入口','R104已增加状态目录共享使用/独占维护保护，双Windows子项已验，新Mac/Linux原生验证继续；过期回收及全局配额仍待实现。R102四平台完整终态success及188协议已严格收验。详见[状态维护边界](docs/状态目录维护保护.md)和[本轮回执](docs/validation/2026-11-07/state-use-r104-qualified/receipt.json)。\n\n## 文档入口',1))
 path=root/'docs/current-validation.json';index=json.loads(path.read_text('utf-8'));index.update(planVersion='v0.104',observedUtc=manifest['observedUtc'],currentGuiSourceCommitPending=True,publicVerificationReceipt=manifest_path.relative_to(root).as_posix(),stateUseR104={'windowsEvidence':proof(receipt_path),'nativeCIPending':True,'expiredCollectionImplemented':False,'entireR04Qualified':False},r102CompleteTerminal=proof(terminal_path),currentSourceStage='R104 state directory use guard; Windows subset verified; native CI and complete safe GC pending',releaseQualified=False,deliveryComplete=False);save(path,index)
 path=root/'docs/ci-verification-20261107-r102.json';old=json.loads(path.read_text('utf-8'));old.update(nativeCIPending=False,nativeGuardOriginalJsonPending=False,fullProtocolTerminalPending=False,fullNativeRegressionQualified=True,completeTerminalEvidence=proof(terminal_path),verifiedProtocolReports=188,wholeF18Qualified=False,releaseQualified=False,deliveryComplete=False);save(path,old)
 path=root/'.cache/execution-current.json';state=json.loads(path.read_text('utf-8'));assert state['currentRepositoryCommit']==PARENT;state.update(planVersion='v0.104',stateUseR104=manifest,goalStatus='active',workingSourceStage=index['currentSourceStage'],releaseQualified=False,deliveryComplete=False);save(path,state)
 shutil.copyfile(Path(__file__),receipt_path.parent/'publication-preparation-driver.py')
 names={'开发计划与进度.md','README.md','docs/执行进度.md','docs/构建验证摘要.md','docs/补充需求与关键设计.md','docs/状态目录维护保护.md','docs/current-validation.json','docs/ci-verification-20261107-r102.json','docs/ci-verification-20261107-r104.json','docs/validation/2026-11-07/state-use-r104-source-audit.json','docs/validation/2026-11-07/state-use-r104-source-audit-final.json','docs/validation/2026-11-06/github-api-push-r103-native-evidence.json'}
 names.update(row['path'] for row in json.loads((root/'.cache/state-use-r104-before/formats.json').read_text('utf-8')))
 for folder in ['state-use-r104-windows','state-use-r104-correction','state-use-r104-windows-recheck','state-use-r104-process-recheck','state-use-r104-qualified','cancel-r102-native-terminal']:
  names.update(p.relative_to(root).as_posix() for p in (base/folder).rglob('*') if p.is_file() and p.suffix not in ('.zip','.gz','.png'))
 names=sorted(names)
 for name in names:
  raw=(root/name).read_bytes();target=checkout/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
  if name.startswith(('src/','ui/','tests/','scripts/')):raw.decode('utf-8-sig')
 (root/('.cache/'+LABEL+'-publish-files.json')).write_text(json.dumps(names,ensure_ascii=False,indent=2)+'\n','utf-8');(root/('.cache/'+LABEL+'-stage.nul')).write_bytes(b''.join(name.encode('utf-8')+b'\0' for name in names))
 raw=(root/'.cache/stage-r103-native-evidence.py').read_bytes().replace(b'r103-native-evidence',LABEL.encode());(root/('.cache/stage-'+LABEL+'.py')).write_bytes(raw)
 print(json.dumps({'explicitFiles':len(names),'buildInputs':len(receipt['buildInputs']),'planVersion':'v0.104','nativeCIPending':True}))
if __name__=='__main__':main()
