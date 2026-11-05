# macOS独立开发预览包

更新日期：2026-11-05。源码提交：`fa6d96ba725670f51ceb3e938078af5c815b392d`。采用C++14和Qt5，Intel及Apple Silicon分别提供GUI和独立CLI。

## 下载与校验

[原生双架构打包与迁移工作流](https://github.com/29583855/dukto-next/actions/runs/41980793643)已整体通过。根据“关于本机”中的芯片选择架构；`uname -m`也可查看。GitHub附件ZIP中包含实际tar.gz、校验值和验收日志。

| 架构 | GitHub附件 | 内部tar.gz的SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/41980793643/artifacts/13393997278) | `ec252a8613f18d251e0e8218a352acc60f3c342b83f7679b90a609862d26a59e` |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/41980793643/artifacts/13394675167) | `91b5158547303d4c6867ae7f67c05056544e1bb0cdc60f49f483775240ba517b` |

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

两种架构均在中文空格新目录、仅系统PATH下运行实际tar：核对所有文件/链接、adhoc签名、Cocoa真实渲染、Qt/OpenSSL实际从包内加载、独立CLI无GUI框架，以及16通道双向、4→8八组恢复和SHA。两种原生截图已查看。两包各193份应用源码另与精确Git树逐字节核对。

此前1bc2774的[独立原生恢复CI](https://github.com/29583855/dukto-next/actions/runs/41971997178)的56组会话/故障/字节进度用例也通过，保持原业务速率与期限。当前fa6d96b完整四平台CI仍在执行，结果记录于[进度文档](执行进度.md)。

这是使用adhoc签名的开发预览包。Developer ID、公证、Gatekeeper、独立干净Mac、完整第三方对应源码及正式发布验收仍未完成；系统可能要求确认来源。历史失败和后续修正分别记录，完整主窗口交互及原生选择器仍继续验收。
