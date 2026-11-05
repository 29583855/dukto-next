# macOS 构建与验收

更新日期：2026-11-05。状态：Intel/Apple Silicon原生C++14 GUI/CLI、各18项CTest、20项独立TLS、Cocoa渲染及面板恢复已通过；修正测试代理累计超睡后，四组默认单通道双向会话通过。1bc2774两架构独立预览包迁移和56组恢复专项已通过；完整最新CI与正式发布资格仍分开验收。

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
| CLI/TLS 与恢复 | 既有协议/服务/权限/多通道/重试/最终确认及新增 fail 冲突、4→8 八组恢复 | 四组单通道双向默认会话已通过；62f49c1完整矩阵ARM64为26/26，Intel为22/26，失败继续处理 |
| 资源采样 | 严格活动进程错误、512 MiB 门槛及短命进程；Darwin 原生线程采样 | 两种架构实际自检通过；Darwin 采用 libproc 线程 ID/RSS/physical footprint |

渲染检查强制选择原生插件，记录窗口/QML 根/屏幕/帧缓冲和缩放几何；CI 小屏幕自动缩窗不再被误当作固定 430×700。失败时也保留截图与实际反馈。offscreen 只用于独立 CTest。它覆盖主入口及首次说明画面；面板恢复覆盖服务器页按钮。完整主窗口交互、原生文件/目录选择器和其他画面仍需单独验收。

## 结果与下一步

