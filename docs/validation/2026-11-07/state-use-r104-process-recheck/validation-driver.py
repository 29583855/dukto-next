"""日期：2026-11-07；修正进程测试的分组错误，只复验受影响脚本；所有已通过核心二进制必须保持。"""
from pathlib import Path
import hashlib,json,runpy,shutil,subprocess,sys

# 日期：2026-11-07；保存原夹具和失败，按编译产物摘要证明只调整测试脚本，没有重编译生产程序。
def main():
 root=Path.cwd();base=root/'docs/validation/2026-11-07';initial=base/'state-use-r104-windows-recheck'
 old=json.loads((initial/'driver-result.json').read_text('utf-8'));assert not old['passed'] and old['buildInputsUnchanged']
 assert len(old['cases'])==2 and all(row['buildExitCode']==row['ctestExitCode']==row['doctorExitCode']==row['serviceExitCode']==0 and row['task-storeExitCode']==1 for row in old['cases'])
 output=base/'state-use-r104-process-recheck';output.mkdir(exist_ok=False)
 source=root/'tests/task_store_integration.py';shutil.copyfile(source,base/'state-use-r104-correction/task_store_integration.initial.py')
 raw=source.read_bytes();oldline=b'            events = [finish(process) for process in processes]';newblock=b'            creation_processes = []\n            for _ in range(8):'
 assert raw.count(oldline)==1 and raw.count(b'            for _ in range(8):')==3
 oldblock=b'            for _ in range(8):\n                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")\n                processes.append(process)\n            events = [finish(process) for process in processes]'
 newblock=b'            creation_processes = []\n            for _ in range(8):\n                process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8")\n                processes.append(process)\n                creation_processes.append(process)\n            events = [finish(process) for process in creation_processes]'
 assert raw.count(oldblock)==1;source.write_bytes(raw.replace(oldblock,newblock))
 prior=json.loads((initial/'build-inputs.json').read_text('utf-8'));inputs=[{'path':row['path'],'sha256':hashlib.sha256((root/row['path']).read_bytes()).hexdigest()} for row in prior]
 changed=[a['path'] for a,b in zip(inputs,prior) if a!=b];assert changed==['tests/task_store_integration.py'],changed
 (output/'build-inputs.json').write_text(json.dumps(inputs,indent=2)+'\n','utf-8')
 environment=runpy.run_path('.cache/validate-overwrite-r62.py')['environment'];results=[]
 for label,folder in [('ucrt','windows-ucrt'),('msvc','windows/Release')]:
  target=output/label;target.mkdir();binary=root/'build'/folder
  before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in binary.glob('*.exe')}
  with (target/'task-store.log').open('xb') as log:code=subprocess.run([sys.executable,'-X','utf8','tests/task_store_integration.py',str(binary/'task-store-probe.exe'),'--report',str(target/'task-store.json')],env=environment(label),stdout=log,stderr=subprocess.STDOUT,timeout=300).returncode
  after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in binary.glob('*.exe')};assert before==after
  row={'toolchain':label,'exitCode':code,'allBuildExecutablesUnchanged':True,'binarySha256':before,'passed':code==0};results.append(row);print(json.dumps({k:v for k,v in row.items() if k!='binarySha256'}),flush=True)
  (output/'progress.json').write_text(json.dumps(results,indent=2)+'\n','utf-8')
 unchanged=all(hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'] for row in inputs)
 value={'cases':results,'changedBuildInputs':changed,'buildInputsUnchanged':unchanged,'productionCodeChangedForCorrection':False,'freshFull23TargetsRerun':False,'passed':unchanged and all(row['passed'] for row in results),'releaseQualified':False,'deliveryComplete':False}
 (output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n','utf-8');shutil.copyfile(Path(__file__),output/'validation-driver.py')
 return 0 if value['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
