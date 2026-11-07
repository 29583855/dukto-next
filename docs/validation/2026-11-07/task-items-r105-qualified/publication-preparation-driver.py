"""日期：2026-11-07；按真实结果发布夹具修正与原Ubuntu失败证据，生产代码及整体交付状态不变。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess

PARENT = '0e1cf818ec6aea9f842cc6759b9bcd16387d7431'
LABEL = 'r105-task-items'


# 日期：2026-11-07；所有输入及回执先核对，再保留格式更新进度；后续暂存、提交与公开整树另行验证。
def main():
    root = Path.cwd()
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=checkout).decode().strip() == PARENT
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=checkout)
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    update, save, proof = helper['update'], helper['save'], helper['proof']
    base = root / 'docs/validation/2026-11-07'
    receipt_path = base / 'task-items-r105-qualified/receipt.json'
    receipt = json.loads(receipt_path.read_text('utf-8'))
    assert receipt['windowsTargetedFixtureRecheckPassed'] and not receipt['independentUbuntuFixtureRecheckPassed']
    assert receipt['changedBuildInputs'] == ['tests/task_items_integration.py'] and not receipt['productionCodeChanged']
    for row in receipt['buildInputs']:
        assert hashlib.sha256((root / row['path']).read_bytes()).hexdigest() == row['sha256']
    manifest_path = root / 'docs/ci-verification-20261107-r105.json'
    assert not manifest_path.exists()
    manifest = {'planVersion': 'v0.105', 'observedUtc': datetime.now(timezone.utc).isoformat(),
                'basedOnPublishedCommit': PARENT, 'sourceCommitPending': True,
                'buildInputs': receipt['buildInputs'], 'fixtureEvidence': proof(receipt_path),
                'productionCodeChanged': False, 'windowsTargetedFixtureRecheckPassed': True,
                'independentUbuntuFixtureRecheckPassed': False, 'nativeCIPending': True,
                'fullNativeRegressionQualified': False, 'releaseQualified': False, 'deliveryComplete': False}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    note = '''

## R105逐项查询夹具修正及R104 Ubuntu终态（2026-11-07）

- [x] R104 Ubuntu原生作业128230608240真实终态failure已保存，官方附件摘要及原始job.log已验。47项协议中46份通过报告逐摘要核验；唯一失败task-items在缺失状态查询后执行original.rmdir()，没有兼容永久state-use.lock。两项磁盘测试被跳过，未补造报告或将整作业标成通过。[原始失败和子集核验](docs/validation/2026-11-07/state-use-r104-ubuntu-terminal/subset-verification.json)。
- [x] 只修正测试夹具：把本测试临时生成的替代状态目录整体移开，再恢复原目录；严格核对替代目录仅含零字节、普通、单链接state-use.lock。保持永久锁，不放宽未知状态文件检查。213份构建输入仅tests/task_items_integration.py变化，生产代码与原编码/BOM/换行保持。
- [x] 使用未重编译的UCRT/MSVC程序分别完成真实4/16通道双向逐项分页、204条目、重命名摘要、部分结果、陌生主体/撤权拒绝和重启稳定性；两个进程真实exit0且程序摘要前后相同。207份维护源码检查零TODO/占位/简化标记，C++14及clang-format通过。[本轮回执](docs/validation/2026-11-07/task-items-r105-qualified/receipt.json)。
- [ ] 独立Ubuntu定向复验在上传阶段触发原90秒超时，尚未到达修正夹具；原日志、失败退出及随后收集器误要求不存在报告的tar失败均保留，不能记为通过。R104独立Ubuntu完整核心与其余原生作业仍按真实终态收验，R105公开后需新原生CI。双Mac最新已核验编译仍为R104，含依赖部署预览仍为R100。
- [ ] 过期安全回收、全局磁盘配额及全部资源/公平性、完整R6/GUI和原生选择器、物理LAN/3×3、各平台86400秒、依赖源码独立重建、最低干净系统与正式分发继续；deliveryComplete=false、releaseQualified=false。
'''

    # 日期：2026-11-07；当前快照直接显示已知失败，历史记录只追加、不抹去旧测试和旧版本身份。
    def plan(text):
        assert '文档版本：v0.104' in text
        text = text.replace('文档版本：v0.104', '文档版本：v0.105', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R105逐项查询夹具修正通过双Windows定向复验；R104双Mac编译通过，Ubuntu原协议失败及独立复验超时已保留，新原生与完整交付继续。', text, count=1, flags=re.M)
        text = text.replace('v0.104 / 状态目录维护互斥', 'v0.105 / 逐项查询夹具与真实失败收验', 1)
        start = text.index('公开仓库：', text.index('## 当前验收快照'))
        end = text.index('\n\n| 范围', start)
        text = text[:start] + '公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R104精确9c1e941的四原生各23核心/88份Qt及双Mac GUI/CLI编译已验；其Ubuntu完整协议47项中46项通过，task-items夹具失败使整个作业failure，后续磁盘步骤跳过。R105仅修正该夹具，通过双Windows定向复验；独立Ubuntu上传超时未通过，新原生CI待精确公开。213份输入见[本轮清单](docs/ci-verification-20261107-r105.json)。R102/R103完整终态保持原身份，含依赖预览仍为R100，安全回收及整体交付未完成。' + text[end:]
        text = text.replace('R104原生23核心及维护互斥方法通过；R102独立Ubuntu/R100部署另验', 'R104原生23核心及POSIX八进程维护互斥通过；完整协议作业failure，46项通过/1项夹具失败', 1)
        text = text.replace('R98 Windows/Ubuntu冻结CLI执行86400秒；R102/R103完整终态通过，R104完整协议与独立Ubuntu继续', 'R98 Windows/Ubuntu冻结CLI执行86400秒；R104三原生作业和独立Ubuntu继续，R105新原生待验', 1)
        return text.rstrip() + note

    update(root / '开发计划与进度.md', plan)
    for name in ['docs/执行进度.md', 'docs/构建验证摘要.md']:
        update(root / name, lambda text: text.rstrip() + note.replace('(docs/', '('))
    update(root / 'README.md', lambda text: text.replace('## 文档入口', 'R105只修正逐项查询测试对永久占用锁的假设，双Windows定向复验通过；R104 Ubuntu完整协议原失败及独立Ubuntu上传超时均保留，新原生验证继续。[修正与证据](docs/ci-verification-20261107-r105.json)。\n\n## 文档入口', 1))
    update(root / 'docs/macOS独立预览包.md', lambda text: text.replace('完整协议和POSIX八进程/链接拒绝专项仍待原件收验，过期回收及整个R04继续。', 'Ubuntu POSIX八进程/链接拒绝专项已核验；其完整协议作业因task-items旧夹具失败，两项磁盘步骤跳过。R105只修正夹具并通过双Windows定向复验，独立Ubuntu上传超时未通过，新原生CI待验；本节Mac编译产物仍为R104。过期回收及整个R04继续。', 1))
    path = root / 'docs/current-validation.json'
    index = json.loads(path.read_text('utf-8'))
    index.update(planVersion='v0.105', observedUtc=manifest['observedUtc'], currentGuiSourceCommitPending=True,
                 publicVerificationReceipt=manifest_path.relative_to(root).as_posix(),
                 taskItemsFixtureR105={'manifest': proof(manifest_path), 'evidence': proof(receipt_path),
                                      'productionCodeChanged': False, 'nativeCIPending': True,
                                      'independentUbuntuFixtureRecheckPassed': False},
                 currentSourceStage='R105 task-items fixture only; Windows targeted rechecks passed; original Ubuntu protocol failure and independent timeout retained; native CI pending',
                 releaseQualified=False, deliveryComplete=False)
    index['stateUseR104'].update(knownUbuntuJobConclusion='failure', ubuntuProtocolVerifiedPassedReports=46,
                                ubuntuFailedCase='task-items', ubuntuDiskStepsSkipped=True,
                                ubuntuTerminalEvidence=proof(base / 'state-use-r104-ubuntu-terminal/subset-verification.json'))
    save(path, index)
    path = root / '.cache/execution-current.json'
    state = json.loads(path.read_text('utf-8'))
    assert state['currentRepositoryCommit'] == PARENT
    state.update(planVersion='v0.105', taskItemsFixtureR105=manifest, workingSourceStage=index['currentSourceStage'],
                 goalStatus='active', releaseQualified=False, deliveryComplete=False)
    save(path, state)
    shutil.copyfile(Path(__file__), receipt_path.parent / 'publication-preparation-driver.py')
    names = {'开发计划与进度.md', 'README.md', 'tests/task_items_integration.py',
             'docs/执行进度.md', 'docs/构建验证摘要.md', 'docs/macOS独立预览包.md',
             'docs/current-validation.json', 'docs/ci-verification-20261107-r105.json',
             'docs/validation/2026-11-07/task-items-r105-source-audit.json',
             'docs/validation/2026-11-06/github-api-push-r104-current-index.json'}
    for folder in ['state-use-r104-ubuntu-terminal', 'task-items-r105-windows',
                   'task-items-r105-glibc', 'task-items-r105-qualified']:
        names.update(path.relative_to(root).as_posix() for path in (base / folder).rglob('*')
                     if path.is_file() and path.suffix not in ('.zip', '.gz', '.png'))
    names = sorted(names)
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / ('.cache/' + LABEL + '-publish-files.json')).write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / ('.cache/' + LABEL + '-stage.nul')).write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    template = (root / '.cache/stage-r104-current-index.py').read_bytes()
    (root / ('.cache/stage-' + LABEL + '.py')).write_bytes(template.replace(b'r104-current-index', LABEL.encode()))
    print(json.dumps({'planVersion': 'v0.105', 'files': len(names), 'productionCodeChanged': False, 'nativeCIPending': True}))


if __name__ == '__main__':
    main()
