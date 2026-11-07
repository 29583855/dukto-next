"""日期：2026-11-07；同步当前索引中的可变清单摘要及R103实际终态，保留历史原件。"""
from pathlib import Path
import hashlib,json,runpy,shutil,subprocess
PARENT='023f2d73210af7cc7114d937e149434b26db619c'
LABEL='r104-current-index'

# 日期：2026-11-07；只更新当前索引和最新回执的引用，不改任何应用/测试输入或旧证据。
def main():
 root=Path.cwd();checkout=root/'.cache/github-29583855-dukto-next-r28';assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout).decode().strip()==PARENT
 assert not subprocess.check_output(['git','status','--porcelain'],cwd=checkout)
 helper=runpy.run_path('.cache/finalize-skip-items-r84.py');save,proof=helper['save'],helper['proof'];path=root/'docs/current-validation.json';index=json.loads(path.read_text('utf-8'))
 before=path.read_bytes();out=root/'docs/validation/2026-11-07/state-use-r104-current-index';out.mkdir(exist_ok=False);(out/'previous-index.json').write_bytes(before)
 index['diagnosticsR103'].update(manifest=proof(root/'docs/ci-verification-20261107-r103.json'),macLinuxNativePending=False,realNativeCliDoctorPending=False,fullNativeRegressionQualified=True,completeTerminalEvidence=proof(root/'docs/validation/2026-11-07/diagnostics-r103-native-terminal/receipt.json'),nativeSaveDialogVerified=False,entireR10Qualified=False)
 index['cancelFixtureR102'].update(manifest=proof(root/'docs/ci-verification-20261107-r102.json'),nativeCIPending=False,fullProtocolTerminalPending=False,completeTerminalEvidence=proof(root/'docs/validation/2026-11-07/cancel-r102-native-terminal/receipt.json'))
 save(path,index)
 # 日期：2026-11-07；递归检查当前索引内明确版本清单的摘要，每个引用必须与公开文件一致。
 checks=[]
 def visit(value):
  if isinstance(value,dict):
   name=value.get('path')
   if name in ['docs/ci-verification-20261107-r102.json','docs/ci-verification-20261107-r103.json','docs/ci-verification-20261107-r104.json']:
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==value['sha256'];checks.append(name)
   for item in value.values():visit(item)
  elif isinstance(value,list):
   for item in value:visit(item)
 visit(index)
 (out/'receipt.json').write_text(json.dumps({'date':'2026-11-07','passed':True,'currentManifestReferencesVerified':checks,'originalIndexRetained':True,'applicationInputsUnchanged':True,'releaseQualified':False,'deliveryComplete':False},indent=2)+'\n','utf-8')
 shutil.copyfile(Path(__file__),out/'verification-driver.py')
 names=['docs/current-validation.json','docs/validation/2026-11-06/github-api-push-r103-terminal-evidence.json',*[p.relative_to(root).as_posix() for p in out.rglob('*') if p.is_file()]]
 for name in names:
  target=checkout/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(root/name,target)
 (root/('.cache/'+LABEL+'-publish-files.json')).write_text(json.dumps(names,indent=2)+'\n','utf-8');(root/('.cache/'+LABEL+'-stage.nul')).write_bytes(b''.join(name.encode('utf-8')+b'\0' for name in names));(root/('.cache/stage-'+LABEL+'.py')).write_bytes((root/'.cache/stage-r103-terminal-evidence.py').read_bytes().replace(b'r103-terminal-evidence',LABEL.encode()));print(json.dumps({'files':len(names),'manifestReferencesVerified':len(checks)}))
if __name__=='__main__':main()
