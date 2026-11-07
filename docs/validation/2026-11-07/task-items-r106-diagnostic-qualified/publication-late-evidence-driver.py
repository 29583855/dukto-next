"""日期：2026-11-07；将刚终止的R104 Windows原始失败并入尚未提交的证据批次。"""
import json
from pathlib import Path
import runpy
import shutil
import subprocess


# 日期：2026-11-07；保留50份真实通过报告和旧夹具失败，重新生成显式暂存范围以便再次完整核验。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == 'b7375f65f418727fa74af1556a913996c6c6a4e0'
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    folder = root / 'docs/validation/2026-11-07/state-use-r104-windows-terminal'
    path = folder / 'subset-verification.json'
    value = json.loads(path.read_text('utf-8'))
    assert value['originalJobConclusion'] == 'failure' and value['verificationPassedWithinExplicitSubset']
    assert len(value['verifiedPassedProtocolReports']) == 50 and not value['fullR104ProtocolQualified']
    checkpoint = root / 'docs/ci-verification-20261107-r106.json'
    data = json.loads(checkpoint.read_text('utf-8'))
    data['r104WindowsOriginalFailure'] = proof(path)
    data['allR104NativeJobsTerminalFailure'] = True
    save(checkpoint, data)
    manifest = root / 'docs/ci-verification-20261107-r105.json'
    data = json.loads(manifest.read_text('utf-8'))
    data['r104WindowsFailureSubsetEvidence'] = proof(path)
    save(manifest, data)
    index = root / 'docs/current-validation.json'
    data = json.loads(index.read_text('utf-8'))
    data['stateUseR104'].update(windowsTerminalEvidence=proof(path), originalWindowsJobConclusion='failure',
                                originalNativeRunConclusion='failure', allOriginalNativeJobsCompleted=True)
    data['taskItemsFixtureR105']['manifest'] = proof(manifest)
    data['evidenceCheckpointR106'] = proof(checkpoint)
    save(index, data)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state['taskItemsFixtureR105'] = json.loads(manifest.read_text('utf-8'))
    state['evidenceCheckpointR106'] = proof(checkpoint)
    save(state_path, state)
    note = '\n- [x] 本批提交前R104 Windows也实际终态failure；51项协议中50份通过报告已逐摘要收验，唯一失败仍为旧task-items的原目录非空假设。四个R104原生作业现在全部终止且失败，原件继续保留；不影响按R105独立收验的新运行。\n'
    authors = ['开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md']
    for name in authors:
        update(root / name, lambda text: text.rstrip() + note)
    receipt = root / 'docs/validation/2026-11-07/task-items-r106-diagnostic-qualified'
    shutil.copyfile(root / '.cache/r104-native-run.json', receipt / 'r104-final-failure-observation.json')
    shutil.copyfile(__file__, receipt / 'publication-late-evidence-driver.py')
    names_path = root / '.cache/r106-evidence-publish-files.json'
    names = set(json.loads(names_path.read_text('utf-8')))
    names.update(p.relative_to(root).as_posix() for p in folder.rglob('*') if p.is_file()
                 and p.suffix in ('.json', '.xml', '.log', '.txt', '.sha256', '.py', '.png'))
    names.update((receipt / name).relative_to(root).as_posix() for name in
                 ('r104-final-failure-observation.json', 'publication-late-evidence-driver.py'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    names_path.write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r106-evidence-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    print(json.dumps({'explicitFiles': len(names), 'r104WindowsPassedSubset': 50, 'originalJobConclusion': 'failure'}))


if __name__ == '__main__':
    main()
