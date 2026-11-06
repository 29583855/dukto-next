# macOS独立开发预览包

更新日期：2026-11-06。当前可下载包源码为`d973da14956a76147d2db5cd4a0a5761e802ab4f`，C++14/Qt5；Intel和Apple Silicon分别交付GUI与独立CLI，Qt5/OpenSSL运行依赖已放入应用。

## 下载与校验

[d973da1双架构打包与迁移工作流](https://github.com/29583855/dukto-next/actions/runs/42127252726)终态success。按Mac芯片选择架构；GitHub附件下载可能需要登录。ZIP内含tar.gz、校验值和原报告。

| 架构 | GitHub附件 | 内部tar.gz的SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42127252726/artifacts/13461997589) | `9c3ad6b2fd3759f3fef9f5d6da2632e1838cb0b2752fc0801cb3f015d1f2ffc2` |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42127252726/artifacts/13462362329) | `07c53ea4b50b1eef1cc34e066a13677a0097f5715982e8574e16051b94ac547f` |

先解压ZIP。Apple Silicon示例（Intel将arm64替换为x86_64）：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

使用tar解包保留框架链接和执行权限。移动时保留整个目录，CLI启动器和.app保持相邻；应用内独立CLI为Dukto Next.app/Contents/MacOS/dukto-cli，无需GUI运行。

## 已验证范围

GUI保留Dukto设备/最近/关于布局，底部“服务器 · 上传 / 下载”进入服务器页。客户机主动连接服务器，执行配对、授权目录浏览、上传和下载；服务器无需主动连接客户机IP。GUI/CLI共用内核，扩展支持1/2/4/8/16通道以及暂停、取消和恢复，CLI可在无桌面服务器独立运行。

两包在原生Mac runner的中文空格目录、仅系统PATH下实际迁移。arm64的1547份载荷、Intel的1705份载荷，各71个链接和全部文件摘要已核验；GUI/CLI Mach-O架构、执行权限、依赖来源及adhoc签名通过。两包各249份内附应用源码与精确Git树全集逐字节一致。各五份原业务报告按父SHA逐份读取并通过：独立CLI、16通道双向、1/4/16覆盖、覆盖恢复和4→8恢复。

两架构原生Cocoa服务器页截图已查看，中文和控件布局正常。生产QML/实际Controller测试夹具的服务器入口、页签、返回重开及紧凑尺寸通过；150%/200%缩放使用独立offscreen用例，完整部署GUI交互和原生文件选择器仍另行验收。

同包源码d973da1增加内部单TLS/并行正文裁决，公开skip仍关闭。完整CI须独立理解：Alpine21核心/40协议通过，Ubuntu及ARM Mac各40协议原报告已验；Intel原20/21核心因测试夹具误判合法busy失败，9cd411f测试修复双Windows已验，新原生复验继续。Ubuntu真实TLS盘满返回网络错误的原失败保留并修复验证中。包迁移成功不代表完整回归通过。

本机持久归档：dist/macos-preview-20261106-r70-skip-wire/BUILD-RECEIPT.json。[当前核验索引](current-validation.json)记录提交、运行、附件ID和摘要；本地原始核验回执为docs/validation/2026-11-06/skip-wire-r70-macos-package-terminal/receipt.json。

## 交付边界

这是adhoc签名的开发预览，尚未Developer ID签名或Apple公证；干净Mac/Gatekeeper、最低系统版本、完整第三方对应源码及独立重建未完成。公开skip、全部原版交互、物理LAN提速/3×3互通和当前全平台24小时稳定性继续按主计划执行，releaseQualified=false、deliveryComplete=false。

## 历史版本记录

以下记录按当时提交理解，当前下载入口以上表为准。

2026-11-05 v0.39补记：此页当前双包已更新到3b8bf4a，包含逐项接收失败原因。旧fa6d96b双包保留于dist/macos-preview-20261105-r38-timeout-attach。新双包部署/迁移通过；同源码完整CI41986605449中Apple Silicon的Core and GUI controller tests步骤失败，尚待该job终态日志定位，其他专项继续原运行。不能将独立包通过写成完整回归通过。


2026-11-05 v0.40补记：3b8完整CI的具体失败已归档为CoreTests::discoveryYieldsAndRejectsMalformedGoodbye，5000包原10秒门槛；服务器GUI和30协议通过。7590363的新双包与完整原生验证继续，未以旧包SHA宣称更新。


v0.41实际交付补记：本页已更新到7590363的双包，保存于dist/macos-preview-20261105-r40-signature-cache。两包各199应用输入及全部框架/签名/依赖核对完成，迁移与双向16通道及4→8八组恢复通过。实际截图已查看，其中ARM截图显示临时接收端口占用；本项GUI检查证明渲染与依赖加载，不能作为该次R6 GUI监听成功的证据。主窗口完整交互与原生选择器验收继续保留。1842009的新双包排队/运行状态以其原生工作流为准，不借用本页旧SHA。


