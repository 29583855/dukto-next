# macOS独立开发预览包

当前31f3db3在显式覆盖、目标预约及首页服务器入口基础上，修复单通道发送期间远端磁盘错误被网络错误遮盖的问题。旧d4626d0包含入口作用域缺陷，历史包仅按各自原验证范围理解。

更新日期：2026-11-05。源码提交：`31f3db3bfb5a8bf70b6217afd50df3284e27934c`。采用C++14和Qt5，Intel及Apple Silicon分别提供GUI和独立CLI。

## 下载与校验

[31f3db3双架构打包与迁移工作流](https://github.com/29583855/dukto-next/actions/runs/42030403502)已通过。按芯片选择架构；GitHub附件下载可能需要登录，ZIP内含tar.gz、校验值和原始日志。

| 架构 | GitHub附件 | 内部tar.gz的SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42030403502/artifacts/13416925250) | `a566766f24d6bafe97218ed595badd6773494aef45582bac0bcb496707d4c1a5` |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42030403502/artifacts/13417420747) | `7bc1f6f8a966566db426d5377573cadc8f87f588daeb11f3fd944532d9e6ea88` |

先解压下载的ZIP。Apple Silicon示例（Intel将arm64替换为x86_64）：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

tar解包保留框架链接及执行权限。Qt5、OpenSSL和QML依赖已放入应用，无需另装Qt；移动整个目录后仍可运行。CLI启动器与.app保持相邻，应用内独立入口为`Dukto Next.app/Contents/MacOS/dukto-cli`。

## 功能和实际验证

GUI沿用Dukto设备/最近/关于布局，底部“服务器 · 上传 / 下载”进入服务器面板。客户机主动连接服务器、配对、浏览授权目录、上传和下载；服务器无需主动连接客户机。上传、下载及恢复支持1/2/4/8/16档位。CLI支持发现、R6发送/接收、服务器管理、配对、任务/接收证据、暂停、取消和恢复，独立于GUI运行；命令见`./dukto-cli --help`及[项目示例](../README.md)。

两架构实际tar在中文空格新目录、仅系统PATH下运行Cocoa GUI和CLI，71框架链接、Mach-O/执行位、adhoc签名、Qt/OpenSSL包内加载及213应用输入与精确31f3db3树匹配。各五项业务原报告SHA逐份核对，包含16通道双向、双向1/4/16覆盖、已有文件4→8恢复和默认恢复。两张实际包截图已查看，中文和接收就绪显示正常。

完整回执：`dist/macos-preview-20261105-r53-peer-close-macos-terminal/BUILD-RECEIPT.json`。核验汇总：[本轮证据](validation/2026-11-05/peer-close-r53-packages-and-validation-summary.json)。主窗口导航另由生产QML/真实Controller的编译测试程序通过，不称直接操作部署.app或完整原生选择器验收。

完整31f3db3矩阵42028894157仍为failure：Intel36项协议全部通过，但证书页按钮测试失败；ARM有会话到期日志观察失败。原附件和日志保留，测试修正本机已通过，新的原生复验待执行。31f3db3双Mac APFS14份报告已通过；6012114重复测试Intel的R6未成功注入、TLS4超时仍是失败，新的物理空间预留夹具待原生验证。

当前为adhoc签名开发预览。Developer ID、公证、Gatekeeper、独立干净Mac、完整第三方对应源码和正式发布尚未完成。完整功能验收继续按主计划，deliveryComplete=false。

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
