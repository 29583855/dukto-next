"""日期：2026-11-07；保留首轮缺对象诊断，补编实际缺失对象再运行同一隔离验证目录。"""
from pathlib import Path
import runpy
import subprocess

root=Path.cwd()
ssh=runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
program='''import hashlib,json
from pathlib import Path
root=Path('/home/dukto/upload-scan-r116-validation')
baseline=Path('/home/dukto/private-read-r113-diagnostic')
rows=[]
missing=[]
for name,digest in json.loads((root/'frozen-object-inputs.json').read_text()).items():
    assert hashlib.sha256((baseline/name).read_bytes()).hexdigest()==digest,name
    obj=baseline/'build/CMakeFiles/dukto-core.dir'/(name+'.o')
    if not obj.is_file():
        missing.append(name)
    else:
        rows.append({'source':name,'sourceSha256':digest,'objectSha256':hashlib.sha256(obj.read_bytes()).hexdigest()})
(root/'frozen-objects-verified.json').write_text(json.dumps(rows,indent=2)+'\\n')
(root/'missing-original-objects.json').write_text(json.dumps(missing,indent=2)+'\\n')
cmake=(root/'CMakeLists.txt').read_text()
for name in missing:
    cmake=cmake.replace('    '+str(baseline/'build/CMakeFiles/dukto-core.dir'/(name+'.o'))+'\\n','    '+name+'\\n')
(root/'CMakeLists.txt').write_text(cmake)
print(json.dumps({'verifiedObjects':len(rows),'missingNowCompiledFromExactSources':missing}))
'''
out=root/'.cache/upload-scan-r116-ubuntu'
result=subprocess.run(ssh+['python3 -'],input=program.encode(),capture_output=True,timeout=30)
(out/'object-verification-retry.log').write_bytes(result.stdout+result.stderr)
print(result.stdout.decode()); print(result.stderr.decode())
assert result.returncode==0
script='''set -eu
cd /home/dukto/upload-scan-r116-validation
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > configure.log 2>&1
nice -n 10 cmake --build build --parallel 2 > build.log 2>&1
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-before.sha256
build/upload-scan-cleanup-tests -o qt.log,txt -o qt.xml,junitxml
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-after.sha256
cmp binaries-before.sha256 binaries-after.sha256
'''
with (out/'driver.log').open('xb') as log:
    result=subprocess.run(ssh+['sh -s'],input=script.encode(),stdout=log,stderr=subprocess.STDOUT,timeout=600)
for name in ['configure.log','build.log','qt.log','qt.xml','binaries-before.sha256','binaries-after.sha256','frozen-objects-verified.json','missing-original-objects.json','CMakeLists.txt']:
    fetched=subprocess.run(ssh+['cat /home/dukto/upload-scan-r116-validation/'+name],capture_output=True,timeout=30)
    if fetched.returncode==0:
        (out/name).write_bytes(fetched.stdout)
print('driverExitCode='+str(result.returncode))
assert result.returncode==0
