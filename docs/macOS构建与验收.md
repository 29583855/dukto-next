# macOS 构建与验收

更新日期：2026-11-05。状态：Intel/Apple Silicon 原生 GUI/CLI 编译、严格资源采样及各 18 项 CTest 已实际通过；20 项独立 TLS、Cocoa 主入口渲染及面板进程恢复已通过；短会话到期检查点失败，完整业务仍未通过，尚未完成 macOS 全部发布验收。

## 运行环境

工程保持 C++14、Qt 5.15、CMake，共用现有核心、GUI 和独立 CLI。开发助手通过 CI 安装 Qt5、OpenSSL 和测试依赖，不要求用户预装 Qt5。

工作流 [build.yml](../.github/workflows/build.yml) 分别使用 `macos-15-intel` 和 `macos-15`，在运行时检查实际 CPU 为 x86_64/arm64。安装使用 `brew install qt@5 openssl@3`，通过各自 Homebrew 前缀设置 `CMAKE_PREFIX_PATH`、`OPENSSL_ROOT_DIR` 和 Qt 工具路径，避免混用两种架构的依赖。

已只读核对 [Homebrew Qt5 元数据](validation/2026-11-05/macos-qt5-brew-formula-r28.json)：版本 5.15.19，当前 `disabled=false`。这仅证明公式元数据状态，实际两种架构已安装 Qt5.15.19 并完成编译，下载、安装和工具链版本保留在每次原生 CI 的日志与依赖 JSON 中。

## 已接入的检查

| 检查 | 执行与证据 | 当前状态 |
| --- | --- | --- |
| 原生工具链 | 系统/CPU、Xcode/SDK、编译器、CMake、qmake、OpenSSL；Homebrew JSON | 两种架构的真实系统/工具链/依赖版本已归档 |
| C++14 GUI/CLI 编译 | 完整应用、独立 CLI、QtTest 与测试探针 | 两种架构实际编译通过；后续改动按提交继续复验 |
| 核心与 QML | 18 项 CTest，包含严格路径、日志、并发、任务、生产服务器面板 | 9198cb5 两种架构各 18/18 实际通过（ARM64 168.00 秒；Intel 197.26 秒） |
| 完整主入口渲染 | 强制 `QT_QPA_PLATFORM=cocoa`，隔离中文空格目录，启动 `.app` 的实际 GUI，保存 PNG | 两种架构通过；实际帧缓冲 ARM64 430×653、Intel 430×700，PNG 已查看 |
| Cocoa 面板进程恢复 | 真实按钮、退出旧面板进程、重开面板并恢复同一任务、复用已同步数据 | 两种架构通过：4→8 下载、真实退出/重开面板，同任务和已同步数据复用 |
| CLI/TLS 与恢复 | 既有协议/服务/权限/多通道/重试/最终确认及新增 fail 冲突、4→8 八组恢复 | 基础 R6/CLI/崩溃/POSIX/服务/身份列表通过；会话到期失败，后续完整专项未执行 |
| 资源采样 | 严格活动进程错误、512 MiB 门槛及短命进程；Darwin 原生线程采样 | 两种架构实际自检通过；Darwin 采用 libproc 线程 ID/RSS/physical footprint |

渲染检查强制选择原生插件，记录窗口/QML 根/屏幕/帧缓冲和缩放几何；CI 小屏幕自动缩窗不再被误当作固定 430×700。失败时也保留截图与实际反馈。offscreen 只用于独立 CTest。它覆盖主入口及首次说明画面；面板恢复覆盖服务器页按钮。完整主窗口交互、原生文件/目录选择器和其他画面仍需单独验收。

## 结果与下一步

