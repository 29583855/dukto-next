"""日期：2026-11-08；收验真实Windows完整计量及20轮变更拒绝，不掩盖原28/29核心失败。"""
from datetime import datetime,timezone
import hashlib,io,json
from pathlib import Path,PurePosixPath
import runpy,stat
import xml.etree.ElementTree as ET
import zipfile


# 日期：2026-11-08；官方ZIP按摘要核对，限定普通相对文本原件及总大小。
def extract(raw,output):
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names=set();total=0
        for member in archive.infolist():
            name=PurePosixPath(member.filename);assert not name.is_absolute() and '..' not in name.parts and ':' not in member.filename
            assert member.filename not in names and not stat.S_ISLNK(member.external_attr>>16);names.add(member.filename)
            total+=member.file_size;assert member.file_size<=32*1024**2 and total<=128*1024**2
            if member.is_dir():continue
            assert name.suffix in ['.log','.xml','.json','.txt']
            path=output/member.filename;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(archive.read(member))


# 日期：2026-11-08；XML失败/跳过均拒绝，不能只读取一行Totals就授予专项资格。
def xml(path,count):
    tree=ET.fromstring(path.read_bytes());assert tree.get('failures')=='0' and tree.get('errors')=='0'
    cases=tree.findall('testcase');assert len(cases)==count and all(case.get('result')=='pass' for case in cases)


# 日期：2026-11-08；按精确源、实际作业与独立20份原件核验，二进制SHA前后保持。
def main():
    root=Path.cwd();repo=root/'.cache/github-29583855-dukto-next-r28';request=runpy.run_path(str(root/'.cache/github-actions-r28.py'))['request'];base='/repos/29583855/dukto-next'
    selected=json.loads((root/'.cache/r119-windows-regression-run.json').read_bytes());path=base+'/actions/runs/'+str(selected['id']);run=request(path)
    source=json.loads((root/'.cache/r119-windows-source-publication.json').read_bytes())['sourceCommit'];assert run['head_sha']==source and run['run_attempt']==1
    jobs=request(path+'/jobs?per_page=100')['jobs'];job,=jobs
    if run['status']!='completed':print(json.dumps({'runId':run['id'],'status':run['status'],'active':[s['name'] for s in job['steps'] if s['status']=='in_progress']}),flush=True);return
    output=repo/'docs/validation/2026-11-07/sqlite-vfs-r119-windows-regression';output.mkdir(exist_ok=False)
    log=request(base+'/actions/jobs/'+str(job['id'])+'/logs',binary=True);(output/'job.log').write_bytes(log)
    assert run['conclusion']==job['conclusion']=='success',job['conclusion']
    artifact,=request(path+'/artifacts?per_page=100')['artifacts'];assert artifact['name']=='windows-observable-storage' and not artifact['expired']
    raw=request(base+'/actions/artifacts/'+str(artifact['id'])+'/zip',binary=True);digest=hashlib.sha256(raw).hexdigest();assert artifact['digest']=='sha256:'+digest
    archive=root/'.cache/r119-windows-observable-storage.zip';assert not archive.exists();archive.write_bytes(raw);extract(raw,output)
    ctest,=output.rglob('ctest.log');assert '100% tests passed' in ctest.read_text('utf-8-sig') and 'out of 1' in ctest.read_text('utf-8-sig')
    full,=output.rglob('state-storage-tests.log');assert 'Totals: 11 passed, 0 failed, 0 skipped' in full.read_text('utf-8-sig');xml(full.with_suffix('.xml'),10)
    stamp,=output.rglob('source-commit.txt');assert stamp.read_text('utf-8-sig').strip()==source
    before,=output.rglob('before.json');after,=output.rglob('after.json');a=json.loads(before.read_text('utf-8-sig'));b=json.loads(after.read_text('utf-8-sig'));assert a==b and len(a)==2
    for item in a:assert item['Algorithm']=='SHA256' and len(item['Hash'])==64
    repeats=[]
    for number in range(1,21):
        path,=output.rglob('repeat-'+str(number)+'.log');assert 'Totals: 3 passed, 0 failed, 0 skipped' in path.read_text('utf-8-sig');assert 'PASS   : StateStorageTests::maintenanceCancellationAndMutation()' in path.read_text('utf-8-sig');xml(path.with_suffix('.xml'),3);repeats.append({'iteration':number,'logSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'xmlSha256':hashlib.sha256(path.with_suffix('.xml').read_bytes()).hexdigest(),'passed':True})
    receipt={'observedUtc':datetime.now(timezone.utc).isoformat(),'sourceCommit':source,'run':{key:run[key] for key in ['id','head_sha','status','conclusion','html_url']},'qualified':True,'fullStateStorageRowsPassed':11,'stateStorageSkipped':0,'directoryMutationRepeated':20,'binaryHashesBeforeAndAfter':a,'binaryUnchanged':True,'artifactId':artifact['id'],'artifactSha256':digest,'repeats':repeats,'scope':'complete Windows state-storage target and 20 real timestamp mutation rejections; original other 28 core targets and original failure remain separate','deliveryComplete':False,'releaseQualified':False}
    (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8')
    (output/'verification-driver.py').write_bytes(Path(__file__).read_bytes());print(json.dumps({'qualified':True,'storageRows':11,'mutationRepeats':20,'sourceCommit':source}),flush=True)


if __name__=='__main__':main()
