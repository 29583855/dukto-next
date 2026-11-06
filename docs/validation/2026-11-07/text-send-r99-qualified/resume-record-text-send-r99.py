"""日期：2026-11-07；严格收验R99双Windows证据并准备明确发布文件，不操作根目录Git。"""
from datetime import datetime, timezone
import codecs
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import xml.etree.ElementTree as ET


# 日期：2026-11-07；资格已验，仅从首次新文件保存失败处继续，不重复写入原件或资格回执。
def main():
    root = Path.cwd()
    helper = runpy.run_path('.cache/finalize-skip-items-r84.py')
    first = root / 'docs/validation/2026-11-07/text-send-r99-windows'
    final = root / 'docs/validation/2026-11-07/text-send-r99-final-windows'
    output = root / 'docs/validation/2026-11-07/text-send-r99-qualified'
    receipt = output / 'verified-receipt.json'
    value = json.loads(receipt.read_text('utf-8'))
    assert value['passed']
    inputs = value['buildInputs']
    changed = value['changedBuildInputs']
    public = {'planVersion': 'v0.99', 'observedUtc': value['observedUtc'],
              'basedOnSourceCommit': value['basedOnSourceCommit'], 'buildInputs': inputs,
              'changedBuildInputs': changed, 'windowsEvidence': helper['proof'](receipt),
              'nativeCIRequested': False, 'nativeCIPending': True, 'passedScope': 'Windows GUI send preflight and rejected draft recovery only',
              'releaseQualified': False, 'deliveryComplete': False}
    public_path = root / 'docs/ci-verification-20261107-r99.json'
    assert not public_path.exists()
    public_path.write_text(json.dumps(public, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    index_path = root / 'docs/current-validation.json'
    index = json.loads(index_path.read_text('utf-8'))
    index.update(planVersion='v0.99', observedUtc=value['observedUtc'], textSendGuardR99=public,
                 currentSourceStage='R99 GUI text encoding preflight and rejected draft retention qualified on both Windows toolchains; native R99 pending',
                 currentGuiSourceCommitPending=True, releaseQualified=False, deliveryComplete=False)
    helper['save'](index_path, index)
    note = '''

## R99发送入口预检与草稿保留（2026-11-07）

- [x] 原生产QML实际复现额度不足时窗口仍关闭；两次更早的夹具准备失败分别保留。修复为转换前检查8 MiB UTF-8上限并申请临时额度，拒绝时显示原错误、保留窗口/全文/目标，释放占用后原稿重试成功。
- [x] MSVC/UCRT初轮各23目标、22份Qt原报告全部通过；最终仅额度异常生命周期及关闭清缓存修改后，各4个相关GUI目标再次通过，其余19个测试二进制逐SHA未变。8组真实TCP帧边界包含空值、三种8 MiB最大正文、孤立代理码元、两种超一字节及大输入拒绝；不降低原协议能力。
- [x] 204份维护源码/脚本零TODO、占位或简化标记；C++14、格式及5份改动文件原编码/换行通过。原版地址页实际点击并滚动观察已保存，只授予对应Windows观察范围。
- [ ] 本次只完成发送前转换及拒绝交互子项；QML粘贴/撤销/段落布局、系统剪贴板与全部资源预算、原生R99验证、完整R6/物理LAN/3×3、长期及正式发布继续。当前下载包保留各自已验身份；R98冻结CLI长测与Linux旧任务不受本次GUI修改影响。
'''
    for name in ('docs/执行进度.md', 'docs/构建验证摘要.md'):
        helper['update'](root / name, lambda text: text + note)
    plan = root / '开发计划与进度.md'
    snapshot = '''## 当前验收快照（2026-11-07，v0.99 / 发送文本预检子项）

公开仓库：[29583855/dukto-next](https://github.com/29583855/dukto-next)。R99修改GUI发送入口与对应测试，210份构建输入摘要固定于[本轮清单](docs/ci-verification-20261107-r99.json)，共用核心/CLI源码与b2e4659保持一致。双Windows初轮完整回归和最终相关GUI复验已通过；R99原生Mac/Linux尚未授予通过。

| 范围 | 最近已核验的结果 | 仍需完成 |
| --- | --- | --- |
| Windows | R99两工具链各23初轮目标，最终4个相关GUI目标及其余19二进制未变；文本8组边界/草稿拒绝重试通过；R98独立包已验 | 发送编辑器/系统剪贴板完整预算、长期、干净系统及正式发布 |
| Linux | R96 Ubuntu/Alpine各23核心及46协议；R97独立退出专项通过 | R98独立干净构建、Linux包42266702018/X11/Wayland；R99原生GUI及最新长期 |
| macOS ARM / Intel | R98各23核心/四状态/16组及重复监听退出通过；R96各46协议和双包各五业务已验 | R99原生GUI回归、完整交互、物理网络及正式分发 |
| 运行中 | R98 Windows冻结CLI的86400秒测试真实运行；旧Linux CI及独立构建继续 | 必须取得真实终态再核验，不以轮数或新GUI改动授予长期资格 |
| 整体 | 已验接收分页、发送转换前预检、部分共享资源额度及上传下载/恢复子项 | 完整R6/原生GUI、全部缓存/句柄/线程预算、公平性/安全GC、物理LAN/3×3、各平台24h、依赖源码独立重建和正式发布 |

历史应用/夹具失败、Mac精确Darwin XFAIL、缺失历史依赖清单与继承验签边界均保留。本次不改变旧包身份，不宣称全部编辑器/系统剪贴板资源已受控；详见[决策0055](docs/decisions/0055-发送文本转换前检查与拒绝保留草稿.md)。完整项目及正式发布继续未完成。

'''
    # 日期：2026-11-07；只更新当前快照并追加实测子项，保留历史失败和其余需求范围。
    def update_plan(text):
        text = text.replace('文档版本：v0.98', '文档版本：v0.99', 1)
        text = re.sub(r'^当前阶段：.*$', '当前阶段：R99发送文本转换前检查及草稿拒绝重试双Windows通过；原生R99、长期及完整交付继续。', text, count=1, flags=re.M)
        start = text.index('## 当前验收快照')
        end = text.index('## 1. 开发目标与先后顺序')
        return text[:start] + snapshot + text[end:] + note
    helper['update'](plan, update_plan)
    helper['update'](root / 'docs/原版运行与功能对照.md', lambda text: text.replace(
        '本机地址入口可见；未完整逐网卡记录原版刷新',
        '实际点击底部网络图标打开地址页并滚动，共观察7条IPv4地址；本次未见网卡标签/刷新按钮，逐网卡变化仍未验', 1) +
        '\n\n2026-11-07补记：原版窗口由参考目录启动后转交既有安装实例，二者SHA一致；实际地址页观察见`validation/2026-11-07/original-r6-address-page/observation.json`。不公开用户地址或桌面截图、不修改原版设置；地址变化刷新、完整F04与新版三平台对照继续未完成。\n')
    helper['update'](root / 'docs/补充需求与关键设计.md', lambda text: text +
        '\n\n## R99：发送文本入口资源与拒绝恢复（2026-11-07）\n\n转换前UTF-8字节检查和临时授信、拒绝时保留草稿、实际重试及关闭后清缓存已在双Windows子范围验证；保持原8 MiB能力。完整编辑器/系统剪贴板预算仍未完成，见[决策0055](decisions/0055-发送文本转换前检查与拒绝保留草稿.md)。\n')
    state_path = root / '.cache/execution-current.json'
    state = json.loads(state_path.read_text('utf-8'))
    state.update(r99TextSendGuard=public, goalStatus='active', releaseQualified=False, deliveryComplete=False)
    helper['save'](state_path, state)
    names = [*changed, '开发计划与进度.md', 'docs/执行进度.md', 'docs/构建验证摘要.md',
             'docs/原版运行与功能对照.md', 'docs/补充需求与关键设计.md', 'docs/current-validation.json',
             'docs/ci-verification-20261107-r99.json', 'docs/decisions/0055-发送文本转换前检查与拒绝保留草稿.md']
    for folder in (first, final, output, root / 'docs/validation/2026-11-07/original-r6-address-page',
                   root / 'docs/validation/2026-11-07/text-send-r99-baseline',
                   root / 'docs/validation/2026-11-07/text-send-r99-baseline-setup',
                   root / 'docs/validation/2026-11-07/text-send-r99-baseline-focus'):
        names.extend(path.relative_to(root).as_posix() for path in folder.rglob('*') if path.is_file())
    names = sorted(set(names))
    checkout = root / '.cache/github-29583855-dukto-next-r28'
    for name in names:
        target = checkout / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    (root / '.cache/r99-text-send-publish-files.json').write_text(json.dumps(names, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    (root / '.cache/r99-text-send-stage.nul').write_bytes(b''.join(name.encode('utf-8') + b'\0' for name in names))
    stage = (root / '.cache/stage-r98-stability-launch.py').read_text('utf-8-sig')
    stage = stage.replace('r98-stability-launch-publish-files.json', 'r99-text-send-publish-files.json').replace('r98-stability-launch-stage.nul', 'r99-text-send-stage.nul')
    (root / '.cache/stage-r99-text-send.py').write_text(stage, 'utf-8')
    print(json.dumps({'passed': True, 'initialFullTargetsEach': 23, 'finalGuiTargetsEach': 4,
                      'unchangedTestBinariesEach': 19, 'publishFiles': len(names)}), flush=True)


if __name__ == '__main__':
    main()
