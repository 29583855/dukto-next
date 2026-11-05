# macOS独立开发预览包

更新日期：2026-11-05。当前预览源码为`d0a8e015ab7a419e28ddd9fe12cfc8763acf2999`，C++14/Qt5；Intel和Apple Silicon分别交付GUI与独立CLI，Qt5/OpenSSL运行依赖已放入应用。

## 下载与校验

[d0a8e01双架构打包与迁移工作流](https://github.com/29583855/dukto-next/actions/runs/42049474548)终态success。按Mac芯片选择架构；GitHub附件下载可能需要登录。ZIP内含tar.gz、校验值和原始报告。

| 架构 | GitHub附件 | 内部tar.gz的SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42049474548/artifacts/13427365702) | `6b5fd10bb108696c7020c5bfd0ce1427529aabc7be7e372d6202776720d448b6` |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42049474548/artifacts/13425809966) | `7654d23cb8993540784c8f0d91e469e444c06d7faae7dac74abbe5a24cbb6a84` |

先解压ZIP。Apple Silicon示例（Intel将arm64替换为x86_64）：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

使用tar解包以保留框架链接和执行权限。移动时保留整个目录，CLI启动器和.app保持相邻；应用内独立CLI为`Dukto Next.app/Contents/MacOS/dukto-cli`，无需GUI正在运行。

## 实际验证与边界

GUI保留Dukto设备/最近/关于布局，底部“服务器 · 上传 / 下载”进入服务器页。客户机主动连接服务器、配对、浏览授权目录、上传和下载；下载由客户机发起，服务器无需连接客户机IP。新协议支持1/2/4/8/16并发档位及恢复。CLI保留发现、R6发送/接收、无桌面服务、配对、浏览、上传/下载、任务及明细、暂停/取消/恢复入口。

两架构实际包在中文空格目录、仅系统PATH下完成Cocoa GUI及CLI迁移。arm64的1547份文件、Intel的1705份文件、各71框架链接、包内依赖/adhoc签名、GUI/CLI架构/执行权限及全部载荷摘要核对通过；各225份内附应用源码与精确d0a8e01 Git树逐字节匹配。两架构各五份原业务报告SHA逐份核验：独立CLI、16通道双向、1/4/16覆盖、覆盖恢复及默认4→8恢复。两张实际Cocoa截图已查看，中文显示和接收就绪正常；该截图主要显示首次说明，完整主窗口交互及原生选择器继续单独验收。

本机持久归档：`dist/macos-preview-20261105-r57-receive-preparation/BUILD-RECEIPT.json`。[逐项核验](validation/2026-11-05/delivery-r57-packages-summary.json)和[公开验证索引](current-validation.json)记录实际范围。

d0a8e01的五种原生环境各21项核心/GUI通过；Alpine完整36协议原报告SHA已核验。当前四runner完整运行42049324101仍待双Mac协议终态，Windows和Ubuntu完整job已通过。较早27b8d21四runner各20核心/146协议和双Mac APFS14业务/26故障方向/14设备清理已逐份核验，属于其自身提交。

此包使用adhoc签名；Developer ID、公证/Gatekeeper、干净Mac、完整第三方对应源码/独立重建及正式发布尚未完成。公开skip及其他主计划未完成项继续验收，`deliveryComplete=false`。旧31f3db3包和全部历史失败证据保留。

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
