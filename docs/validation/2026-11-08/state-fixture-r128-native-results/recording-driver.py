"""日期：2026-11-08；记录精确公开源的实际派发和独立环境原件，未终态仍保持未完成。"""
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


# 日期：2026-11-08；普通文本原件逐字节镜像，测试归档与可执行文件不加入公开证据。
def copy(source, target):
    for path in source.rglob('*'):
        if path.is_file() and path.suffix in ['.json', '.log', '.py', '.xml', '.txt', '.sha256', '.exit']:
            destination = target / path.relative_to(source)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, destination)


# 日期：2026-11-08；同一精确提交的两个工作流分别记账，不以派发、排队或编译替代测试通过。
def main():
    target = ROOT / '.cache/r128-native-results-prepared.json'
    assert not target.exists()
    runs = json.loads((ROOT / '.cache/r128-ci-runs.json').read_bytes())
    source = runs['sourceCommit']
    folder = BASE + 'state-fixture-r128-native-results'
    output = REPO / folder
    output.mkdir(exist_ok=False)
    request = runpy.run_path(str(ROOT / '.cache/github-actions-r28.py'))['request']
    observed = []
    for key in ['nativeRunId', 'regressionRunId']:
        value = request('/repos/29583855/dukto-next/actions/runs/' + str(runs[key]))
        assert value['head_sha'] == source and value['run_attempt'] == 1
        observed.append({key: value[key] for key in ['id', 'head_sha', 'status', 'conclusion', 'html_url']})
    for name in ['r128-ci-runs.json', 'r128-dispatch-build.yml.json', 'r128-dispatch-state-fixture-regression.yml.json']:
        shutil.copyfile(ROOT / '.cache' / name, output / name)
    glibc_path = ROOT / '.cache/r128-glibc-fixtures/receipt.json'
    glibc_status = 'pending'
    if glibc_path.exists():
        glibc = json.loads(glibc_path.read_bytes())
        assert glibc['productionSourceCommit'] == '6c6dc363c7bb755f7b5aae1f7627385c009a0ac2'
        for name, sha in glibc['testInputs'].items():
            assert hashlib.sha256((ROOT / 'tests' / name).read_bytes()).hexdigest() == sha
        copy(ROOT / '.cache/r128-glibc-fixtures', output / 'independent-glibc')
        shutil.copyfile(ROOT / '.cache/validate-r128-glibc-fixtures.py', output / 'validate-glibc.py')
        glibc_status = 'passed' if glibc['passed'] else 'failed-original-retained'
    native_path = BASE + 'state-fixture-r128-native'
    core_path = BASE + 'state-fixture-r128-full-native-core'
    native = json.loads((REPO / native_path / 'receipt.json').read_bytes())
    core = json.loads((REPO / core_path / 'receipt.json').read_bytes())
    assert native['sourceCommit'] == core['sourceCommit'] == source
    native_count = sum(row['qualified'] for row in native['records'])
    core_count = sum(row['qualified'] for row in core['records'])
    record = {'observedUtc': datetime.now(timezone.utc).isoformat(), 'sourceCommit': source,
              'runs': observed, 'bothExactSourceWorkflowsDispatched': True,
              'nativeFixtureJobsVerified': native_count, 'allFourNativeFixturesQualified': native_count == 4,
              'nativeCoreJobsVerified': core_count,
              'independentGlibcFixtureStatus': glibc_status, 'productCppChanged': False,
              'fullNativeProtocolQualified': False, 'globalQuotaEnforced': False,
              'deliveryComplete': False, 'releaseQualified': False}
    (output / 'receipt.json').write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    shutil.copyfile(Path(__file__), output / 'recording-driver.py')
    folders = [BASE + 'state-fixture-r128-' + suffix for suffix in ['native', 'full-native-core', 'native-terminal']] + [folder]
    for name in folders:
        copy(REPO / name, ROOT / name)
    index_path = ROOT / 'docs/ci-verification-20261108-r128.json'
    index = json.loads(index_path.read_bytes())
    assert all(hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256'] for row in index['qualificationInputs'])
    index.update(sourceCommit=source, nativeRun=observed[0], regressionRun=observed[1],
                 nativeFixtureJobsVerified=native_count, allFourNativeFixturesQualified=native_count == 4,
                 nativeCoreJobsVerified=core_count, nativeFixtureQualificationPending=native_count != 4,
                 independentGlibcFixtureStatus=glibc_status, observedUtc=record['observedUtc'])
    refs = {row['path'] for row in index['receipts']} | {name + '/receipt.json' for name in folders}
    index['receipts'] = [{'path': name, 'sha256': hashlib.sha256((ROOT / name).read_bytes()).hexdigest()} for name in sorted(refs)]
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    shutil.copyfile(index_path, REPO / index_path.relative_to(ROOT))
    update = runpy.run_path(str(ROOT / '.cache/publish-r121-source.py'))['update_document']
    note = ('独立Ubuntu用相同R127生产程序及精确R128夹具，两项专项均通过；原安装源/程序和测试输入前后保持。'
            if glibc_status == 'passed' else '独立Ubuntu两项夹具专项继续按原进程收验。')
    summary = (f'R128精确{source[:8]}已公开，四平台专项已验{native_count}/4，完整核心已验{core_count}/4；完整协议终态继续收验。'
               + note + '双Windows两项已验；生产C++保持R127，Mac双架构含依赖预览已公开匿名下载核对。历史迁移、总预算/自动GC与完整项目继续。')
    line = (f'- [x] 精确{source}已非强制公开；[四平台两项专项]({observed[1]["html_url"]})已验{native_count}/4，'
            f'完整核心已验{core_count}/4；'
            f'[完整GUI/核心/协议]({observed[0]["html_url"]})已实际派发，终态按原件独立收验。' + note + '\n')
    anchor = '- [ ] 新293份资格输入的四原生专项及完整GUI/核心/协议按精确公开提交分别收验，未完成前不授予完整协议资格。'
    update('开发计划与进度.md', lambda text: re.sub(r'^当前阶段：.*$', '当前阶段：' + summary,
           text.replace(anchor, line + anchor, 1), count=1, flags=re.M))
    update('docs/执行进度.md', lambda text: text.replace(anchor, line + anchor, 1))
    update('README.md', lambda text: text.replace('R128修正两项状态目录协议夹具', summary + '\n\nR128修正两项状态目录协议夹具', 1))
    update('docs/状态目录协议夹具说明.md', lambda text: text + '\n精确公开源`' + source + '`的[四平台专项]('
           + observed[1]['html_url'] + ')及[完整回归](' + observed[0]['html_url'] + ')已启动；' + note + '\n')
    record.update(evidenceFolders=folders, explicitFiles=['README.md', '开发计划与进度.md', 'docs/执行进度.md',
                                                        'docs/状态目录协议夹具说明.md', 'docs/ci-verification-20261108-r128.json'])
    target.write_text(json.dumps(record, indent=2) + '\n', 'utf-8')
    print(json.dumps(record), flush=True)


if __name__ == '__main__':
    main()