初次提供的 airen3339/dukto-next 对本机账号仅有读取权限。用户随后明确授权使用当前 29583855 账号创建公开仓库并操作上传、编译，已创建 [29583855/dukto-next](https://github.com/29583855/dukto-next)。现已上传跨平台共用源码与工作流并实际执行多轮原生编译，初始提交 a51a5ec；当前已编译源码 9198cb5d1f5d49edd855307f5b2aa383f3e3204c。

macOS 编译成功后即保存实际 GUI/独立 CLI，artifact 为 `macos-compiled-X64` 和 `macos-compiled-ARM64`；内部 tar 保留应用链接和可执行权限，附源码提交 SHA、许可证及摘要。这是仍需匹配 Qt5/OpenSSL 的编译输出，自包含发布包、签名和公证继续单独验收。每个原生 runner 无论成功或失败均保存日志与 JSON，截图也加入归档；对应 artifact 为 `validation-macos-15-intel` 和 `validation-macos-15`。[原工作流静态记录](validation/2026-11-05/ci-structure-r28.json)仅反映运行前历史状态。现在 remoteActionsExecuted=true，实际编译与测试记录见下表，不能用整体 CI 失败掩盖已通过子项，也不能用编译通过冒称整体 CI 成功。

CI 通过后继续实际桌面交互、三平台互通、macOS 独立 GUI/CLI 包、运行依赖、签名与分发、干净系统及对应源码验证。当前 runner 使用 macOS 15，最低支持版本须由实际构建部署目标和对应环境验证确定。


## 实际运行与修复记录

| 源码 / 运行 | 实际结果与边界 |
| --- | --- |
| [a51a5ec 首轮](https://github.com/29583855/dukto-next/actions/runs/41949900282) | Qt5 安装成功；两 Mac 的已签名 Python 线程 Mach 采样被拒绝。原日志/附件保留，改用 libproc，未放宽权限错误和内存限额 |
| [7f47dcf 第二轮](https://github.com/29583855/dukto-next/actions/runs/41950525717) | 两 Mac 实际 GUI/CLI 编译和采样通过；[下载并验证 Mach-O/提交/权限/压缩摘要](validation/2026-11-05/github-evidence-r28-native-compiled/receipt.json)。运行测试发现 APFS/证书差异，整体失败保留 |
| [b11752a 第三轮](https://github.com/29583855/dukto-next/actions/runs/41951279050) | APFS 改用 statfs 查询目标卷；SecureTransport 的已固定叶证书独立验证自签/算法/用途/日期/SAN。两 Mac 各18/18通过；[完整原始证据](validation/2026-11-05/github-evidence-r29-apfs-pin-tests/receipt.json)。Cocoa 字体警告及 Ubuntu 更新检查/Windows 合成记录所有者错误保留 |
| [4989047 第四轮](https://github.com/29583855/dukto-next/actions/runs/41951998010) | Menlo 修复已生效，Cocoa 退出0/空标准输出错误；CI 屏幕限制使窗口430×653，原固定比例断言失败。Ubuntu 确认合法版本1.0.0被旧解析路径拒绝 |
| [f25625c 历史复验](https://github.com/29583855/dukto-next/actions/runs/41952908873) | 按实际原生几何验证；显式有界三段版本解析；Windows 合成记录创建即绑定真实私有所有者/DACL；独立 TLS 边界专项前置。历史 TLS 测试端证书加载失败；后续见 9198cb5 记录 |

本机同一 APFS/证书修复源码 [18/18 Windows UCRT](validation/2026-11-05/ctest-macos-compat-r29-ucrt.log)、[独立 TLS 拒绝边界](validation/2026-11-05/secure-channel-macos-compat-r29-ucrt.json)通过。后续几何/版本/字体修改的[两项回归](validation/2026-11-05/ctest-version-font-r29-ucrt.log)、[真实 Windows 原生截图与几何](validation/2026-11-05/native-geometry-r29-windows.json)及[私有合成记录分页](validation/2026-11-05/client-list-explicit-owner-r29-ucrt.json)通过。它们各自覆盖明确范围，不代替 Mac 原生结果。

## 当前已交付的编译结果（源码 9198cb5，2026-11-05）

[原生 CI 与完整日志](https://github.com/29583855/dukto-next/actions/runs/41954110035)已完成两种 Mac job。两者整体结论均为 failure：编译和已列子项实际通过，业务步骤因会话到期专项失败而停止；不改变原测试时限来取得通过结果。

| 架构 | GUI 与 CLI 编译附件 | 内部 tar SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [macos-compiled-ARM64](https://github.com/29583855/dukto-next/actions/runs/41954110035/artifacts/13381379149) | 6a048f0380c570f01d9b3439fc4629949911d32598ef666506b9ef7841f21061 |
| Intel / x86_64 | [macos-compiled-X64](https://github.com/29583855/dukto-next/actions/runs/41954110035/artifacts/13381359525) | e23e2a4b509492300ae0b6d4596757d527f935216d1312b11f37d594e00893b4 |

两份附件已完整下载，逐层核对 GitHub ZIP 摘要、内部 tar 摘要、源码提交、Mach-O CPU、应用 Info.plist 及 GUI/CLI 可执行权限。[本机结果](validation/2026-11-05/github-macos-result-r29.json)与[原始归档](validation/2026-11-05/github-evidence-r29-dual-native-final/receipt.json)保留；编译输出另存本机 dist/macos-compiled-20261105-r29/。Actions 附件受平台保留期限限制。

- [x] 两种架构自动安装 Qt5/OpenSSL，完成 C++14 GUI/CLI 编译；18/18 CTest 和 20 项独立 TLS 正反例通过，含“正确固定指纹但仅限 clientAuth”的拒绝。
- [x] 两种架构强制 Cocoa 原生主入口渲染通过；实际截图已核对。生产服务器页 4→8 下载、退出/重开进程后恢复同一任务并复用确认数据通过。
- [x] 两种架构 R6、CLI 契约、崩溃、POSIX 路径、服务/配对/分页浏览、身份列表以及凭据轮换专项通过。
- [ ] R29-01：两 Mac 的 session_expiry_integration 在 upload/1 的已持久确认量为 0（要求大于0）；任务已 interrupted，无完成文件。保留20秒会话、512KiB/s、45秒退出、30秒就绪、90秒恢复配置。下一步增加分阶段诊断，查明准备/传输/检查点时序；未执行到后续恢复和其他完整业务专项。
- [ ] R29-02：同一提交的 Ubuntu CI 已通过会话/排队/重试，fail 冲突16通道遇到目标目录时返回7/parallel，预期4/conflict；检查并行取消与原始冲突错误传播。后续脚本及磁盘专项被 shell 失败状态跳过，不能算通过。
- [ ] 独立打包部署、所有原生交互/选择器、物理 LAN、三平台3×3、长时稳定性、签名公证、干净系统、第三方对应源码重建及完整交付仍开放。

同一运行四个runner现已全部结束，整体为failure；Windows会话/排队通过，重试中的远程暂停返回4/parallel而预期7，另记R29-03。两Mac已列通过项不变，后续业务继续验收。[完整终态](validation/2026-11-05/terminal-state-r29.json)与[全量附件](validation/2026-11-05/github-evidence-r29-all-runners-terminal/receipt.json)保留。
