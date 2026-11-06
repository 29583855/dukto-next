# Windows 独立预览包

当前R98采用精确b2e4659源码，包含当前接收分页、资源授信、服务器上传下载及恢复/冲突处理。C++14/Qt5，GUI与CLI均可独立运行。

更新日期：2026-11-07。当前为开发预览，完整主计划和正式发布继续。

## 当前R98预览包（2026-11-07）

`dist/windows-preview-20261107-r98-exit-state/DuktoNext-windows-x64-preview.zip`，SHA-256：`99f007bb1daf11a87750ecbb0435b5f0ccc617ce3baf9566efb77c72add77a82`。源码`b2e4659b347c65eef24c8e568e07e96a2d6ff2d7`；333份应用源码全集与精确Git逐字节一致，GUI/CLI绑定实际构建。

实际ZIP在中文空格目录、仅系统PATH下通过GUI、独立CLI、16通道双向、会话/混合排队/重试/最终确认/fail/overwrite与4→8恢复。Windows MSVC/UCRT各23核心通过。首次说明截图已查看，中文与控件正常；截图中的头像端口不可用提示保留，完整GUI和原生选择器仍另验。

24个未变依赖的364部署文件、53许可与公开摘要固定的R25验签记录一致；本次重新核对缓存归档及配方摘要，没有重新验签。最早R12清单仍缺失，首次核验工具失败保留，见[决策0054](decisions/0054-未变依赖验签记录的摘要继承核对.md)。[实际回执](validation/2026-11-07/exit-state-r98-windows-package/verified-receipt.json)记录范围。干净系统、全部资源/长期、依赖对应源码独立重建与正式签名发布未完成。

## r25预览包（历史，2026-11-06）

包位置：dist/windows-preview-20261106-r25-completed-history/DuktoNext-windows-x64-preview.zip，SHA-256：529b14ec96e57e2e1735f896efe2eaab243b034aa7616a6462b725411f325c9c。包源5857073、生产源码db8c774；242份应用源码与精确Git树全集一致。364受信依赖、24包和53许可核对通过。

实际ZIP在中文空格目录、仅系统PATH下验证GUI、独立CLI和16通道双向；会话、混合排队、重试、最终确认、fail/overwrite与4→8恢复通过。同一部署CLI另通过历史只读/上传确认恢复/处置/证书专项，CLI SHA为7e10b8a7045c3786a76e1c255ab004fd8bf6bc26a2ee78dfddda5aed121e55de。实际首次说明截图已查看。20轮短测通过，冻结输入24h长测已启动，终态未验。

[公开回执](ci-verification-20261106-r68.json)记录源码与全部原报告摘要。包当前保存在本机持久dist目录；干净系统、完整GUI/原生选择器、完整第三方源码/独立重建、签名及正式发布未完成。

## r24预览包（历史，2026-11-05）

当前包：`dist/windows-preview-20261105-r24-peer-close/DuktoNext-windows-x64-preview.zip`，SHA-256：`ad02396dbba52a80df3e21315d79aa10936ea44a1fc7a77fae97f355801826ee`。源码`31f3db3bfb5a8bf70b6217afd50df3284e27934c`，213应用输入与精确Git树匹配。364受信依赖、24包和53许可核对通过。实际ZIP在系统PATH/中文空格目录运行GUI及独立CLI，包含客户端、会话、排队、重试、最终确认、fail/overwrite和4→8恢复；同一包CLI七项证书生命周期及双向检查点复用通过。实际截图已查看。

[运行报告](validation/2026-11-05/windows-r24-runtime-r52.json)、[源码身份](validation/2026-11-05/windows-r24-source-linkage-r52.json)、[依赖映射](validation/2026-11-05/windows-r24-signed-payload-map-r52.json)、[证书生命周期](validation/2026-11-05/windows-r24-certificate-lifecycle-r52.json)。CLI SHA为`58cda186aabbde9998ff98bd20697d1138bf95a1d06532fadde75936c81da38a`。

支持CLI `--on-conflict overwrite`及GUI同名普通文件覆盖，合并目录保留无关项。原31f3db3 Windows完整协议38项中会话日志观察失败，本机修正测试已通过，原生复验继续。完整处置/最终确认、干净系统、第三方对应源码/独立重建及正式发布尚未完成。

## r23覆盖预览包（历史，2026-11-05）

