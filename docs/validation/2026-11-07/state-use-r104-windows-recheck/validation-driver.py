"""日期：2026-11-07；两种Windows编译器真实构建并执行占用互斥及原任务竞争，不重用旧报告。"""
from pathlib import Path
import hashlib
import json
import runpy
import shutil
import subprocess
import sys
import time

# 日期：2026-11-07；每步保存原始日志和退出码，失败不删除报告或降低原门槛。
def main():
 root=Path.cwd(); output=root/'docs/validation/2026-11-07/state-use-r104-windows-recheck';output.mkdir(exist_ok=False)
 prior=json.loads((root/'docs/ci-verification-20261107-r103.json').read_text('utf-8'))['buildInputs']
 inputs=[dict(path=row['path'],sha256=hashlib.sha256((root/row['path']).read_bytes()).hexdigest()) for row in prior]
 (output/'build-inputs.json').write_text(json.dumps(inputs,indent=2)+'\n','utf-8')
 environment=runpy.run_path('.cache/validate-overwrite-r62.py')['environment'];results=[]
 for label,folder,cmake,ctest,extra in [('ucrt','windows-ucrt','.tools/msys64/ucrt64/bin/cmake.exe','.tools/msys64/ucrt64/bin/ctest.exe',[]),('msvc','windows','.tools/python/Scripts/cmake.exe','.tools/python/Scripts/ctest.exe',['-C','Release'])]:
  target=output/label;target.mkdir();env=environment(label);row={'toolchain':label}
  with (target/'build.log').open('xb') as log:
   row['buildExitCode']=subprocess.run([str(root/cmake),'--build',str(root/'build'/folder),'--config','Release','--parallel','2'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1800).returncode
  assert row['buildExitCode']==0,row
  with (target/'ctest.log').open('xb') as log:
   row['ctestExitCode']=subprocess.run([str(root/ctest),'--test-dir',str(root/'build'/folder),*extra,'--output-on-failure'],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200).returncode
  shutil.copytree(root/'build'/folder/'Testing/QtTest',target/'QtTest');shutil.copyfile(root/'build'/folder/'Testing/Temporary/LastTest.log',target/'LastTest.log')
  binary=root/'build'/folder
  if label=='msvc':binary/='Release'
  for name,script,exe in [('task-store','task_store_integration','task-store-probe.exe'),('doctor','doctor_integration','dukto-cli.exe'),('service','service_integration','dukto-cli.exe')]:
   started=time.monotonic()
   with (target/(name+'.log')).open('xb') as log:
    row[name+'ExitCode']=subprocess.run([sys.executable,'-X','utf8','tests/'+script+'.py',str(binary/exe),'--report',str(target/(name+'.json'))],env=env,stdout=log,stderr=subprocess.STDOUT,timeout=300).returncode
   row[name+'Seconds']=round(time.monotonic()-started,3)
  row['passed']=all(value==0 for key,value in row.items() if key.endswith('ExitCode'));results.append(row)
  (output/'progress.json').write_text(json.dumps(results,indent=2)+'\n','utf-8');print(json.dumps(row),flush=True)
 unchanged=all(hashlib.sha256((root/row['path']).read_bytes()).hexdigest()==row['sha256'] for row in inputs)
 value={'cases':results,'buildInputsUnchanged':unchanged,'passed':unchanged and all(row['passed'] for row in results),'releaseQualified':False,'deliveryComplete':False}
 (output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n','utf-8');shutil.copyfile(Path(__file__),output/'validation-driver.py')
 return 0 if value['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
