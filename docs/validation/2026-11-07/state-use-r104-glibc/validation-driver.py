"""日期：2026-11-07；独立Ubuntu目录验证状态占用锁，不触及冻结长期测试。"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import runpy
import shutil
import subprocess
import tarfile

# 日期：2026-11-07；冻结源码快照、全核心及真实进程测试保留退出码和原件。
def main():
 root=Path.cwd();output=root/'docs/validation/2026-11-07/state-use-r104-glibc';output.mkdir(exist_ok=False)
 ssh=runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH'];snapshot=runpy.run_path('scripts/source_snapshot.py')
 archive=root/'.cache/source-state-use-r104.tar.gz';snapshot['create'](root,archive)
 for local,remote in [(archive,'/home/dukto/source-state-use-r104.tar.gz'),(root/'scripts/source_snapshot.py','/home/dukto/source-install-state-use-r104.py')]:
  with local.open('rb') as data:subprocess.run(ssh+['set -C; cat > '+remote],stdin=data,check=True,timeout=120)
 program=r'''
import hashlib,json,os,runpy,subprocess
from pathlib import Path
root=Path('/home/dukto/state-use-r104');root.mkdir(exist_ok=False)
runpy.run_path('/home/dukto/source-install-state-use-r104.py')['install'](root,Path('/home/dukto/source-state-use-r104.tar.gz'))
output=root/'results';output.mkdir();runtime=root/'runtime';runtime.mkdir(mode=0o700)
env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',XDG_RUNTIME_DIR=str(runtime))
rows=[]
# 日期：2026-11-07；每条原始命令串行运行，失败仍原样记录，不重用此前编译或报告。
def check(name,args,timeout=1800):
 with (output/(name+'.log')).open('xb') as log:p=subprocess.run(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
 rows.append({'name':name,'exitCode':p.returncode});(output/'exit-codes.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows[-1]),flush=True)
 return p.returncode
assert check('configure',['cmake','-S','.','-B','build','-G','Ninja','-DCMAKE_BUILD_TYPE=Release'])==0
assert check('build',['cmake','--build','build','--parallel','2'])==0
before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'build/dukto-cli',root/'build/task-store-probe')}
check('ctest',['ctest','--test-dir','build','--output-on-failure'],3600)
for name,script,exe in [('task-store','task_store_integration','task-store-probe'),('doctor','doctor_integration','dukto-cli'),('service','service_integration','dukto-cli')]:
 check(name,['python3','-X','utf8','tests/'+script+'.py',str(root/'build'/exe),'--report',str(output/(name+'.json'))],300)
after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'build/dukto-cli',root/'build/task-store-probe')}
assert before==after
value={'cases':rows,'binarySha256':before,'binaryUnchanged':True,'passed':all(row['exitCode']==0 for row in rows),'releaseQualified':False,'deliveryComplete':False}
(output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n')
raise SystemExit(0 if value['passed'] else 1)
'''
 with (output/'remote-driver.log').open('xb') as log:code=subprocess.run(ssh+['python3 -'],input=program.encode('utf-8'),stdout=log,stderr=subprocess.STDOUT,timeout=7200).returncode
 archive_out=output/'results.tar.gz'
 with archive_out.open('xb') as data:subprocess.run(ssh+['tar czf - -C /home/dukto/state-use-r104 results build/Testing/QtTest build/Testing/Temporary/LastTest.log'],stdout=data,check=True,timeout=120)
 with tarfile.open(archive_out) as data:
  for member in data:
   path=PurePosixPath(member.name);assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name;assert member.isdir() or member.isfile()
   if member.isfile():
    assert member.size<=32*1024**2;target=output/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data.extractfile(member).read())
 shutil.copyfile(Path(__file__),output/'validation-driver.py')
 value={'remoteExitCode':code,'sourceSnapshotSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'passed':code==0,'releaseQualified':False,'deliveryComplete':False}
 (output/'collection-result.json').write_text(json.dumps(value,indent=2)+'\n','utf-8');print(json.dumps(value),flush=True)
 return code
if __name__=='__main__':raise SystemExit(main())
