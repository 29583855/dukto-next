"""日期：2026-11-07；独立Ubuntu使用精确R113原对象与明确候选源验证真实扫描清理及CLI。"""
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import runpy
import subprocess
import tarfile

ROOT = Path.cwd()
OUT = ROOT / '.cache/upload-scan-r116-ubuntu'
REMOTE = '/home/dukto/upload-scan-r116-validation'


# 日期：2026-11-07；所有既有源对象逐一对比R113实际源码摘要，候选三源及CLI/测试独立编译。
def main():
    OUT.mkdir(exist_ok=False)
    ssh = runpy.run_path('.cache/validate-exit-state-r98-final-glibc.py')['SSH']
    repo = ROOT / '.cache/github-29583855-dukto-next-r28'
    baseline = '400e0621745dc250b3390ad01a5e9f47dfc924a4'
    core_names = [line.strip() for line in (ROOT/'CMakeLists.txt').read_text('utf-8').splitlines()
                  if line.strip().startswith('src/core/') and line.strip().endswith('.cpp')]
    replaced = ['src/core/uploadmanifest.cpp', 'src/core/sourcefile.cpp', 'src/core/privatestore.cpp']
    frozen = {}
    for name in core_names:
        if name not in replaced:
            raw = subprocess.check_output(['git','show',baseline+':'+name],cwd=repo)
            assert raw == (ROOT/name).read_bytes(), name
            frozen[name] = hashlib.sha256(raw).hexdigest()
    names = core_names + [str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'src/core').glob('*.h')]
    names += ['src/cli/main.cpp','src/cli/input.cpp','src/cli/input.h','src/cli/servicecommands.cpp',
              'src/cli/servicecommands.h','tests/upload_scan_cleanup_tests.cpp']
    cmake = '''cmake_minimum_required(VERSION 3.20)
project(UploadScanValidation LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_AUTOMOC ON)
find_package(Qt5 5.15 REQUIRED COMPONENTS Core Network Sql Test)
find_package(OpenSSL REQUIRED COMPONENTS Crypto)
add_library(candidate STATIC
''' + ''.join('    '+name+'\n' for name in replaced) + ')\n'
    cmake += 'target_sources(candidate PRIVATE\n' + ''.join(
        '    /home/dukto/private-read-r113-diagnostic/build/CMakeFiles/dukto-core.dir/'+name+'.o\n'
        for name in frozen) + ')\n'
    cmake += '''target_include_directories(candidate PUBLIC src)
target_link_libraries(candidate PUBLIC Qt5::Core Qt5::Network Qt5::Sql OpenSSL::Crypto)
target_compile_definitions(candidate PUBLIC DUKTO_VERSION="0.1.0")
add_executable(upload-scan-cleanup-tests tests/upload_scan_cleanup_tests.cpp)
target_link_libraries(upload-scan-cleanup-tests PRIVATE candidate Qt5::Test)
add_executable(dukto-cli src/cli/main.cpp src/cli/input.cpp src/cli/servicecommands.cpp)
target_link_libraries(dukto-cli PRIVATE candidate)
'''
    files = {name:(ROOT/name).read_bytes() for name in names}
    files['CMakeLists.txt'] = cmake.encode()
    files['frozen-object-inputs.json'] = json.dumps(frozen).encode()
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w:gz') as tar:
        for name,raw in files.items():
            item=tarfile.TarInfo(name); item.size=len(raw); tar.addfile(item,io.BytesIO(raw))
    (OUT/'source.tar.gz').write_bytes(archive.getvalue())
    subprocess.run(ssh+['mkdir '+REMOTE],capture_output=True,check=True,timeout=30)
    subprocess.run(ssh+['tar xzf - -C '+REMOTE],input=archive.getvalue(),capture_output=True,check=True,timeout=30)
    verify = '''import hashlib,json
from pathlib import Path
root=Path('/home/dukto/upload-scan-r116-validation')
baseline=Path('/home/dukto/private-read-r113-diagnostic')
rows=[]
for name,digest in json.loads((root/'frozen-object-inputs.json').read_text()).items():
    assert hashlib.sha256((baseline/name).read_bytes()).hexdigest()==digest,name
    obj=baseline/'build/CMakeFiles/dukto-core.dir'/(name+'.o')
    assert obj.is_file(),name
    rows.append({'source':name,'sourceSha256':digest,'objectSha256':hashlib.sha256(obj.read_bytes()).hexdigest()})
(root/'frozen-objects-verified.json').write_text(json.dumps(rows,indent=2)+'\\n')
'''
    verified=subprocess.run(ssh+['python3 -'],input=verify.encode(),capture_output=True,timeout=30)
    (OUT/'object-verification.log').write_bytes(verified.stdout+verified.stderr)
    assert verified.returncode==0, verified.stderr.decode('utf-8','replace')
    script='''set -eu
cd /home/dukto/upload-scan-r116-validation
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release > configure.log 2>&1
nice -n 10 cmake --build build --parallel 2 > build.log 2>&1
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-before.sha256
build/upload-scan-cleanup-tests -o qt.log,txt -o qt.xml,junitxml
sha256sum build/dukto-cli build/upload-scan-cleanup-tests > binaries-after.sha256
cmp binaries-before.sha256 binaries-after.sha256
'''
    (OUT/'driver.sh').write_text(script,'utf-8')
    with (OUT/'driver.log').open('xb') as log:
        result=subprocess.run(ssh+['sh -s'],input=script.encode(),stdout=log,stderr=subprocess.STDOUT,timeout=600)
    for name in ['configure.log','build.log','qt.log','qt.xml','binaries-before.sha256','binaries-after.sha256','frozen-objects-verified.json']:
        fetched=subprocess.run(ssh+['cat '+REMOTE+'/'+name],capture_output=True,timeout=30)
        if fetched.returncode==0:
            (OUT/name).write_bytes(fetched.stdout)
    value={'observedUtc':datetime.now(timezone.utc).isoformat(),'baselineObjectSourceCommit':baseline,
           'frozenObjectInputs':len(frozen),'candidateCompiledSources':replaced,'exitCode':result.returncode,
           'testSourceSha256':hashlib.sha256(files['tests/upload_scan_cleanup_tests.cpp']).hexdigest(),
           'deliveryComplete':False,'releaseQualified':False}
    (OUT/'receipt.json').write_text(json.dumps(value,indent=2)+'\n','utf-8')
    print(json.dumps(value),flush=True)


if __name__=='__main__':
    main()
