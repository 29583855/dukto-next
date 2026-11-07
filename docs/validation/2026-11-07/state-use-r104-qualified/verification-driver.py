"""日期：2026-11-07；严格核对R104两套Windows原始核心和真实进程报告，不授予未执行平台资格。"""
from datetime import datetime,timezone
from pathlib import Path
import hashlib,json,re,runpy,shutil,subprocess

# 日期：2026-11-07；绑定所有构建输入、原始退出和修正前失败，避免用子项替代完整交付。
def main():
 root=Path.cwd();base=root/'docs/validation/2026-11-07';source=base/'state-use-r104-windows-recheck'
 result=json.loads((source/'driver-result.json').read_text('utf-8'));assert not result['passed'] and result['buildInputsUnchanged']
 recheck=base/'state-use-r104-process-recheck';fixed=json.loads((recheck/'driver-result.json').read_text('utf-8'));assert fixed['passed'] and fixed['buildInputsUnchanged'] and not fixed['productionCodeChangedForCorrection'] and not fixed['freshFull23TargetsRerun']
 inputs=json.loads((recheck/'build-inputs.json').read_text('utf-8'));assert len(inputs)==213
 prior=json.loads((source/'build-inputs.json').read_text('utf-8'));assert [a['path'] for a,b in zip(inputs,prior) if a!=b]==['tests/task_store_integration.py']
 checkout=root/'.cache/github-29583855-dukto-next-r28';changed=[]
 for row in inputs:
  raw=(root/row['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['sha256']
  previous=subprocess.check_output(['git','show','HEAD:'+row['path']],cwd=checkout)
  if raw!=previous:changed.append(row['path'])
 assert sorted(changed)==sorted(['src/core/privatestore.h','src/core/privatestore.cpp','tests/identity_tests.cpp','tests/task_store_probe.cpp','tests/task_store_integration.py']),changed
 helper=runpy.run_path('.cache/finalize-skip-items-r84.py');proof=helper['proof'];verify_xml=runpy.run_path('.cache/verify-diagnostics-r103.py')['verify_xml'];rows=[]
 for label in ['ucrt','msvc']:
  row,=[r for r in result['cases'] if r['toolchain']==label];assert not row['passed']
  correction,=[r for r in fixed['cases'] if r['toolchain']==label];assert correction['passed'] and correction['exitCode']==0 and correction['allBuildExecutablesUnchanged']
  binary=root/('build/windows-ucrt' if label=='ucrt' else 'build/windows/Release')
  for name,digest in correction['binarySha256'].items():assert hashlib.sha256((binary/name).read_bytes()).hexdigest()==digest
  for key,value in row.items():
   if key.endswith('ExitCode'):assert value==(1 if key=='task-storeExitCode' else 0),(label,key,value)
  target=source/label
  assert re.search(r'^100% tests passed(?:, 0 tests failed)? out of 23$',(target/'ctest.log').read_text('utf-8-sig'),re.M)
  files=sorted((target/'QtTest').glob('*.xml'));assert len(files)==22
  for path in files:verify_xml(path)
  log=(target/'QtTest/identity-tests.log').read_text('utf-8-sig').splitlines();assert log.count('PASS   : IdentityTests::stateDirectoryUseGuard()')==1
  task=json.loads((recheck/label/'task-store.json').read_text('utf-8'));assert task['passed'] and task['stateDirectoryUse']['sharedProcesses']==8
  for key in ['exclusiveRefusedUntilLastReaderExited','sharedAndExclusiveRefusedDuringMaintenance','recoveredAfterKill','ordinaryDataUnchanged','nonemptyGuardRefusedWithoutTruncation']:assert task['stateDirectoryUse'][key]
  for name in ['doctor','service']:assert json.loads((target/(name+'.json')).read_text('utf-8'))['passed']
  rows.append({'toolchain':label,'coreTargets':23,'qtXmlReports':22,'stateUseProcesses':8,'processReport':proof(recheck/label/'task-store.json'),'doctor':proof(target/'doctor.json'),'service':proof(target/'service.json')})
 formats=json.loads((root/'.cache/state-use-r104-before/formats.json').read_text('utf-8'))
 for row in formats:
  raw=(root/row['path']).read_bytes();assert raw.startswith(b'\xef\xbb\xbf')==row['bom'];assert (b'\r\n' in raw)==row['crlf'];raw.decode('utf-8-sig');assert b'\r' not in raw
 audit=json.loads((base/'state-use-r104-source-audit-final.json').read_text('utf-8'));assert len(audit['files'])==207 and not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
 failure=json.loads((base/'state-use-r104-correction/failure.json').read_text('utf-8'));assert failure['initialWindowsDriverExitCode']==1 and not failure['productionCodeChangedForCorrection']
 output=base/'state-use-r104-qualified';output.mkdir(exist_ok=False)
 receipt={'observedUtc':datetime.now(timezone.utc).isoformat(),'passed':True,'basedOnPublishedCommit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=checkout).decode().strip(),'buildInputs':inputs,'windows':rows,'encodingAndNewlinesPreserved':True,'originalTestCompilationFailureRetained':True,'originalProcessFixtureFailureRetained':True,'freshFull23TargetsRerunAfterPythonCorrection':False,'allBuildExecutablesUnchangedForPythonCorrection':True,'sourceAudit':proof(base/'state-use-r104-source-audit-final.json'),'sharedReadersAndExclusiveMaintenanceImplemented':True,'expiredTaskCollectionImplemented':False,'cliCleanupImplemented':False,'mixedOldVersionsProtected':False,'allPlatformR104RuntimeVerified':False,'entireR04Qualified':False,'releaseQualified':False,'deliveryComplete':False}
 (output/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n','utf-8');shutil.copyfile(Path(__file__),output/'verification-driver.py');print(json.dumps({'passed':True,'windowsToolchains':2,'coreTargetsEach':23,'inputs':len(inputs)}))
if __name__=='__main__':main()
