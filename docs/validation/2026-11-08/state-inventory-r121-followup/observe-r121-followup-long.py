"""日期：2026-11-08；只读观察冻结长测和依赖漂移，兼容原服务正常终止。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess


# 日期：2026-11-08；核对原Ubuntu执行文件、全部冻结输入和运行库，不重启、不改原件、不覆盖旧观察。
def main():
    root = Path.cwd()
    ssh = runpy.run_path(str(root / '.cache/validate-exit-state-r98-final-glibc.py'))['SSH']
    program = '''import hashlib,json,os
from pathlib import Path
root=Path('/home/dukto/current-linux-r98-long')
launch=json.loads((root/'results/launch.json').read_bytes())
value=json.loads((root/'results/summary24h.json').read_bytes())
selected={key:value.get(key) for key in ('status','passed','rounds','elapsedSeconds','durationRequestedSeconds','requestedChannels','executableSha256','servicePid')}
actual=hashlib.sha256((root/'dukto-cli').read_bytes()).hexdigest()
assert actual==launch['binarySha256']==value['executableSha256']
try:
    running=hashlib.sha256(Path('/proc/'+str(value['servicePid'])+'/exe').read_bytes()).hexdigest()
    assert running==actual
    selected['originalServiceProcessAlive']=True
except FileNotFoundError:
    selected['originalServiceProcessAlive']=False
assert all(hashlib.sha256((root/name).read_bytes()).hexdigest()==sha for name,sha in launch['frozenFiles'].items())
selected['allFrozenInputsUnchanged']=True
changes=[]
for name,sha in launch['runtimeDependencies'].items():
    digest=hashlib.sha256(Path(name).read_bytes()).hexdigest()
    if digest!=sha:
        changes.append({'path':name,'beforeSha256':sha,'currentSha256':digest})
selected['changedRuntimeDependencies']=changes
selected['allRuntimeDependenciesUnchanged']=not changes
terminal=root/'results/driver-result.json'
selected['driverResultExists']=terminal.exists()
print(json.dumps(selected))
'''
    result = subprocess.run(ssh + ['python3 -'], input=program.encode('utf-8'), capture_output=True, timeout=45)
    assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    value = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'ubuntu': json.loads(result.stdout),
             'originalProcessesAndInputsNotModified': True, 'terminalQualificationGrantedByThisObservation': False,
             'deliveryComplete': False, 'releaseQualified': False}
    target = root / '.cache/r121-followup-long-observation.json'
    assert not target.exists()
    target.write_text(json.dumps(value, indent=2) + '\n', 'utf-8')
    print(json.dumps(value))


if __name__ == '__main__':
    main()
