# Windows 独立预览包

更新日期：2026-11-05。当前为开发预览，完整功能和发布验收仍按主计划执行。

## 生成

先运行 `scripts/build-ucrt.ps1`。Qt 部署工具缺少时，由开发助手在同一 MSYS2 UCRT 环境中安装 `mingw-w64-ucrt-x86_64-qt5-tools`，保持 pacman 签名校验。已安装版本为 5.15.19-1，安装日志保存在 `.tools/downloads/msys2-install-qt5-tools.log`。

```powershell
.tools/python/Scripts/python.exe -X utf8 scripts/package_windows.py --output dist/windows-preview-<唯一名称>
.tools/python/Scripts/python.exe -X utf8 tests/windows_package_integration.py dist/windows-preview-<唯一名称>/DuktoNext-windows-x64-preview.zip --report docs/validation/<日期>/package-windows-runtime.json
```

输出目录必须尚不存在，脚本不覆盖既有产物。生成 ZIP、SHA256SUMS、Qt 部署日志及解压后的完整目录。包内包含 GUI、独立 CLI、Qt/SQLite 插件、实际 QML 导入、OpenSSL3 和递归 PE 导入依赖；除 Windows 系统组件外，缺少导入或未知来源均使打包失败。

Qt 桌面端由应用明确使用软件渲染，部署参数相应关闭 ANGLE 和备用 OpenGL 光栅器。SQLite 为本项目唯一数据库，排除未使用的外部数据库插件。`qt.conf` 将插件及 QML 导入固定到应用目录；正常启动无需开发工具 PATH。

## 使用与内容

解压后双击 `dukto-gui.exe`。在 PowerShell、cmd 或其他终端运行 `dukto-cli.exe --help`、`dukto-cli.exe doctor --json`。CLI 不要求 GUI 启动，不加载 QtGui/Widgets/QML。配置和传输状态默认使用平台用户目录，显式隔离参数见项目 README。

`package-manifest.json` 记录逐文件大小/摘要、依赖来源、PE 导入和本工程源码摘要；清单自身由外层 ZIP 的 SHA-256 覆盖。`dependency-packages.json` 固定实际部署的 pacman 包版本、许可、安装来源和签名验证标记。`licenses/` 保留本工程 GPL 及安装依赖的完整许可，`DuktoNext-corresponding-source.zip` 包含本工程源码、界面、构建、验证脚本和设计文档，不含状态或凭据。

对应第三方源码、准确构建配方/补丁的分发仍待完善；现有许可和版本记录不能替代该项。正式发布还需要干净 Windows 系统验收，当前打包不会将 `releaseQualified` 标为 true。

## 已验证范围

2026-11-05 首包约 40 MiB。测试解压到包含中文及空格的临时目录，子进程 PATH 仅保留 Windows System32，配置/缓存/用户目录全部隔离。逐文件 SHA、CLI 帮助/依赖自检、服务持久 SQLite、GUI 原生 Windows 平台插件及 430×700 实际渲染、16 通道双向 TLS/三窗口/Unicode/空目录/幂等重试/同名文件保护均通过。

测试读取真实进程模块列表，要求所有模块来自解压目录或 Windows 目录，CLI 拒绝加载桌面模块。此结论覆盖开发主机上的迁移运行，干净系统结论仍独立保留。记录见 [运行报告](validation/2026-11-05/package-windows-runtime.json) 与 [渲染](validation/2026-11-05/package-windows-runtime.png)。

2026-11-05 第四版包包含零字节任务完成进度修复及 SQLite 页缓存目标共用授信，迁移验证再次通过。位置为 `dist/windows-preview-20261105-r4/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `5bdac959a72d7cdf516ec16cd117ba68aba550636c6fcc67ba074aeac78aa955`。见 [第四版报告](validation/2026-11-05/package-windows-runtime-r4.json)。源码与运行依赖以包内逐文件清单为准，后续新增验证脚本不改变该快照的验证范围。

2026-11-05 第五版包包含完成确认与冻结强清单严格一致性修复，独立迁移验证通过。位置为 `dist/windows-preview-20261105-r5/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `5e2396f13eb08dec196743c942166f5ef7bd9ea82a4ff2a4e98def8ac25ca303`。见 [第五版报告](validation/2026-11-05/package-windows-runtime-r5.json)。该包早于后续 Discovery 排空循环修改；完整发布和干净系统验证继续。

2026-11-05 第六版包包含本轮发现消息有界排空和完成确认修复，迁移运行通过。位置为 `dist/windows-preview-20261105-r6/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `425128637a98af34abc8c38953c38ffa838b8043338c1c63f0c336573f65ce39`。见 [第六版报告](validation/2026-11-05/package-windows-runtime-r6.json)。

2026-11-05 第七版包包含访问凭据轮换、待确认恢复提示及认证失效后原任务恢复处理，[迁移运行](validation/2026-11-05/package-windows-runtime-r7.json)与仅系统 PATH 的[包内 CLI 轮换及中途恢复](validation/2026-11-05/credential-rotation-package-r7.json)均通过。位置为 `dist/windows-preview-20261105-r7/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `01420e529b106a7e3800c8d75f357ca0a398a2ea99ff53127d9b19be7da78dde`。源码归档是打包当时快照，后续测试身份登记脚本修改不在该归档中；完整发布仍按主计划验收。


