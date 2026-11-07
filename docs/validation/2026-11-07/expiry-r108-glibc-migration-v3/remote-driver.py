
from pathlib import Path
import hashlib,json,subprocess,time
root=Path('/home/dukto/expiry-r108'); out=Path('/home/dukto/expiry-r108-migration-v3')
names=['dukto-cli','task-store-tests','expired-task-cleanup-tests','task-store-probe']
before={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in names}
started=time.monotonic()
with (out/'migration.log').open('xb') as log:
    code=subprocess.run(['python3','-X','utf8',str(out/'task_store_integration.py'),str(root/'build/task-store-probe'),'--report',str(out/'migration.json')],cwd=out,stdout=log,stderr=subprocess.STDOUT,timeout=600).returncode
after={name:hashlib.sha256((root/'build'/name).read_bytes()).hexdigest() for name in names}
assert before==after
result={'exitCode':code,'seconds':round(time.monotonic()-started,3),'binarySha256':before,'binaryUnchanged':True,'fixtureSha256':hashlib.sha256((out/'task_store_integration.py').read_bytes()).hexdigest(),'passed':code==0,'releaseQualified':False,'deliveryComplete':False}
(out/'recheck-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result),flush=True)
raise SystemExit(code)
