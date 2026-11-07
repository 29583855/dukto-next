"""日期：2026-11-07；旧原生构建真实终止后，按冻结快照只更新两处测试输入并复验Ubuntu。"""
from pathlib import Path,PurePosixPath
import hashlib,json,runpy,shutil,subprocess,tarfile

# 日期：2026-11-07；不重复安装依赖、不触及长期冻结目录；复用按摘要验证的未变生产对象。
def main():
 root=Path.cwd();snapshot=runpy.run_path('scripts/source_snapshot.py');output=root/'docs/validation/2026-11-07/state-use-r104-glibc-recheck';output.mkdir(exist_ok=False)
 old=snapshot['read_archive'](root/'.cache/source-state-use-r104.tar.gz')[0]['files']
 archive=root/'.cache/source-state-use-r104-final.tar.gz';snapshot['create'](root,archive);new=snapshot['read_archive'](archive)[0]['files']
 inputs=json.loads((root/'docs/ci-verification-20261107-r104.json').read_text('utf-8'))['buildInputs']
 changed=[row['path'] for row in inputs if old[row['path']]!=new[row['path']]];assert sorted(changed)==['tests/identity_tests.cpp','tests/task_store_integration.py'],changed
 (output/'build-inputs.json').write_text(json.dumps(inputs,indent=2)+'\n','utf-8')
 ssh=runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
 with archive.open('rb') as data:subprocess.run(ssh+['set -C; cat > /home/dukto/source-state-use-r104-final.tar.gz'],stdin=data,check=True,timeout=120)
 program=r'''
from pathlib import Path
import hashlib,json,os,runpy,subprocess
root=Path('/home/dukto/state-use-r104');initial=root/'results'
rows=json.loads((initial/'exit-codes.json').read_text());assert rows[0]=={'name':'configure','exitCode':0} and rows[1]['name']=='build' and rows[1]['exitCode']!=0
assert 'PrivateStore' in (initial/'build.log').read_text() and 'identity_tests.cpp' in (initial/'build.log').read_text()
# 日期：2026-11-07；旧构建树必须无存活编译进程，不能在原ninja读取输入时替换测试文件。
for proc in Path('/proc').iterdir():
 if not proc.name.isdecimal():continue
 try:
  cwd=(proc/'cwd').resolve()
  if (cwd==root or root in cwd.parents) and any(word in (proc/'comm').read_text() for word in ('cmake','ninja','cc1plus','c++')):raise AssertionError('initial build still active')
 except OSError:pass
change=runpy.run_path('/home/dukto/source-install-state-use-r104.py')['install'](root,Path('/home/dukto/source-state-use-r104-final.tar.gz'))
output=root/'recheck-results';output.mkdir(exist_ok=False);(output/'source-update.json').write_text(json.dumps(change,indent=2)+'\n')
runtime=root/'recheck-runtime';runtime.mkdir(mode=0o700);env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',XDG_RUNTIME_DIR=str(runtime));rows=[]
# 日期：2026-11-07；真实退出码先持久保存，任一失败使整个复验失败。
def check(name,args,timeout=1800):
 with (output/(name+'.log')).open('xb') as log:p=subprocess.run(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
 rows.append({'name':name,'exitCode':p.returncode});(output/'exit-codes.json').write_text(json.dumps(rows,indent=2)+'\n');print(json.dumps(rows[-1]),flush=True);return p.returncode
assert check('build',['cmake','--build','build','--parallel','2'])==0
before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'build/dukto-cli',root/'build/task-store-probe')}
check('ctest',['ctest','--test-dir','build','--output-on-failure'],3600)
for name,script,exe in [('task-store','task_store_integration','task-store-probe'),('doctor','doctor_integration','dukto-cli'),('service','service_integration','dukto-cli')]:check(name,['python3','-X','utf8','tests/'+script+'.py',str(root/'build'/exe),'--report',str(output/(name+'.json'))],300)
after={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'build/dukto-cli',root/'build/task-store-probe')};assert before==after
value={'cases':rows,'binarySha256':before,'binaryUnchanged':True,'passed':all(row['exitCode']==0 for row in rows),'releaseQualified':False,'deliveryComplete':False}
(output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n');raise SystemExit(0 if value['passed'] else 1)
'''
 with (output/'remote-driver.log').open('xb') as log:code=subprocess.run(ssh+['python3 -'],input=program.encode('utf-8'),stdout=log,stderr=subprocess.STDOUT,timeout=7200).returncode
 archive_out=output/'results.tar.gz'
 with archive_out.open('xb') as data:subprocess.run(ssh+['tar czf - -C /home/dukto/state-use-r104 results recheck-results build/Testing/QtTest build/Testing/Temporary/LastTest.log'],stdout=data,check=True,timeout=120)
 with tarfile.open(archive_out) as data:
  for member in data:
   path=PurePosixPath(member.name);assert not path.is_absolute() and '..' not in path.parts and ':' not in member.name;assert member.isdir() or member.isfile()
   if member.isfile():
    assert member.size<=32*1024**2;target=output/member.name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data.extractfile(member).read())
 value={'remoteExitCode':code,'sourceSnapshotSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'changedBuildInputs':changed,'passed':code==0,'releaseQualified':False,'deliveryComplete':False}
 (output/'collection-result.json').write_text(json.dumps(value,indent=2)+'\n','utf-8');shutil.copyfile(Path(__file__),output/'validation-driver.py');print(json.dumps(value),flush=True);return code
if __name__=='__main__':raise SystemExit(main())