v0.42当前包补记：下载入口已切换到1842009有界重查双包，原包7590363仍保留。持久目录dist/macos-preview-20261105-r41-bounded-recheck；两包各199输入与精确Git树匹配，全部摘要、71框架链接、Mach-O/执行位及依赖核对，迁移/独立CLI/双向16通道/4→8八组恢复通过。两张原生截图已查看，本轮均显示接收就绪；这不覆盖旧ARM端口占用截图，也不替代完整GUI及原生选择器验收。仍为adhoc开发预览。


2026-11-05 v0.46版本范围补记：上方已验收的实际包早于证书续期/指纹迁移功能，不含serve renew、profile-info及trust；新源码和新包的资格分别记录，新包实际下载校验结束后再更换入口。


v0.47当前入口已切换到d4626d0证书版，旧184双包原目录和摘要保留。207应用输入、两份实际迁移和截图核验通过；完整协议和正式发布资格继续按本轮进度记录。


v0.51：当前c3fc781双包迁移/覆盖/恢复报告保留原范围。新增APFS覆盖单通道盘满暴露5/磁盘错误被3/网络错误遮盖；本包早于0017发送期修复，修复的原生盘满和新包仍须验证。


本轮补记（v0.54）：8c8becd四runner核心步骤通过，完整协议仍执行。双Mac物理空间预留盘满14报告/26方向业务均通过；42036465929仍failure，唯一失败为Intel TLS4业务成功后的hdiutil detach资源忙/16。新CI助手仅对自建镜像普通卸载作20秒/8次重试并独立报告，仍待原生复验；原业务错误5/时限不变。公开摘要见[current-validation.json](current-validation.json)，原矩阵及全部历史失败保留。


本轮补记（v0.55）：8c8becd的Ubuntu/双Mac完整job和Alpine完整运行已通过，Windows协议终态待收集。f6128b6双Mac14业务报告/26方向均通过，整体仍failure，Intel TLS1清理为16后旧路径消失/1；新设备映射状态机七项通过，原生复验待执行。新增处置基础在Windows两套工具链通过，尚未接入skip；现有下载包仍精确31f3db3。


v0.55终态补记（2026-11-05）：8c8becd四runner完整运行42036392240已终态success，四套各19核心，Windows38与Ubuntu/双Mac各36协议合计146项原报告SHA逐份核验；Alpine42036458146另19核心/36协议通过。原31f3db3及APFS失败记录继续保留。新增处置基础27b8d21已公开，四runner42043328634、Alpine42043463523及APFS设备清理42043472400已启动，Ubuntu新20核心步骤通过，其它当前资格仍待终态，不继承旧源码结果。skip实际接入及完整交付仍未完成。


v0.56当前补记：27b8d21的Alpine完整20项CTest/36协议已核验；四runner20项核心步骤通过，Ubuntu及ARM Mac完整job成功，Windows/Intel Mac协议终态继续。双Mac APFS42043472400的14业务/26方向/14设备清理全部通过并逐份核验。新增持久跳过准备通过Windows双工具链最终各21项CTest，公开skip、晚期裁决和最终确认仍待接入，见0019。当前可下载预览包保持精确31f3db3，未继承新准备层资格。


v0.61范围补记：上传发送端持久确认/缺项恢复已公开为b9d9b78，[新双Mac部署42078319293](https://github.com/29583855/dukto-next/actions/runs/42078319293)已实际启动；本页下载仍是已验74dd5ce，不能把Windows新功能验证归给旧Mac包，终态和产物核验后再换入口。


v0.62范围补记：b9d9b78双架构原生编译及部署成功，原迁移步骤因临时库glob包含持久处置日志而失败，未替换已验包。修正已上传3fbec42，[双架构新部署42083741936](https://github.com/29583855/dukto-next/actions/runs/42083741936)正在实际运行；本页当前下载仍是74dd5ce，取得终态并核验新产物后更新。


v0.68：Mac下载仍为本页已验db8c774双包；同生产输入Windows r25/Linux5857073实际包已核验。五环境各21核心、Ubuntu/Apple Silicon各39及Alpine39协议已验，Windows/Intel完整终态继续。[当前回执](ci-verification-20261106-r68.json)。


### v0.69 新源码资格说明（2026-11-06）

最新生产源码4da0b12增加双端处置摘要确认，双Windows核心与协议专项通过；精确新提交的原生CI及双Mac部署包已启动，终态和原附件待核验。本页下载仍为已验db8c774生产输入，不声称包含新协议。上一db8c774五环境各21核心、四runner159及Alpine39协议原报告SHA均已核验。见[本轮回执](ci-verification-20261106-r69.json)。


2026-11-06 v0.70：当前入口已切换到精确4da0b12双Mac包。两架构实际编译及迁移成功，各245份应用源码与Git树全集一致、各五份业务报告和四张截图已核验。旧db8c774包和所有历史失败保持原输入；正式发布仍未完成。
