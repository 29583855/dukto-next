"""日期：2026-11-08；两项夹具修正独立登记，旧完整协议失败保持原件，不改变生产保护。"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil

ROOT = Path.cwd()
REPO = ROOT / '.cache/github-29583855-dukto-next-r28'
BASE = 'docs/validation/2026-11-08/'


# 日期：2026-11-08；只收公开文本证据与测试脚本，不发布程序或测试私有凭据。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.log', '.py', '.xml', '.txt', '.sha256']:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


# 日期：2026-11-08；冻结两套真实CLI及原失败、候选失败、修正通过三类原件，逐份核对输入身份。
def main():
    destination = ROOT / '.cache/r128-source-prepared.json'
    assert not destination.exists()
    promotion = json.loads((ROOT / '.cache/r128-promotion.json').read_bytes())
    previous = json.loads((ROOT / 'docs/ci-verification-20261108-r127.json').read_bytes())
    audit = json.loads((ROOT / '.cache/r128-source-audit.json').read_bytes())
    snapshot = json.loads((ROOT / '.cache/r128-source-snapshot.json').read_bytes())
    assert not audit['findings'] and audit['formatting']['passed'] and audit['cxx14Configuration']
    assert snapshot['passed'] and len(snapshot['checks']) == 13
    paths = {row['path'] for row in previous['qualificationInputs']} | set(promotion['changedInputs'])
    inputs = [{'path': name, 'bytes': (ROOT / name).stat().st_size,
               'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in sorted(paths)]
    old = {row['path']: row['sha256'] for row in previous['qualificationInputs']}
    changed = [row['path'] for row in inputs if old.get(row['path']) != row['sha256']]
    assert set(changed) == set(promotion['changedInputs']) and len(inputs) == 293
    folder = BASE + 'state-fixture-r128-local'
    output = ROOT / folder
    output.mkdir(exist_ok=False)
    records = []
    verify = runpy.run_path(str(ROOT / 'scripts/ci_state_fixture_regression.py'))['verify_report']
    for tag in ['msvc', 'ucrt']:
        failed = ROOT / ('.cache/r128-candidate-' + tag)
        passed = ROOT / ('.cache/r128-candidate-attempt2-' + tag)
        first = json.loads((failed / 'receipt.json').read_bytes())
        value = json.loads((passed / 'receipt.json').read_bytes())
        assert not first['passed'] and value['passed']
        binary = ROOT / ('build/windows/Release/dukto-cli.exe' if tag == 'msvc' else 'build/windows-ucrt/dukto-cli.exe')
        assert hashlib.sha256(binary.read_bytes()).hexdigest() == value['binaryBefore'] == value['binaryAfter']
        for name, script in [('credential-rotation', 'credential_rotation'), ('task-items', 'task_items')]:
            report = json.loads((passed / (script + '.json')).read_bytes())
            script_sha = hashlib.sha256((ROOT / 'tests' / (script + '_integration.py')).read_bytes()).hexdigest()
            verify(name, report, value['binaryBefore'], script_sha)
        copy(failed, output / (tag + '-first-failed'))
        copy(passed, output / (tag + '-second-passed'))
        records.append({'toolchain': tag, 'bothCasesPassed': True, 'binarySha256': value['binaryBefore'],
                        'productionSourceCommit': value['productionSourceCommit'],
                        'candidateFixtures': value['candidateFixtures'], 'originalFailureRetained': True})
    copy(ROOT / '.cache/r128-first-candidate', output / 'first-candidate')
    copy(ROOT / '.cache/r128-start', output / 'original-inputs')
    for name, renamed in [('r128-source-audit.json', 'source-audit.json'),
                          ('r128-source-snapshot.json', 'source-snapshot.json'),
                          ('validate-r128-fixtures.py', 'local-driver.py'),
                          ('r128-promotion.json', 'promotion.json')]:
        shutil.copyfile(ROOT / '.cache' / name, output / renamed)
    receipt = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'records': records,
               'localTwoToolchainsBothCasesPassed': True, 'productCppChanged': False,
               'originalProductionInputCount': 291, 'currentQualificationInputCount': 293,
               'encodingPreserved': promotion['encodingPreserved'], 'sourceFilesAudited': len(audit['files']),
               'fullProtocolQualified': False, 'globalQuotaEnforced': False,
               'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'preparation-driver.py')
    copy(output, REPO / folder)
    index = dict(receipt, qualificationInputs=inputs, inputCount=293, changedInputs=changed,
                 parentCommit=promotion['parentCommit'], previousSourceCommit=promotion['previousSourceCommit'],
                 nativeQualificationPending=True, fullNativeProtocolQualified=False,
                 receipts=[{'path': folder + '/receipt.json',
                            'sha256': hashlib.sha256((output / 'receipt.json').read_bytes()).hexdigest()}])
    index_path = ROOT / 'docs/ci-verification-20261108-r128.json'
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    doc = ROOT / 'docs/状态目录协议夹具说明.md'
    assert not doc.exists()
    doc.write_text('''# 状态目录协议夹具修正

更新日期：2026-11-08。R128仅修正测试夹具及增加独立四平台复验，不修改生产C++、认证或状态目录保护。

R126完整协议原生终态中，credential-rotation将旧clients目录整体复制到新路径；持久根标记绑定原生目录，复制后必须先被本地完整性检查拒绝。它不能继续充当“旧凭据网络认证失败”的测试。task-items原先要求缺失接收记录查询仅留下锁文件；生产状态接入还会登记固定256字节域标记，因此原断言也失败。原运行和原日志保留，后续通过不改写旧失败。

修正后的凭据测试先由CLI创建权限正确的新根，再覆盖旧标记和资料，要求返回6/state-domain；原标记、资料和服务凭据字节保持。另建独立的新登记根，只复制旧配对资料，保留轮换后返回认证错误4的真实网络负例。丢确认、客户进程退出、活动上传/下载停止的15秒期限、相同任务及检查点复用等原断言均保留。

首候选在Windows直接copytree后被ACL保护先拒绝（4/identity），未到目录绑定验证；原候选和两套失败日志单独保存。修正准备步骤后两套Windows均通过上述两项专项。不能用ACL拒绝替代权限正确情况下的绑定反例。

缺失记录查询只允许零字节锁和256字节、单链接普通域标记。同一预算域的新根代数必须不同，预算仅增加256且保留额为0；重复查询的控制文件和预算均不变，不产生接收、结果或清单库。恢复旧目录后核对原根代数，不能重复退还仍存在的新标记占用。

新四平台专项冻结实际CLI和全部执行输入，分别保存两项原报告及退出码；完整协议仍由独立完整工作流验收。双Windows结果使用冻结R127生产程序，产品C++与R128相同；它不代表新293份资格输入已在四平台编译通过。Mac可下载包继续使用已验R127精确源，夹具变更不重新发布相同产品包。

全应用状态迁移、实际写前磁盘额度、自动GC、物理LAN/3×3及当前版本各平台24小时验收仍未完成。
''', 'utf-8', newline='\n')
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    summary = ('R128修正两项状态目录协议夹具，双Windows真实CLI专项均通过，原失败与首候选ACL失败保留；'
               '生产C++保持R127，四平台专项和完整协议等待精确提交收验。Mac含依赖预览为R127，历史迁移、实际总预算和自动GC继续。')
    section = '''## R128状态目录协议夹具修正（2026-11-08）

- [x] 保留R126完整协议原始失败；凭据复制绑定反例与旧凭据网络反例分开验证，生产完整性和认证检查均保持。丢确认、进程退出、活动传输15秒停止及同任务恢复等原断言不变。
- [x] 缺失记录查询只允许零字节锁和固定256字节标记；新根代数、仅一次计量、零保留额、重复查询原字节保持、恢复原根核对通过，不生成接收/结果库。
- [x] 双Windows冻结R127程序均通过两项修正专项；原291输入及程序前后保持。首候选ACL前置失败和第二轮通过分别保留；原两文件编码/BOM/LF保持，C++14/格式和维护源码审计通过。[说明](docs/状态目录协议夹具说明.md)。
- [x] 本轮只修改两份Python夹具及新增独立四平台复验脚本/工作流，生产C++与R127相同。含Qt5/OpenSSL的Mac ARM/Intel下载继续为R127精确源。
- [ ] 新293份资格输入的四原生专项及完整GUI/核心/协议按精确公开提交分别收验，未完成前不授予完整协议资格。
- [ ] 普通历史安全迁移、全应用/临时对象归属、实际写前预算、跨卷/未知项/有效幂等保留、自动GC、完整R6/选择器、物理LAN/3×3、当前各平台24h和正式发布继续，整体active。

'''
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace('文档版本：v0.127', '文档版本：v0.128', 1).replace('## R127四原生GUI接入与双Mac预览', section + '## R127四原生GUI接入与双Mac预览', 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace('## R127四原生GUI接入与双Mac预览', section.replace('](docs/', '](') + '## R127四原生GUI接入与双Mac预览', 1))
    update('README.md', lambda text: text.replace('R127精确', summary + ' [本轮证据](docs/ci-verification-20261108-r128.json)。\n\nR127精确', 1))
    explicit = set(changed) | {'README.md', '开发计划与进度.md', 'docs/执行进度.md',
                              'docs/状态目录协议夹具说明.md', 'docs/ci-verification-20261108-r128.json'}
    for name in explicit:
        (REPO / name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, REPO / name)
    destination.write_text(json.dumps({'explicitFiles': sorted(explicit), 'evidenceFolders': [folder],
                                      'allLocalQualified': True, 'inputCount': 293}, indent=2) + '\n', 'utf-8')
    print(json.dumps({'inputs': 293, 'changed': changed, 'bothWindowsCasesPassed': True}))


if __name__ == '__main__':
    main()