初次提供的 airen3339/dukto-next 对本机账号仅有读取权限。用户随后明确授权使用当前 29583855 账号创建公开仓库并操作上传、编译，已创建 [29583855/dukto-next](https://github.com/29583855/dukto-next)。现已上传跨平台共用源码与工作流并实际执行多轮原生编译，初始提交 a51a5ec；当前已编译源码62f49c1e0a0f66f08f80928bae3ca14414f5637b，其生产C++与da2799b一致。

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

## 历史编译结果（源码 9198cb5，2026-11-05）

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

## 3360496编译与独立专项验证（2026-11-05）

[本轮CI](https://github.com/29583855/dukto-next/actions/runs/41958459234)已编译两个Mac架构，附件已下载并核对GitHub ZIP、内部tar、源码提交、Mach-O CPU和执行权限；原始字节存于本机dist/macos-compiled-20261105-r30。

| 架构 | 原生编译附件 | tar SHA-256 |
| --- | --- | --- |
| Apple Silicon | [ARM64](https://github.com/29583855/dukto-next/actions/runs/41958459234/artifacts/13383893253) | 4a372e85ce5edf06e4301579b68126d5ad62031c9da251af3266e6edc9acda81 |
| Intel | [X64](https://github.com/29583855/dukto-next/actions/runs/41958459234/artifacts/13384610507) | 080af8e6f97542760e528eab5c65377e9adde1736967acfe3e726bfa4fbe6f9f |

[原生报告与失败证据](validation/2026-11-05/github-evidence-r30-intel-terminal/receipt.json)保留。ARM64为18/18 CTest（188.53秒）；Intel为17/18，UDP连锁5000次变更超过原10000ms门槛，QTest诊断需12450ms。两者20项独立TLS、Cocoa主入口、面板4→8进程恢复及四组逐连接错误根因专项通过。两Mac仍在单通道上传到期时确认0字节，完整协议步骤未通过，后续专项尚未执行。

新增诊断记录客户端分阶段事件时间，但单通道上传会到块确认时才消费接收进度，不能把客户端首个进度时间冒称服务端首个正文时间。下一轮增加接收日志/临时文件大小及有界不透明TLS代理计数，原20秒会话、512KiB/s、45秒退出、30秒就绪、90秒恢复继续保持。CI将逐项执行并汇总所有既有专项，失败仍导致总步骤失败，后续专项可提供独立结果。自包含部署、签名、公证、干净系统和完整发布仍未完成。

## v0.31 原生诊断补充（2026-11-05）

两架构单独UDP复验已通过；原完整Intel超时仍保留。短会话接收临时文件不足首个4MiB块，继续使用原20秒会话和512KiB/s代理，新增实际收包/限速/发包耗时，两个方向独立执行。这只是诊断，当前完整业务及自包含部署资格尚未通过。共享SQLite并发校验已在Windows复现并修复，新源码的原生Mac构建/测试结果仍待上传后的实际CI。

## 原生部署预览流程（2026-11-05，实际验证中）

[macos-package.yml](../.github/workflows/macos-package.yml)手动运行两架构本机编译与Qt5部署，[打包脚本](../scripts/package_macos.py)保留原编译件，部署框架/QML及独立CLI，逐个检查Mach-O依赖并使用本地adhoc签名。[迁移专项](../tests/macos_package_integration.py)在中文空格目录解开真实tar，以系统PATH运行并核对dyld实际加载来源、CLI不加载GUI框架、Cocoa入口、16通道双向与4→8恢复。原生执行已发现并修正brotli及QtPrintSupport遗漏依赖；c49dc9d的ARM64实际tar迁移已通过，Intel仍在部署阶段超时，具体身份见下文。Developer ID、公证、Gatekeeper、干净系统、完整对应源码及正式发布资格仍须单独完成。

## 计时偏差的实际证据（2026-11-05）

[双方向原生诊断](https://github.com/29583855/dukto-next/actions/runs/41962777596)显示ARM64上传代理名义睡眠7.581秒、实际20.601秒，下载6.905秒、实际18.601秒。先修正代理重复相对睡眠造成的限速偏差：保持原速率和期限、按单调期限补偿、补偿上限0.25秒。真实TCP注入70ms超睡已在Windows验证2MiB用时4.079秒；两Mac原门槛已实际通过，具体记录见下文。这是测试基础设施修正，未宣称产品性能问题已经解决。

部署首轮ARM64在严格检查中发现libbrotlidec依赖的libbrotlicommon未被macdeployqt部署，已保留原失败。打包器新增从已安装Cellar精确匹配传递库、来源和原摘要记录、加载名修正及独立CLI/GUI框架rpath检查；新原生结果待验，不跳过缺库校验。

## 两架构原会话门槛通过（2026-11-05）

[0df8231原生诊断](https://github.com/29583855/dukto-next/actions/runs/41963964567)两架构单通道上传/下载全部通过原门槛；ARM64恢复16.129/9.622秒，Intel为24.197/15.161秒，持久复用与摘要全部核对。ARM64 job成功；Intel UDP链5000/10秒仍超时（本次10250ms足够），因此Intel job仍失败，继续独立采样定位。da2799b两架构18/18 CTest（204.60/240.73秒）及实际编译tar已归档到dist/macos-compiled-20261105-r31。原完整CI因新夹具替代而取消，完整产品资格仍不能勾选。部署预览发现QtPrintSupport框架传递依赖，新增完整框架复制与自身ID区分后继续原生验证。

## v0.33 APFS真实磁盘满（2026-11-05）

[双架构原生工作流](https://github.com/29583855/dukto-next/actions/runs/41967829452)整体成功；[六份实际报告及源码关联](validation/2026-11-05/macos-apfs-qualification-r33.json)记录两种架构各自创建的256MiB APFS隔离镜像上的原协议和4/16通道双向TLS写满、已有持久检查点、原文件保护、释放空间后恢复及SHA核对。上传按明确失败后新请求恢复，下载恢复原任务；两者语义分别记录。控制记录存放在另一个未写满的临时卷，因此不代表元数据卷同时写满或完整故障矩阵通过。

62f49c1的独立UDP/四组单通道原门槛会话CI也整体成功，原Intel间歇超时保留。部署已生成两架构依赖闭包和adhoc签名tar；迁移需识别系统Cryptex中的缓存镜像，已依据Apple公开dyld API增加原生缓存成员核验，第三方路径仍严格限定包内。原始失败均保留；当前终态及后续修复见下文，Developer ID/公证、干净系统和正式发布未完成。

## v0.34 终态核对与初始化竞争修正（2026-11-05）

- [x] [62f49c1完整CI](https://github.com/29583855/dukto-next/actions/runs/41966084944)已结束：Ubuntu全部通过；ARM64各18项CTest、20项独立TLS、Cocoa及26/26协议通过。Windows为18项CTest及26/28协议通过；Intel为18项CTest、TLS/Cocoa及22/26协议通过。整体failure已保存，不以通过子项代替整体结果。
- [x] [c49dc9d ARM64实际部署包](https://github.com/29583855/dukto-next/actions/runs/41968009381/artifacts/13389365034)通过中文空格目录、系统PATH、包内Qt/OpenSSL真实加载、独立CLI无GUI框架、Cocoa渲染、16通道双向及4→8八组恢复。tar SHA256为e6de953e1a63c96dbb3a1fc09caa19f4115f1f2834151d3f4c865801a402a5a5；1547文件、71链接、77 Mach-O、183应用源码逐字节核验。该包对应c49dc9d，不包含本节新增初始化轮询。Intel同轮因macdeployqt原300秒工具预算失败，整个工作流failure。
- [x] Windows TLS失败已定位为测试证书继承OpenSSL1.1默认v3_ca后再次-addext导致basicConstraints重复；测试改用独立req配置。生产证书信任与用途/有效期/主机名/pin拒绝规则保持。MSVC/UCRT新构建均通过20项TLS。
- [x] 任务初始化保留原5秒上限及活进程锁语义，以最多10ms非阻塞轮询代替Qt长退避；两工具链各18项CTest、真实八进程持锁竞争、活持锁进程5秒拒绝及kill后恢复通过。MSVC竞争0.359秒、拒绝5.031秒；UCRT具体数值见任务专项报告。旧本机实现在本次额外竞争中也通过，因此尚不能宣称CI原初始化失败根因完全证明，须Windows CI复验。
- [ ] Intel完整协议仍有16通道下载会话恢复的连接断开，以及fail恢复/八组恢复/字节进度的中途暂停竞态。下一步增加有界服务端关闭诊断并在真实持久检查点处设置测试数据转发屏障，仍须在完整传输前注入故障，保留原速率、SHA和恢复时限。
- [ ] 新Mac打包仅把macdeployqt工具预算改为有界900秒并保存超时部分输出；业务测试期限保持。新源码尚待上传后的双架构原生部署和完整CI。Developer ID/公证、干净系统、完整对应源码及其他主计划未完成项继续保留；deliveryComplete=false。

## v0.35 持久检查点故障协调与诊断（2026-11-05）

- [x] 2627d48已上传，新四平台CI已实际编译两Mac架构。两种架构的[部署工作流](https://github.com/29583855/dukto-next/actions/runs/41970508922)都完成依赖部署/签名、Cocoa和16通道双向；Intel在900秒预算内完成Qt部署。迁移中的4→8专项均在暂停请求到达前完成，故整个工作流仍failure，原tar与日志保留。不能把工具阶段通过当成包的完整迁移资格。
- [x] 新增仅用于测试的透明TLS检查点屏障：每流初始128KiB、最多128条流，只给单条数据流逐次4MiB额度，接收日志实际确认增加后再追加；达到原阈值后冻结已有数据流，允许新管理连接。暂停/取消提交或进程退出后才放开，原4MiB/s、30秒就绪和90秒恢复保持。明确要求故障前确认量小于批次总量，不接受已完成代替中途故障。
- [x] UCRT四文件50%阈值rename八组恢复、MSVC fail八组恢复全部通过；故障前真实确认约20MiB、完整33,554,448字节，恢复保持同任务/请求/原策略及最终SHA。两种策略各自报告，不以零错误标记代替结果。
- [x] 字节进度原六组1/4/16双向通过；4通道在真实检查点暂停后8通道恢复。MSVC额外对本测试task/pause命令各注入1.5秒启动延迟仍六组通过。检查点后等待完整300ms再放行有限片段，触发产品原250ms节流进度；保留最初协调器超时失败，不修改生产进度规则。
- [x] 共用服务输出报告保留最后16条事件；会话恢复失败把最后16条客户端及服务端原因写入报告，仍使原专项失败。UCRT16通道下载原门槛会话到期确认/复用134,217,728字节，恢复4.185秒并校验SHA；这不替代Intel原生失败的根因证据。
- [ ] 新增双Mac独立恢复工作流，包含六组原会话、两种策略各八组恢复及六组字节进度；上传后实际执行，完整CI也须复验。154份维护文件审计无TODO/未实现标记，C++14配置及格式检查通过；项目仍有主计划未完成项，deliveryComplete=false。

## v0.36 双Mac独立预览交付（2026-11-05）

- [x] 已授权的公开仓库为[29583855/dukto-next](https://github.com/29583855/dukto-next)。共用C++14源码1bc2774的[双架构部署工作流](https://github.com/29583855/dukto-next/actions/runs/41972000613)整体success，Intel/Apple Silicon GUI与独立CLI均完成真实编译、Qt/OpenSSL部署、adhoc签名核对、中文空格目录系统PATH迁移、Cocoa实际画面、16通道双向和4→8八组恢复。两份原生截图均已人工查看。
- [x] 两份GitHub原始ZIP和内部tar已下载到持久dist/macos-preview-20261105-r35-checkpoint-qualified；ARM64为1547文件/71链接/77 Mach-O，Intel为1705文件/71链接/75 Mach-O；每包185份应用源码与精确Git树逐字节核对，归档SHA、架构和入口执行位通过。下载、SHA与GUI/CLI用法见[Mac独立预览包](macOS独立预览包.md)。
- [x] [双架构恢复专项](https://github.com/29583855/dukto-next/actions/runs/41971997178)整体success：各六组1/4/16双向会话、rename/fail各八组故障、六组字节进度，共56组。会话保持20秒/512KiB/s/45秒退出/30秒就绪/90秒恢复；12次恢复为6.848–17.393秒。两种架构16通道下载均在确认64MiB后复用同量并恢复成功；原Intel连接断开历史保留，本轮未复现不等于证明该间歇故障根因。
- [x] 2627d48[完整CI终态](https://github.com/29583855/dukto-next/actions/runs/41970484287)为Windows/Ubuntu success，两Mac failure。Windows各18项CTest及28/28协议通过，含新初始化竞争及20项TLS；实际八进程预持锁竞争0.663秒，活持锁者5.026秒仍正确拒绝。两Mac各18项CTest、20项TLS/Cocoa及24/26协议通过，仅两个旧夹具中途暂停专项失败；新夹具上述原生独立复验已通过，历史失败保留。
- [x] Windows r17实际独立ZIP系统PATH迁移通过，SHA4825c481916e8daa5ee81b0d3180737a87a3e143b12f3a509892110f7fdba944，包含2627d48初始化轮询和新测试输入。185份应用源码与1bc2774完整核对；24受信签名包的364个部署文件、53份许可重新核对。与旧r16分开保留，不借用旧包SHA。
- [ ] 1bc2774新完整四平台CI仍在执行，当前Ubuntu已成功，其他runner继续。独立Linux187文件快照已送入新/home/dukto/checkpoint-r35，按glibc→musl顺序全新构建，旧长测及旧资格目录未改。Mac预览包为adhoc开发包；Developer ID/公证、独立干净Mac、完整对应源码、原版全基线/完整原生交互、全预算/回收、四冲突策略、24小时、物理LAN、3×3及正式发布仍未完成。deliveryComplete=false。