当前包：`dist/windows-preview-20261105-r23-overwrite/DuktoNext-windows-x64-preview.zip`，SHA-256：`c830a482351eebc78cf9831e7e76ee8db1c89900f0724a61f0fb370c62be1de0`。源码 `c3fc7815679b16dc5f0f3aa432dad56d92ae312f`，487文件、211应用输入与精确Git树匹配。实际ZIP系统PATH/中文空格目录迁移、双向1/4/16覆盖和8组已有文件4→8恢复通过，GUI截图已查看；[运行报告](validation/2026-11-05/windows-r23-runtime-r49.json)、[源码身份](validation/2026-11-05/windows-r23-source-linkage-r49.json)、[受信依赖/许可映射](validation/2026-11-05/windows-r23-signed-payload-map-r49.json)分别保留。

支持 `--on-conflict overwrite` 和GUI同名普通文件覆盖选择，目录合并保留无关项。既有客户端/会话/排队/重试/最终确认/fail及恢复也在本包重新验证。该包CLI SHA为fe8373a79ac439e6f77ade487bed978f0af6c751b6980caff58fc0cc6ae51268；证书生命周期已用同一CLI原位重跑通过。原生Mac/Linux新覆盖资格、完整处置确认、干净系统和正式发布仍待验收。历史r22及以前的包与结果保持原范围。

## r22主窗口修复预览包（历史，2026-11-05）

当前包：`dist/windows-preview-20261105-r22-main-server/DuktoNext-windows-x64-preview.zip`，SHA-256：`df5e563edb8dc9d8250b663bcc782f6cea778354905e299877ca5c7bb5d9ba13`。源码f230f3d，487文件、209应用输入与精确Git树匹配；[实际迁移报告](validation/2026-11-05/windows-r22-runtime-r48.json)、[源码关联](validation/2026-11-05/windows-r22-source-linkage-r48.json)和[受信依赖/许可核对](validation/2026-11-05/windows-r22-signed-payload-map-r48.json)均通过，实际GUI截图已查看。

实际ZIP迁移至中文空格路径、只用系统PATH，GUI/独立CLI/16双向、客户端/会话/排队/重试/最终确认/fail及恢复均通过。生产主窗口真实点击、两尺寸、三页导航、返回/重开和原生/150%/200%另由同一生产QML的编译测试程序通过；不声称直接点击部署EXE。CLI摘要仍为7875f59a16d0638a1fe1401a1e7414b7181455f3e4c273cd0995bf0670cb07f1，与已验证证书功能版本相同。全量协议、对应源码/独立重建、干净系统及正式发布继续未完成。

旧r21及其SHA/证书专项报告保留在原目录，不将旧入口当作通过。下文历史包按各自版本理解。

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

## r15 当前可用的预览包（2026-11-05）

新包位于 `dist/windows-preview-20261105-r15/DuktoNext-windows-x64-preview.zip`，SHA-256为 `5fa8f761a2166351f87043c7655f9cf809737fc60e78f55e721cfd4b8ac932f5`，持久存放在用户目录下的DuktoNextArtifacts。它包含3360496的并行错误根因保留及暂停/取消分类修复。[系统PATH迁移](validation/2026-11-05/package-windows-runtime-r15.json)通过：486份清单文件、GUI原生渲染、无桌面依赖CLI、16通道双向、客户端、会话、排队、14组重试、6组最终确认、fail冲突及4→8恢复。截图已查看。

[应用源码关联](validation/2026-11-05/windows-r15-source-linkage-r30.json)逐文件验证包内源码及78份生产输入；源码为生成时快照，不包含后续诊断/CI/文档更新。[24个依赖包的364份文件及53份许可](validation/2026-11-05/windows-r15-signed-payload-map-r30.json)重新与受信签名原包核对。旧r12/r13/r14归档仍缺失，此新包不恢复或冒充历史摘要。cleanSystemQualified与releaseQualified继续为false，完整对应源码/独立重建仍待完成。

## r16 共享数据库校验修复预览（2026-11-05）

持久包为dist/windows-preview-20261105-r16/DuktoNext-windows-x64-preview.zip，SHA-256：b606036baa5d4da5d270a57192a114134b9a44dff8b76039cc46e0d38c1e6b98。系统PATH实际迁移通过，包含da2799b并发私有数据库校验修复；GUI、独立CLI、16通道双向、会话、混合排队、14重试、最终确认和fail/4→8恢复通过。[应用源及生产输入核验](validation/2026-11-05/windows-r16-source-linkage-r32.json)与[依赖许可核验](validation/2026-11-05/windows-r16-signed-payload-map-r32.json)保留。应用源码为打包时冻结快照，后续夹具/部署修改另行记录；干净系统、完整对应源码、独立重建及正式发布资格仍未完成。

## r17初始化竞争修正预览（2026-11-05）