2026-11-05 第八版包包含本机已配对客户端查看/选择、分页及权限同步刷新，位置为 `dist/windows-preview-20261105-r8/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `d3c952382a54c54acb5ad9092055e043796fccfbd6e04d160f6da53c7710c3ed`。[迁移运行](validation/2026-11-05/package-windows-runtime-r8.json)与[含包内客户端管理专项](validation/2026-11-05/package-windows-runtime-client-list-r8.json)均通过；后者在仅系统 PATH、中文空格路径中实际配对两主体，验证轮换/授权/撤销与 107 主体分页。完整原生服务器面板鼠标测试另见计划 v0.21，包测试不混称完整主窗口或干净系统验收。


2026-11-05 第九版包进一步包含多通道定向唤醒，位置为 `dist/windows-preview-20261105-r9/DuktoNext-windows-x64-preview.zip`，SHA-256 为 `3862cebe918fcfca6f992e3bb2ba785a49db1cadb9149841e79feac2cdef4376`。[迁移运行及客户端管理专项](validation/2026-11-05/package-windows-runtime-r9.json)通过，实际包内 CLI SHA `a564ef3e5173be949b0cad07eba9bb26237d18418ddcb5867da2e726b51bf2d7`。源码为打包当时快照，后续报告/进度更新以当前计划为准；不改变 releaseQualified=false 的开发预览范围。


2026-11-05 第十版包增加认证会话期限和本机 GUI/CLI 设置，位置为 dist/windows-preview-20261105-r10/DuktoNext-windows-x64-preview.zip，SHA-256 为 6319b7170d61b0846f8d967e3aa4d2316d93f966214836e58af5aa9bcd52789b。[迁移运行](validation/2026-11-05/package-windows-runtime-r10-recheck.json)通过，除原有 GUI/CLI/16 通道/客户端管理之外，包含同包内 CLI 的严格期限协商、策略持久化和四通道到期后恢复原任务；CLI SHA cc7116c70277fb7f7d177e68a6dfa5e09afd4177953c750a49cf509f1fb430d6。首轮测试捕获 GUI 模块枚举竞态，保留失败，外部测试修正后重跑通过；最终仍要求实际 qwindows 模块证据。包内源码是生成时快照，之后的测试/文档修改不在其中。干净系统、准确第三方对应源码和完整发布仍待完成。

2026-11-05 第十一版包包含有限公平任务排队、实际授信档位和中文等待控制，位置为 dist/windows-preview-20261105-r11/DuktoNext-windows-x64-preview.zip，ZIP SHA-256 40ed3d77b0935b4a98c1ea90ce96d60cbe78a7f79e124d693a996ea6b0c36a14。[迁移运行](validation/2026-11-05/package-windows-runtime-r11.json)通过，新增包内混合上传/下载等待、排队控制、到期/撤权/断开/服务重启及原任务恢复，CLI SHA f9605c326de6741f2c2717eff894bc903f56e3eae9ad10f73d4d463b41bae38e。485 个清单文件和外层 ZIP 完整性核验，包总计 486 文件/24 依赖包；实际 qwindows 模块和原生渲染已捕获，CLI 保持独立无桌面模块。源码归档为生成时快照，之后本机进度/契约文档对齐不在其中，生产输入见[身份核对](validation/2026-11-05/admission-production-identity.json)。当前为开发预览，完整主窗口交互、干净系统、准确第三方对应源码与正式发布继续。


2026-11-05 第十二版[归档状态（r12 ZIP当前缺失）](产物存放与可用性.md)包含有限网络重试、总时限及远程暂停/取消保护，ZIP SHA-256 为 4362134a681285627553f4031a18deab4ab0e272bbfb7910a230abaee7b3779a，CLI SHA 为 1701673bff7fe7c8cf7586922edcf8b7ae5323a2c2951719bdfdf2e52f95dbf5。[迁移报告](validation/2026-11-05/package-windows-runtime-r12-recheck.json)通过：原有 GUI/CLI/16 通道/客户端/会话恢复/混合排队之外，实际执行同一包内 CLI 的十四组重试/总时限与六组自动最终确认恢复。只保留系统 PATH；没有借开发 DLL 目录补足依赖。

本轮[首次失败](validation/2026-11-05/package-windows-runtime-r12.log)来自测试复制裸 EXE 后失去相邻 DLL；专项新增 --in-place，直接运行已部署程序后，同一 ZIP 完整重跑通过。包内对应源码为生成时内容，之后外部测试的原地运行选项、诊断及进度修改未写回该包。预览身份和发行资格保持独立，cleanSystemQualified/releaseQualified=false。

## r13 许可修正包（2026-11-05）

当前[r13归档状态（ZIP当前缺失）](产物存放与可用性.md)，SHA 937d3c67f6f7c4c348aa4322c4e8fedf21c75d7952dd204dab03b5977cd3d9e9，[仅系统 PATH 迁移](validation/2026-11-05/package-windows-runtime-r13.json)通过，新增 ICU 许可完整部署，24 包/364 依赖文件/53 许可已与受信签名原包核对。r12 许可遗漏发现保留；新包不覆盖旧归档。r13 仍早于 fail 冲突策略，工程源码使用其自带 ZIP，旧源码输入附件只复用相同依赖输入，详见[源码身份关联](validation/2026-11-05/windows-r13-source-input-linkage.json)。独立重建、干净系统及正式发行仍未完成。
