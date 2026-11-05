# macOS 构建与验收

更新日期：2026-11-05。状态：双架构 CI 已配置，尚未在 GitHub 实际运行，不能据此标记 macOS 支持已经验收。

## 运行环境

工程保持 C++14、Qt 5.15、CMake，共用现有核心、GUI 和独立 CLI。开发助手通过 CI 安装 Qt5、OpenSSL 和测试依赖，不要求用户预装 Qt5。

工作流 [build.yml](../.github/workflows/build.yml) 分别使用 `macos-15-intel` 和 `macos-15`，在运行时检查实际 CPU 为 x86_64/arm64。安装使用 `brew install qt@5 openssl@3`，通过各自 Homebrew 前缀设置 `CMAKE_PREFIX_PATH`、`OPENSSL_ROOT_DIR` 和 Qt 工具路径，避免混用两种架构的依赖。

已只读核对 [Homebrew Qt5 元数据](validation/2026-11-05/macos-qt5-brew-formula-r28.json)：版本 5.15.19，当前 `disabled=false`。这仅证明公式元数据状态，实际下载、安装和运行结果仍由每次原生 CI 记录。

## 已接入的检查

| 检查 | 执行与证据 | 当前状态 |
| --- | --- | --- |
| 原生工具链 | 系统/CPU、Xcode/SDK、编译器、CMake、qmake、OpenSSL；Homebrew JSON | 配置完成，实际结果待运行 |
| C++14 GUI/CLI 编译 | 完整应用、独立 CLI、QtTest 与测试探针 | 待两种架构实际通过 |
| 核心与 QML | 18 项 CTest，包含严格路径、日志、并发、任务、生产服务器面板 | 待两种架构实际通过 |
| 完整主入口渲染 | 强制 `QT_QPA_PLATFORM=cocoa`，隔离中文空格目录，启动 `.app` 的实际 GUI，保存 PNG | 脚本在 Windows 原生环境已通过；macOS 待运行 |
| Cocoa 面板进程恢复 | 真实按钮、退出旧面板进程、重开面板并恢复同一任务、复用已同步数据 | 待两种架构实际通过 |
| CLI/TLS 与恢复 | 既有协议/服务/权限/多通道/重试/最终确认及新增 fail 冲突、4→8 八组恢复 | 待两种架构实际通过 |
| 资源采样 | 严格活动进程错误、512 MiB 门槛及短命进程；Darwin 原生线程采样 | 待 macOS 实际通过 |

渲染检查强制选择原生插件，不用 offscreen 结果代替 Cocoa。它覆盖主入口及首次说明画面；面板恢复覆盖服务器页按钮。完整主窗口交互、原生文件/目录选择器和其他画面仍需单独验收。

## 结果与下一步

初次提供的 airen3339/dukto-next 对本机账号仅有读取权限。用户随后明确授权使用当前 29583855 账号创建公开仓库并操作上传、编译，已创建 [29583855/dukto-next](https://github.com/29583855/dukto-next)。接下来上传跨平台共用源码与工作流，运行两种原生 macOS 架构。

macOS 编译成功后即保存实际 GUI/独立 CLI，artifact 为 `macos-compiled-X64` 和 `macos-compiled-ARM64`；内部 tar 保留应用链接和可执行权限，附源码提交 SHA、许可证及摘要。这是仍需匹配 Qt5/OpenSSL 的编译输出，自包含发布包、签名和公证继续单独验收。每个原生 runner 无论成功或失败均保存日志与 JSON，截图也加入归档；对应 artifact 为 `validation-macos-15-intel` 和 `validation-macos-15`。仅工作流结构已通过[静态核对](validation/2026-11-05/ci-structure-r28.json)，`remoteActionsExecuted=false`。

CI 通过后继续实际桌面交互、三平台互通、macOS 独立 GUI/CLI 包、运行依赖、签名与分发、干净系统及对应源码验证。当前 runner 使用 macOS 15，最低支持版本须由实际构建部署目标和对应环境验证确定。