持久包为dist/windows-preview-20261105-r17/DuktoNext-windows-x64-preview.zip，SHA-256：4825c481916e8daa5ee81b0d3180737a87a3e143b12f3a509892110f7fdba944。实际ZIP系统PATH迁移通过，包含2627d48初始化轮询；185份应用输入与1bc2774精确Git树核对，24包/364个依赖文件/53份许可核对通过。原生截图已查看。完整对应源码、干净系统及正式发布仍待验，历史r16继续保留。


## r18逐项查询和网络稳定性修复（2026-11-05）

当前包为`dist/windows-preview-20261105-r18/DuktoNext-windows-x64-preview.zip`，SHA-256：`76328048c393ea824d2939a83e4ec818ef553052c0e2c2777c9bb02d521b74a9`。源码fa6d96b；193份包内应用源码与精确Git树相同。新增逐项查询及R6 I/O期限/多通道加入确认修复。实际包的[系统PATH迁移](validation/2026-11-05/windows-package-r18-runtime-r38.json)、[源码核验](validation/2026-11-05/windows-r18-source-linkage-r38.json)及[依赖许可映射](validation/2026-11-05/windows-r18-signed-payload-map-r38.json)均通过，原生GUI截图已查看。旧包保留；干净系统、完整对应源码/独立重建及正式发布仍待验收。


2026-11-05 v0.39补记：当前r19包已包含逐项接收失败原因，下面按精确源码与实际迁移单独记录；r18保留为历史版本。


## r19逐项失败原因预览（2026-11-05）

当前可用包为`dist/windows-preview-20261105-r19/DuktoNext-windows-x64-preview.zip`，SHA-256：`f04057d0e9f3d2cec9fa86e83af37993ab777484790c6ec07d7ea100a1a28a12`。源码3b8bf4a；195份应用输入与精确Git树相同。[实际ZIP系统PATH迁移](validation/2026-11-05/windows-package-r19-runtime-r39.json)、[新增原因专项](validation/2026-11-05/windows-r19-item-failures-r39.json)、[源码核验](validation/2026-11-05/windows-r19-source-linkage-r39.json)与[依赖许可映射](validation/2026-11-05/windows-r19-signed-payload-map-r39.json)均通过。原生GUI截图已查看，旧版本保留。完整第三方对应源码、独立重建、干净系统及正式发布资格仍未完成。


v0.41当前可用Windows r20：dist/windows-preview-20261105-r20/DuktoNext-windows-x64-preview.zip，SHA-256 `54934373992c49fa774d9fb706759108924a6ad1bc9625ac1b9b82b3f6e908e7`。实际迁移、199应用输入/精确Git树和364依赖/53许可核对通过，生产7590363、完整源码文档bed94bf。1842009重查不在此包；原失败及新构建分别保留，完整正式发布资格继续未完成。


2026-11-05 v0.46版本范围补记：上方已验收的实际包早于证书续期/指纹迁移功能，不含serve renew、profile-info及trust；新源码和新包的资格分别记录，新包实际下载校验结束后再更换入口。


v0.51：r23同一fe8373a7 CLI原位运行已完成证书生命周期七检查及双向检查点复用，报告windows-r23-certificate-lifecycle-r50-inplace.json。复制单个EXE离开包的首轮测试无法定位SQL插件，原失败保留，新增--in-place保持EXE旁依赖布局。r23仍早于0017发送期修复，新包/原生盘满另验。


### v0.69 新源码资格说明（2026-11-06）

最新生产源码4da0b12增加双端处置摘要确认，双Windows核心与协议专项通过；精确新提交的原生CI及双Mac部署包已启动，终态和原附件待核验。本页下载仍为已验db8c774生产输入，不声称包含新协议。上一db8c774五环境各21核心、四runner159及Alpine39协议原报告SHA均已核验。见[本轮回执](ci-verification-20261106-r69.json)。


## R98当前Windows100轮及长期验证启动（2026-11-07）

- [x] 当前已验R98包及全部测试输入冻结：采样自检和100轮16通道双向传输通过，用时125.063秒，服务常驻、内容摘要及资源预算断言保持；二进制与实际部署包一致，冻结输入未变。
- [x] 204份维护源码/脚本零TODO、占位和简化标记；C++14及格式检查通过。零标记不替代未验功能或资源保证。
- [ ] 同一冻结输入24小时测试已实际开始（会话56228，原86400秒/300秒间隔）；仅公开启动观察快照，终态及资源趋势尚待核验。不把100轮通过视为24h或任意增长/磁盘GC通过。
- [ ] Linux当前部署包42266702018仍在安装依赖；完整R6/原生GUI、全部资源预算、公平性/安全GC、物理网络/3×3、其他平台当前长期、依赖源码独立重建、干净系统及正式签名公证继续。
