"""日期：2026-11-07；发布独立Ubuntu清理终态与R107 ARM真实失败，应用216输入保持。"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import re
import runpy
import shutil
import subprocess

PARENT = '73cd10ac95be6c97fd67134ba14b6edee4b2c189'
LABEL = 'r108-terminal-evidence'


# 日期：2026-11-07；只根据独立回执更新当前快照，失败记录及未完范围保持显式。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    publication = json.loads((root / '.cache/r108-expiry-published-tree-verification.json').read_text('utf-8'))
    assert publication['passed'] and publication['repositoryCommit'] == PARENT
    base = root / 'docs/validation/2026-11-07'
    ubuntu_path = base / 'expiry-r108-glibc/receipt.json'
    arm_path = base / 'secure-ready-r107-arm-failure/receipt.json'
    ubuntu = json.loads(ubuntu_path.read_text('utf-8'))
    arm = json.loads(arm_path.read_text('utf-8'))
    assert ubuntu['passed'] and ubuntu['coreTargetsVerified'] == 2 and ubuntu['buildInputsVerifiedOnVm'] == 216
    assert ubuntu['originalDriverExitCode'] == 1 and ubuntu['correctedFixtureRecheckExitCode'] == 0
    assert arm['failureVerifiedAsFailure'] and not arm['fullRegressionPassed']
    assert arm['passingReportsVerified'] == 46 and arm['failingCase']['name'] == 'overwrite-faults'
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    authors = ['README.md', '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
               'docs/ci-verification-20261107-r108.json', 'docs/current-validation.json']
    backup = root / '.cache/r108-terminal-docs-before'
    backup.mkdir(exist_ok=False)
    for name in authors:
        target = backup / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    manifest_path = root / 'docs/ci-verification-20261107-r108.json'
    manifest = json.loads(manifest_path.read_text('utf-8'))
    for row in manifest['buildInputs']:
        raw = (root / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        assert subprocess.check_output(['git', 'show', PARENT + ':' + row['path']], cwd=checkout) == raw
    manifest.update(sourceCommit=PARENT, observedUtc=datetime.now(timezone.utc).isoformat(),
                    independentUbuntuPending=False, independentUbuntuEvidence=proof(ubuntu_path),
                    independentUbuntuCleanupAndMigrationQualified=True,
                    r107ArmFailure=proof(arm_path), r107FullNativeRegressionPassed=False,
                    nativeCIPending=True, releaseQualified=False, deliveryComplete=False)
    save(manifest_path, manifest)
    note = '''

## R108独立Ubuntu与R107 ARM失败终态（2026-11-07）

- [x] 独立Ubuntu从新隔离源码编译成功，任务库/过期清理两个核心目标及18行清理测试通过；C++14、Qt5.15.13、216输入及二进制身份逐项核验。原八进程夹具仍断言版本二而退出1，修正版在独立目录用同一二进制退出0，版本一/二各八进程迁移及原字段保持均通过。原失败没有覆盖，未宣称重新执行完整核心或原小文件task-items。[独立回执](docs/validation/2026-11-07/expiry-r108-glibc/receipt.json)。
- [x] R107 ARM完整作业真实失败已保留，官方附件摘要、精确源码脚本与47条命令逐一核对。46项报告通过；`overwrite-faults`退出1且没有报告，测试在改配根时实际收到`code=6/stage=read`的文件身份变化错误，旧断言只接受3/4。已定位精确夹具失败，尚未修改该断言或授予完整Mac回归通过。[失败原件](docs/validation/2026-11-07/secure-ready-r107-arm-failure/receipt.json)。
- [x] 本轮R108应用源码已上传精确提交`73cd10ac95be6c97fd67134ba14b6edee4b2c189`，公开main及整树已独立核对；自动四平台[运行42332515396](https://github.com/29583855/dukto-next/actions/runs/42332515396)继续，不重复派发。
- [ ] R107 Intel/Windows终态、R108新原生及ARM精确故障断言继续。独立Ubuntu原90秒超时、全局磁盘预算、其余GC范围、完整R6/GUI、物理LAN/3×3、各平台24h和正式分发未完成。两套冻结长测本轮只读观察仍运行，99/73轮约29774/24504秒不代表24h终态。
'''

    # 日期：2026-11-07；当前快照准确表达独立子项成功和原生完整失败，不复用旧平台包授予新源码资格。
    def plan(text):
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R108过期上传清理通过双Windows及独立Ubuntu专项；R107 ARM完整作业有精确故障夹具失败，R108新原生继续。', text, count=1, flags=re.M)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R108过期服务器上传临时正文维护CLI通过双Windows各24核心及独立Ubuntu两个核心/八进程迁移专项，原失败保留。R107 ARM完整回归在覆盖故障测试旧断言失败（实际身份变化错误6），46项报告通过；不能认定完整Mac通过。R108四平台新运行继续。含依赖包仍为双Mac R105、Windows/Linux R100。[本轮证据](docs/ci-verification-20261107-r108.json)。整体未完成。' + text[end:]
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: re.sub(r'^公开仓库为.*$', '公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。R108[过期上传临时文件维护CLI](docs/过期任务临时文件清理.md)通过双Windows和独立Ubuntu专项；新四平台CI继续。R107 ARM完整故障测试有精确断言失败并保留，GUI/CLI编译结果不变；[含依赖双Mac预览](docs/macOS独立预览包.md)仍为R105。完整状态见[计划](开发计划与进度.md)和[本轮证据](docs/ci-verification-20261107-r108.json)。', text, count=1, flags=re.M))
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index['expiredUploadCleanupR108'].update(manifest=proof(manifest_path), independentUbuntuPending=False,
                                           independentUbuntuEvidence=proof(ubuntu_path),
                                           independentUbuntuCleanupAndMigrationQualified=True)
    index['secureReadyR107'].update(armFailure=proof(arm_path), fullNativeRegressionPassed=False)
    index.update(currentSourceCommit=PARENT, currentGuiSourceCommit=PARENT, currentGuiSourceCommitPending=False,
                 observedUtc=manifest['observedUtc'],
                 currentSourceStage='R108 Windows and independent Ubuntu cleanup qualified; R107 ARM precise fault fixture failed; new native pending',
                 releaseQualified=False, deliveryComplete=False)
    save(index_path, index)
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(expiredUploadCleanupR108=manifest, goalStatus='active',
                 workingSourceStage=index['currentSourceStage'], releaseQualified=False, deliveryComplete=False)
    save(state_path, state)
    qualified = base / 'expiry-r108-qualified'
    shutil.copyfile(__file__, qualified / 'terminal-publication-preparation-driver.py')
    shutil.copyfile(root / '.cache/r108-native-run.json', qualified / 'r108-native-observation.json')
    names = set(authors + ['docs/validation/2026-11-06/github-api-push-r108-expiry.json',
                          (qualified / 'terminal-publication-preparation-driver.py').relative_to(root).as_posix(),
                          (qualified / 'r108-native-observation.json').relative_to(root).as_posix()])
    for folder in ('expiry-r108-glibc', 'expiry-r108-glibc-migration-v3', 'secure-ready-r107-arm-failure'):
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*') if path.is_file()
                     and path.suffix in ('.json', '.jsonl', '.xml', '.log', '.txt', '.sha256', '.py', '.png', '.stderr'))
    changes = []
    for name in sorted(names):
        raw = (root / name).read_bytes()
        assert not re.search(rb'-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----|(?:ghp_|github_pat_)[A-Za-z0-9_]{20,}', raw), name
        prior = subprocess.run(['git', 'show', 'HEAD:' + name], cwd=checkout, capture_output=True)
        if prior.returncode == 0 and prior.stdout == raw:
            continue
        changes.append(name)
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    assert not set(changes).intersection(row['path'] for row in manifest['buildInputs'])
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(changes, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in changes))
    template = (root / '.cache/stage-r106-evidence.py').read_bytes()
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes(template.replace(b'r106-evidence', LABEL.encode()))
    print(json.dumps({'explicitFiles': len(changes), 'applicationSourceCommit': PARENT,
                      'all216BuildInputsUnchanged': True, 'r107ArmFullRegressionPassed': False, 'deliveryComplete': False}))


if __name__ == '__main__':
    main()
