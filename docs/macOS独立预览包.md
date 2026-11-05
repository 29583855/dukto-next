# macOS独立开发预览包

更新日期：2026-11-05。源码提交：`7590363d99f0dd7c281912e75c07bac526998146`。采用C++14和Qt5，Intel及Apple Silicon分别提供GUI和独立CLI。

## 下载与校验

[原生双架构打包与迁移工作流](https://github.com/29583855/dukto-next/actions/runs/41991697198)已整体通过。根据“关于本机”中的芯片选择架构；`uname -m`也可查看。GitHub附件ZIP中包含实际tar.gz、校验值和验收日志。

| 架构 | GitHub附件 | 内部tar.gz的SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/41991697198/artifacts/13397919636) | `fd11153b8d8d797fb5624dbcb23906c9a68480bd6c5dd500488216b44c9242d7` |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/41991697198/artifacts/13398877218) | `fb7b75e3648a3a6401a8b2097a488ee35775372df85b61400bddf2315997247b` |

先解压下载的ZIP，进入包含tar.gz及.sha256的目录。Apple Silicon示例：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

Intel将命令中的`arm64`替换为`x86_64`。使用tar解包可保留应用框架符号链接和入口执行权限。Qt5、OpenSSL及QML运行依赖已放入应用，不需另装Qt。整体移动解压目录后仍可运行；CLI启动器与.app保持相邻。日常GUI也可放入Applications；其独立CLI位于`Dukto Next.app/Contents/MacOS/dukto-cli`。

## 图形与命令行

打开.app进入与Dukto相近的设备/最近/关于布局，底部“服务器 · 上传 / 下载”进入服务器面板。客户端主动连接服务器，配对后浏览授权目录、上传或下载；服务器无需主动连接客户机。并发档位为1/2/4/8/16，下载、上传与恢复均可选择。

CLI不需要GUI运行，支持发现、R6发送/接收、服务器管理、配对、上传、下载、任务/逐项接收证据查询、暂停、取消与恢复。完整语法执行`./dukto-cli --help`查看，[项目示例](../README.md)列有两端配置及命令。

## 实际验证范围

两种架构均在中文空格新目录、仅系统PATH下运行实际tar：核对所有文件/链接、adhoc签名、Cocoa真实渲染、Qt/OpenSSL实际从包内加载、独立CLI无GUI框架，以及16通道双向、4→8八组恢复和SHA。两种原生截图已查看。两包各199份应用源码另与精确Git树逐字节核对。

7590363双包部署/迁移通过，其完整CI41991583917的Intel为18/19 CTest，唯一失败为原UDP连锁10秒门槛，其他专项继续；ARM核心19/19通过。1842009增加有界批次重查，双工具链及双Mac独立原门槛诊断通过，新的完整原生CI与独立包仍待验。本页现有包不包含1842009重查改动，结果记录于[进度文档](执行进度.md)。

这是使用adhoc签名的开发预览包。Developer ID、公证、Gatekeeper、独立干净Mac、完整第三方对应源码及正式发布验收仍未完成；系统可能要求确认来源。历史失败和后续修正分别记录，完整主窗口交互及原生选择器仍继续验收。


2026-11-05 v0.39补记：此页当前双包已更新到3b8bf4a，包含逐项接收失败原因。旧fa6d96b双包保留于dist/macos-preview-20261105-r38-timeout-attach。新双包部署/迁移通过；同源码完整CI41986605449中Apple Silicon的Core and GUI controller tests步骤失败，尚待该job终态日志定位，其他专项继续原运行。不能将独立包通过写成完整回归通过。


2026-11-05 v0.40补记：3b8完整CI的具体失败已归档为CoreTests::discoveryYieldsAndRejectsMalformedGoodbye，5000包原10秒门槛；服务器GUI和30协议通过。7590363的新双包与完整原生验证继续，未以旧包SHA宣称更新。


v0.41实际交付补记：本页已更新到7590363的双包，保存于dist/macos-preview-20261105-r40-signature-cache。两包各199应用输入及全部框架/签名/依赖核对完成，迁移与双向16通道及4→8八组恢复通过。实际截图已查看，其中ARM截图显示临时接收端口占用；本项GUI检查证明渲染与依赖加载，不能作为该次R6 GUI监听成功的证据。主窗口完整交互与原生选择器验收继续保留。1842009的新双包排队/运行状态以其原生工作流为准，不借用本页旧SHA。
