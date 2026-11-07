
from pathlib import Path
import hashlib,json,os,runpy,subprocess,time
root=Path('/home/dukto/secure-ready-r107');root.mkdir(exist_ok=False)
runpy.run_path('/home/dukto/source-install-secure-ready-r107.py')['install'](root,Path('/home/dukto/source-secure-ready-r107.tar.gz'))
output=root/'results';output.mkdir();runtime=root/'runtime';runtime.mkdir(mode=0o700)
env=os.environ.copy();env.update(QT_QPA_PLATFORM='offscreen',XDG_RUNTIME_DIR=str(runtime));rows=[]
# 日期：2026-11-07；实际命令结束即记录，保留原门槛、失败及stderr。
def check(name,args,timeout=1800):
    started=time.monotonic()
    with (output/(name+'.log')).open('xb') as log:
        p=subprocess.run(args,cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=timeout)
    rows.append({'name':name,'exitCode':p.returncode,'seconds':round(time.monotonic()-started,3)})
    (output/'exit-codes.json').write_text(json.dumps(rows,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(rows[-1]),flush=True);return p.returncode
assert check('configure',['cmake','-S','.','-B','build','-G','Ninja','-DCMAKE_BUILD_TYPE=Release','-DDUKTO_BUILD_GUI=OFF'])==0
assert check('build',['cmake','--build','build','--target','dukto-cli','secure-channel-probe','--parallel','2'])==0
before={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in ('dukto-cli','secure-channel-probe')}
for name,script,exe,extra in [('secure-channel','secure_channel_integration','secure-channel-probe',[]),
                             ('task-items','task_items_integration','dukto-cli',[]),
                             ('transfer16','transfer_integration','dukto-cli',['--threads','16'])]:
    check(name,['python3','-X','utf8','tests/'+script+'.py',str(root/'build'/exe),*extra,'--report',str(output/(name+'.json'))],600)
after={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in before};assert before==after
value={'cases':rows,'binarySha256':before,'binaryUnchanged':True,'independentFullCoreSuiteRun':False,'passed':all(row['exitCode']==0 for row in rows),'releaseQualified':False,'deliveryComplete':False}
(output/'driver-result.json').write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8');raise SystemExit(0 if value['passed'] else 1)
