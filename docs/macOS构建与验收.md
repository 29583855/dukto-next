# macOS 构建与验收

更新日期：2026-11-06，计划v0.64。7772151已上传，新双Mac打包42096271845与原生矩阵待验。当前已验下载保持3fbec42：Intel/Apple Silicon GUI、独立CLI及Qt5/OpenSSL依赖编译部署迁移通过，各234份应用源码和各五业务原报告核验。其完整四runner154/155，Windows私有配置替换失败；Ubuntu/双Mac各38和Alpine38通过。正式签名/公证与完整验收继续。

## 运行环境

工程保持 C++14、Qt 5.15、CMake，共用现有核心、GUI 和独立 CLI。开发助手通过 CI 安装 Qt5、OpenSSL 和测试依赖，不要求用户预装 Qt5。

工作流 [build.yml](../.github/workflows/build.yml) 分别使用 `macos-15-intel` 和 `macos-15`，在运行时检查实际 CPU 为 x86_64/arm64。安装使用 `brew install qt@5 openssl@3`，通过各自 Homebrew 前缀设置 `CMAKE_PREFIX_PATH`、`OPENSSL_ROOT_DIR` 和 Qt 工具路径，避免混用两种架构的依赖。

已只读核对 [Homebrew Qt5 元数据](validation/2026-11-05/macos-qt5-brew-formula-r28.json)：版本 5.15.19，当前 `disabled=false`。这仅证明公式元数据状态，实际两种架构已安装 Qt5.15.19 并完成编译，下载、安装和工具链版本保留在每次原生 CI 的日志与依赖 JSON 中。

## 早期检查记录（按表中源码）

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

初次提供的 airen3339/dukto-next 对本机账号仅有读取权限。用户随后明确授权使用当前 29583855 账号创建公开仓库并操作上传、编译，已创建 [29583855/dukto-next](https://github.com/29583855/dukto-next)。现已上传跨平台共用源码与工作流并实际执行多轮原生编译，初始提交a51a5ec；ecb0387完整原生矩阵已成功，当前fa6d96b两种Mac架构也已编译成功，部署包和新完整测试按精确提交分别验收。

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

## v0.37 完整原生CI追加证据

2026-11-05，固定1bc2774完整运行41971957335的Mac ARM64与Intel均成功：每架构18CTest和26/26协议专项通过，包括新的rename/fail检查点协调、会话、4→8恢复及字节进度。该运行整体仍因Windows旧协议异常帧超时为failure。双Mac旧预览包的SHA和源码身份不变；新增加的逐项分页属于下一源码修订，另行原生编译验证，不能借用旧包结果。


v0.37 实际上传补记：源码已推送为 `ecb0387f135e89d6eea7b1c41bcc215c31f2bdad`；[新四平台原生CI](https://github.com/29583855/dukto-next/actions/runs/41977378181)已启动，尚未以其在途状态标记通过。157份维护文件审计0标记，C++14配置及格式检查通过。旧预览包不含新增分页。冻结1bc2774的glibc资格已结束：18CTest（490.30秒）、12检查组中10组通过，session-expiry和conflict-fail失败；二进制前后SHA不变，`results.tar.gz`和driver-result已归档。musl由原3978驱动继续；失败继续计入总计划。

## v0.38 网络期限与数据通道加入时序（2026-11-05）

- [x] 旧UCRT/MSVC各自真实进程暂停复现：先收8字节、暂停后发送其余内容、6秒后恢复，正常文件与非法文本均被旧代码错误归为网络超时；静默/部分帧停滞仍按5秒失败。对应`legacy-timeout-r38-before-*.json`保留。修复网络I/O独立计时及已缓冲数据读取顺序，新版各四组通过，原5秒期限未放宽；旧CI的具体子样本和调度不足，不能宣称那次根因已唯一证明。
- [x] 对冻结旧glibc二进制进行新的独立诊断：4/16通道共16次同名目录冲突，其中4次客户端误报3/protocol，服务端所有连接及持久任务仍为4/conflict，原目标均保留。发现并修复“公布就绪早于Attached确认写出”的竞态：唯一预约、完成确认、再公布就绪；重复票据拒绝不进入组取消区。新回归逐次核对全部连接和任务，Windows两套工具链各16次通过。
- [x] 两套Windows实际C++14 GUI/CLI构建及各18/18 CTest通过（UCRT108.58秒、MSVC118.33秒）；各9项协议专项通过：旧协议、原5秒停滞、新加入时序、延迟控制根因、双向1/4/16冲突、自动重试、默认会话到期/90秒恢复、源/授权故障、字节进度。二进制摘要在整组前后相同，见`timeout-attach-r38-*-summary.json`。159份维护文件审计0标记，格式/C++14检查通过；不据此勾选完整交付。
- [x] 新增两项回归并接入三平台完整CI和本机verify；R6异常样本失败现在保留样本名。时序及期限契约见`decisions/0011-网络期限与多通道加入确认.md`。
- [ ] 新固定194文件源码快照SHA `e18cc41ce84da2340ae2097ba2b65b45b6e62845c93770fb8e3266d58dbca9f4`在独立`/home/dukto/timeout-attach-r38`构建/验证；不得改用或覆盖旧冻结输入。旧3978驱动继续musl；旧glibc10/12资格失败、90秒恢复超时继续保留，当前修复不宣称解决该性能失败。
- [ ] 新修复上传后继续Intel/ARM Mac和Ubuntu/Windows完整原生验证，独立预览包按其精确源码另验。目前可用Mac独立包仍为1bc2774，旧Windows包仍不含新分页及本轮修复。含分页的ecb0387已编译双Mac，其41977378181运行结果按各runner归档，未结束者不勾选通过。
- [ ] skip/overwrite、逐项处置及完成摘要、完整预算/安全GC、证书生命周期、原版全基线/原生交互、物理LAN/3×3/当前24小时、完整盘满矩阵、干净系统及签名公证/对应源码继续按主计划推进。deliveryComplete=false。


v0.38 原生与部署补记（2026-11-05）：

- [x] 含逐项查询的固定`ecb0387`完整运行[41977378181](https://github.com/29583855/dukto-next/actions/runs/41977378181)已全部success：Mac ARM64、Intel、Ubuntu各18CTest和27/27协议；Windows18CTest和29/29协议。完整附件/步骤日志位于`github-evidence-r38-items-full-terminal/receipt.json`；两Mac逐项查询截图已查看。旧1bc运行中的Windows超时失败仍保留，不回写成功。
- [x] 本轮修复已上传为`fa6d96ba725670f51ceb3e938078af5c815b392d`；80份生产输入、共162份应用/测试输入与精确提交树逐字节相同。两种Mac架构实际C++14 GUI/CLI已再次编译成功，当前编译附件已归档并核对CPU、源码SHA、执行位和摘要；其独立运行依赖资格仍另验。
- [x] Windows当前r18独立ZIP SHA `76328048c393ea824d2939a83e4ec818ef553052c0e2c2777c9bb02d521b74a9`迁移到中文空格目录、仅系统PATH后通过：原生GUI/截图、独立CLI实际库来源、16通道双向、4→8恢复、客户端分页、默认会话、混合排队、自动重试、最终确认丢失及fail/恢复。193份包内应用源码与fa6d96b精确树相同；364部署依赖字节来自24个已验签包，53许可文件对应。仍为开发预览，干净系统及完整第三方对应源码/独立重建等未完成。
- [x] 新glibc已链接CLI另复制到独立诊断目录，固定SHA `9e9d49bcb2e540848dfb60e6ac07f6a49192d3669f5bac9dd2b755664c3b5962`：16次4/16通道即时冲突全部正确、R6已缓冲/非法文本/两类5秒停滞共4项通过；复制前核对原CLI，诊断前后SHA相同。完整GUI/CTest构建仍继续，不能将这一并行诊断当作整套Linux资格。
- [ ] 新修复的[完整原生CI41980707523](https://github.com/29583855/dukto-next/actions/runs/41980707523)和[双Mac部署41980793643](https://github.com/29583855/dukto-next/actions/runs/41980793643)继续观察同次运行；旧冻结musl3978、新glibc33671和长测保留。新Mac独立包、当前Linux完整资格及原glibc90秒恢复瓶颈尚须实际终态。完整交付仍为false。


v0.38 当前Mac独立包交付（2026-11-05）：

- [x] 固定fa6d96b的[双架构原生部署41980793643](https://github.com/29583855/dukto-next/actions/runs/41980793643)已整体success，包含新逐项查询及网络期限/加入确认修复；两份GitHub原始ZIP和内部tar持久保存于`dist/macos-preview-20261105-r38-timeout-attach`。每份归档SHA、Mach-O架构、执行位、链接、应用对应源码与精确提交树已逐层核验，迁移、原生Cocoa/实际加载库、16双向和4→8八组恢复均通过，两张截图已查看。
- [x] 当前Mac GUI/独立CLI的下载、SHA和用法已更新至`docs/macOS独立预览包.md`。旧1bc包保留，当前包以本轮BUILD-RECEIPT为准。Windows r18也保留于独立目录，不用新文件冒充历史缺失摘要。
- [ ] 新完整原生CI41980707523仍按其实际终态验收；Mac包为adhoc开发预览，Developer ID/公证、独立干净Mac、完整主窗口/原生选择器与正式发布继续未完成。冻结Linux资格/长测和完整主计划继续，不把双Mac交付当作整个项目完成。


## v0.39 逐项接收失败原因与原生资格终态（2026-11-05）

- [x] 固定fa6d96b的[完整CI41980707523](https://github.com/29583855/dukto-next/actions/runs/41980707523)已四runner全部success：Mac Intel、Apple Silicon、Ubuntu各18CTest及29/29协议；Windows18CTest及31/31协议。全部附件和步骤日志已归档于`github-evidence-r39-timeout-attach-full-terminal/receipt.json`，双Mac逐项页截图已查看。其双Mac独立部署运行41980793643此前也已完成；两者均按fa6d96b记录，不混同本轮新源码。
- [x] 接收器增加有界逐项失败旁表：准备/打开恢复/写入校验/提交阶段的本地4/5/6原因绑定冻结清单，跨重启保留。完成行与原错误resolved在同一事务；旧日志仅由执行者验证绑定后迁移，查询只读。网络、取消和批次授权不随意分摊给文件；磁盘满等导致原因无法记录时继续返回原错误，缺少原因不能推断没有失败。见[0012契约](decisions/0012-逐项接收失败证据.md)。
- [x] GUI分页真实按钮显示中文具体原因；普通CLI与JSONL保留同一证据。可选`task-item-failures-v1`字段保持原v1处置枚举，固定r18旧CLI与新客户端/服务器四种方向组合实际查询通过。旧服务缺少原因时不制造远端证据；本机下载按实际接收日志查询。
- [x] 最终Windows UCRT/MSVC各18/18 CTest及8/8协议专项通过，二进制全组前后SHA一致，见`item-failures-r39-final-*-summary.json`。专项覆盖双向1/4/16共12次冲突、跨窗口16复制+1失败+1未执行的3组批次、204项三页、原目标保护、重启查询、旧日志只读、篡改清单/枚举/字符串/小数/超32位整数拒绝，以及确认丢失/自动重试/4→8八组恢复等原有检查。两个最终GUI原因截图已保存并核对。最初GUI追加断言误按QObject拥有树查委托，失败日志保留；改按实际childItems视觉树验证后通过。
- [x] 当前160份维护文件审计0标记，C++14、格式检查通过；保留既有UTF-8/BOM/CRLF。零标记不等于功能或正式交付完成。
- [ ] 本轮新源码上传后继续Mac双架构/Ubuntu/Windows完整CI及独立包。现有可下载Mac双包和Windows r18仍为fa6d96b，尚不含本轮逐项失败原因，不以旧包冒充新版本。当前glibc的r38完整资格33671与旧musl长测4687继续原运行，不改输入、期限或门槛。
- [ ] 旧固定1bc2774的musl资格3978已完整结束并归档：18/18 CTest、12组中8通过4失败（parallel-failure误报网络、session-expiry原90秒恢复超时、transfer-retry总期限、conflict-recovery未到注入检查点）。二进制前后摘要一致；不得用本轮Windows或先前Mac成功回写旧Linux失败。当前源码的musl仍需独立复验。
- [ ] 两项旧冻结Windows24小时长测已失败终止：摘要轮数148/136，累计44751.063/41082.906秒时测试shared目录缺失；保留原报告`frozen-long-tests-r39-terminal.json`，原因归属尚未证明，不将这两次算作应用崩溃或24小时通过。后续需持久隔离测试根及当前源码重新资格，原运行不重启。
- [ ] skip/overwrite、统一逐项处置/汇总/最终确认、全局预算/安全GC、证书生命周期、原版F01–F23与主窗口/原生选择器、物理LAN/3×3/当前24小时、完整盘满/干净系统、签名公证和第三方完整对应源码/独立重建等继续按主计划执行。deliveryComplete=false。


v0.39 编译与Windows部署补记（2026-11-05）：

- [x] 逐项失败证据已上传为`3b8bf4ac9459ec2a9caa3b74d9a63baf8c0e9ee7`；80份生产输入、共163份应用/测试/脚本输入与精确Git树相同，见`source-linkage-r39.json`。新Intel/Apple Silicon C++14 GUI/CLI均已原生编译成功，两个编译附件的原始SHA、Mach-O架构、执行位及提交身份已归档于`github-evidence-r39-items-compiled/receipt.json`。
- [x] 当前Windows r19实际ZIP SHA `f04057d0e9f3d2cec9fa86e83af37993ab777484790c6ec07d7ea100a1a28a12`已迁移到中文空格目录并仅用系统PATH通过独立GUI/CLI、真实库来源、16通道双向、4→8恢复、客户端分页、默认会话、混合排队、自动重试、确认丢失及fail/恢复。新增逐项原因专项另在迁移的实际包中完成12次冲突、3组跨窗口批次、重启及损坏/旧日志边界。原生截图已查看；195份包内应用输入与3b8bf4a精确树相同，24受信包的364依赖文件及53许可核对通过。仍为开发预览，完整第三方对应源码/独立重建、干净系统和正式发布尚待验。
- [ ] [新完整CI41986605449](https://github.com/29583855/dukto-next/actions/runs/41986605449)和[双Mac部署41986673599](https://github.com/29583855/dukto-next/actions/runs/41986673599)继续同次运行；两种Mac编译成功不等于整套回归及独立包通过。Mac当前已完整下载核验的双包仍为fa6d96b。
- [ ] 当前源码的197文件快照SHA `c0480ec764288756e6207b2961b5e528b6cd014c790797f828aa318d4f9b0a0f`已在独立`/home/dukto/item-failures-r39`启动musl构建和资格40851。原glibc33671及旧musl长测4687保持原输入，不覆盖旧失败，不放宽5秒/90秒等期限；总交付仍未完成。


v0.39 双Mac独立包交付补记（2026-11-05）：

- [x] [41986673599](https://github.com/29583855/dukto-next/actions/runs/41986673599)双架构完整打包运行success，源码3b8bf4a。已实际下载并逐层核验两份tar、源码SHA、执行位、Mach-O、71框架链接、原生依赖、adhoc签名和两包各195份应用输入；中文空格目录/仅系统PATH的Cocoa GUI、独立CLI及16通道双向/4→8八组恢复通过。两张原生截图已查看。回执`github-evidence-r39-item-failures/receipt.json`与dist/BUILD-RECEIPT均保存。
- [x] 新包持久存放在`dist/macos-preview-20261105-r39-item-failures/`。ARM64 tar SHA `41b3eb0a89ea192656cc27a00ebb3c97143a0ed6e2cbcc22ae05670bb73ea8be`；Intel tar SHA `e9e5478827d8bdc01d33228b8070c6de4fb0b1591041a9c6face03a0bfd758ba`。公开下载入口已更新到macOS独立预览包说明，旧fa6d96b双包保留。
- [ ] 同源码的[完整原生CI41986605449](https://github.com/29583855/dukto-next/actions/runs/41986605449)继续原运行，Apple Silicon的Core and GUI controller tests步骤已经失败，具体测试日志须等该job终态后归档定位；不能以编译、Windows或独立包迁移成功覆盖该失败。没有取消/重启其他专项。当前正式发布与总计划交付均未完成，Developer ID/公证、干净Mac以及其他计划项仍待验。


## v0.40 发现原门槛与原生回归（2026-11-05）

- [x] 原3b8bf4a完整CI41986605449终态已归档：Intel、Ubuntu各18/18 CTest及30/30协议，Windows18/18及32/32协议通过；ARM17/18 CTest与30/30协议通过，唯一失败是原5000次真实UDP连锁测试超出10秒，QtTest报告约需11.85秒。服务器GUI通过，双Mac逐项原因截图已实际查看。全量回执`github-evidence-r40-native-full-terminal/receipt.json`保留该失败，不以独立包通过覆盖它。
- [x] 新源码7590363缓存每次公告的本机身份，收包/回复不再反复同步查询系统主机名；启动、改名、显式及60秒周期公告刷新，原R6格式和64包/5ms处理片保持。原core_tests.cpp的SHA保持`1b825e24642a8e24dff158b75ce7c99f68b7a6bdbe1c26ce86e4d0b786c1da4b`，5000包/10秒门槛不变。边界见决策0013。
- [x] Windows UCRT/MSVC完整C++14 GUI/CLI编译，两套各19/19 CTest通过（118.77/124.32秒），真实旧协议与CLI回归通过；全组前后CLI摘要相同。新增身份刷新测试首轮误计真实设备导致失败，原源码副本/两套失败报告保留；修正为只核对测试身份后完整复验通过。`discovery-r40-final-*-summary.json`、逐项日志和截图已归档；源码扫描162维护文件、0标记，C++14/格式通过。
- [x] 当前80生产输入和165应用/验证输入已与7590363逐字节关联。UCRT CLI SHA `15a8fd5c6515092b70107dba708ed53fb2c144f8c7873a670cfc5683ba205539`，MSVC SHA `ad6bd1d01547962dc5c5def6dfa807b4b6819d6731bda2f6d06db6fc07efd2a6`。旧Windows r19和双Mac r39包仍明确是3b8bf4a，不冒充包含本次缓存改动。
- [ ] 新源码完整四平台CI、双Mac原门槛对照诊断和双Mac独立包继续；单独微基准仅定位查询成本，不能替代原门槛或物理局域网提速。核心日志改为在后续协议前立即归档，不跳过失败或后续独立测试。尚未宣称ARM失败已修复。
- [x] fa6对应glibc原冻结资格33671已终态exit1归档：18/18 CTest（543.64秒），10协议9过1失败；session-expiry在原90秒恢复期限确认142606336/268435475字节、复用8388608字节后超时。前后CLI SHA同为`9e9d49bcb2e540848dfb60e6ac07f6a49192d3669f5bac9dd2b755664c3b5962`。原失败保留于`linux-glibc-timeout-attach-r38`，不放宽门槛。
- [x] 后续独立Linux会话诊断仍用同一fa6二进制与原20秒/512KiB/s/90秒门槛，保留91次有界/proc观察及原始报告。环境确认为单vCPU、QEMU TCG；诊断仍超时，采样可能影响耗时，尚不能凭此定位某一函数或宣称应用崩溃。`linux-glibc-session-diagnostic-r40/results/sampling.json`中原二进制/脚本前后SHA一致。当前3b8的musl40851和旧musl4687长测继续原运行，均不改动。
- [ ] skip/overwrite、完整处置汇总与最终确认、R6完整基线、预算/GC、证书生命周期、当前版本24小时、物理LAN/3×3、干净系统与正式签名发布等总计划项仍未完成。


## v0.41 有界发现重查与实际包（2026-11-05）

- [x] 1842009已上传公开仓库。设备发现每个实际收包片最多再排一次非阻塞重查；空片不续排，原64包/5ms预算和5000包/10秒门槛保持。新增真实收包后空闲检查，禁止无包时无限零定时器轮询。Windows UCRT/MSVC各19/19 CTest、真实旧协议及CLI回归通过，前后CLI摘要一致；162维护文件0标记、C++14/格式通过，80生产及165应用/验证输入与Git树一致。
- [x] 当前UCRT CLI SHA `5a717e560a67b5018b9d80c9cd34e1bb017523f599abfbd8753aad1450013a8c`；MSVC SHA `b8db0e047b168878a5bee36b6e7eb63b60995162cdd4aa16d1311f6b939eddd3`。完整日志见discovery-r41-*-summary.json。双Mac独立原门槛对照诊断[41993873462](https://github.com/29583855/dukto-next/actions/runs/41993873462)已success，原源码与旧失败继续保留，完整原生CI[41993762798](https://github.com/29583855/dukto-next/actions/runs/41993762798)和新包[41993878362](https://github.com/29583855/dukto-next/actions/runs/41993878362)仍在途，不据独立诊断断言偶发超时已根治。
- [x] 7590363双Mac独立包[41991697198](https://github.com/29583855/dukto-next/actions/runs/41991697198)已整体success，已下载到dist/macos-preview-20261105-r40-signature-cache；逐层核对摘要、199应用输入、框架链接/Mach-O、adhoc签名和依赖，中文空格/仅系统PATH迁移与双向16通道、4→8八组恢复通过。ARM tar SHA `fd11153b8d8d797fb5624dbcb23906c9a68480bd6c5dd500488216b44c9242d7`，Intel SHA `fb7b75e3648a3a6401a8b2097a488ee35775372df85b61400bddf2315997247b`。两张截图已查看；ARM截图临时接收端口占用，GUI仅证明渲染/依赖加载，不把本行当作R6 GUI监听资格。
- [x] Windows r20 ZIP已生成、实际迁移并查看截图，199应用输入与文档提交bed94bf逐字节匹配，生产代码为7590363；24受信依赖包的364文件/53许可再次核对。ZIP SHA `54934373992c49fa774d9fb706759108924a6ad1bc9625ac1b9b82b3f6e908e7`，位于dist/windows-preview-20261105-r20。该包与上述Mac包不含1842009重查，不冒充当前构建；第三方完整对应源码/重建和干净系统仍待验。
- [x] 新Windows长测使用1842009的独立冻结CLI、已验证依赖、原测试源码及原资源门槛，持久测试根位于C:/Users/qqw/DuktoNextArtifacts/dukto-01a1a510/stability-r41-r2。首个预检因复制CLI后未显式提供冻结SQLite插件目录而失败，原失败及doctor对照保留在windows-stability-r41；显式QT_PLUGIN_PATH仅修正隔离运行环境。新目录20轮16通道双向/SHA/幂等和暖机后资源门槛全部通过，测试源与二进制不改，windows-stability-r41-r2/precheck.json与terminal回执保存。
- [ ] 同一冻结输入24小时稳定性83949已启动，当前运行中；不能把20轮预检当作24小时通过。旧Windows两次Temp缺失失败及旧musl4687不改、不重启；当前3b8的musl40851继续，已出现transfer-retry/session-expiry/transfer-faults失败，具体终态原报告待归档，不以其他平台成功覆盖。
- [ ] 7590363完整CI41991583917的Intel原UDP门槛再次失败（QtTest约需12.3秒），早期核心附件已归档。其余专项继续原运行。主机名查询微基准成本不能解释该超时，缓存不作为根因修复证据；旧失败、基线与新重查实际结果分别保存于决策0013和验证目录。
- [ ] 原版完整基线/主窗口和原生选择器、skip/overwrite与最终处置确认、全局预算/GC、证书生命周期、当前版本全平台24h、物理LAN/3×3、完整第三方对应源码/独立重建、干净系统及正式签名/发布仍未完成。


## v0.42 当前双 Mac 包与原生 musl 复验（2026-11-05）

- [x] 1842009双Mac独立包[41993878362](https://github.com/29583855/dukto-next/actions/runs/41993878362)整体success，已下载到dist/macos-preview-20261105-r41-bounded-recheck。ARM tar SHA `8d34381a18be8cc348f4903035142df113b14e445e61ba074c3b02dac1f48637`，Intel SHA `faf374ce5f966dd57ef6d90a5ccf5d483243b2bd355e15ee9f694b1b1163383b`；两包各199应用输入/精确Git树、71框架链接、Mach-O/执行位、签名和运行依赖核对。中文空格路径/仅系统PATH迁移、独立CLI、16通道双向、4→8八组恢复与SHA通过。两截图已查看，本轮均显示接收就绪；旧ARM端口占用的截图及其局限保留。
- [x] 3b8bf4a的冻结musl197原资格40851已exit1并完整归档：18/18 CTest（320.67秒），11协议7过4失败。task-items的204项原90秒仅完成16文件；16通道上传自动重试达到原总期限；session-expiry原90秒恢复超时（确认142606336、复用8388608）；源同尺寸/mtime变化上传故障31.062秒超过原30秒。CLI/GUI前后SHA相同，结果tar SHA `f72525be4bcbcde351c90933075066a2b197cbcb576def678b44e20127f4f0f2`。原失败不改、不放宽门槛、不用其他平台结果覆盖，详见musl-r39-terminal-r42.json。
- [x] 原生CPU Alpine工作流、普通用户Docker环境及只读源码/结束摘要核对已上传；保留3.24.1实际镜像digest、apk版本、CPU和工具链。bash语法及YAML解析通过。首次派发因job env错误引用runner.temp被GitHub422拒绝，记录保留；已改用RUNNER_TEMP/GITHUB_ENV后派发。生产代码仍逐字节等价1842009，不修改任何旧长测输入；边界见决策0014。
- [ ] 原生Alpine的C++14 GUI/CLI、19CTest/TLS/30原协议实际结果待验；offscreen不当作桌面或干净系统验收。完整四平台CI41993762798的四组19/19核心已通过，协议仍在原运行；旧759完整CI的Intel原UDP门槛失败和后续专项分别归档。
- [ ] 83949当前Windows冻结20轮预检后24h继续运行；旧musl4687继续，不改二进制、数据、脚本或原门槛。长测及全平台正式交付不因子项通过标记完成。
- [ ] skip/overwrite与处置汇总/最终确认绑定、R6主窗口完整交互、全局预算/GC、证书生命周期、物理LAN/3×3、当前全平台24h、第三方完整对应源码/重建、干净系统、正式签名/公证与发布继续未完成。


## v0.43 当前完整四平台矩阵终态（2026-11-05）

- [x] 当前1842009完整CI[41993762798](https://github.com/29583855/dukto-next/actions/runs/41993762798)四job全部success，完整日志、原始附件及SHA已下载归档：macOS arm64、macOS x86_64、Ubuntu各19/19 CTest与30/30协议；Windows19/19 CTest与32/32协议。双Mac实际Cocoa渲染、面板进程恢复和独立TLS证书/协议边界均通过，逐项失败页面两张截图已查看。回执github-evidence-r42-bounded-recheck-full-terminal/receipt.json，汇总native-full-r43-summary.json。
- [x] 旧7590363完整CI41991583917已终态failure并完整归档。Intel核心唯一失败是原5000包10秒UDP门槛；Windows核心19项通过、协议31/32，唯一失败parallel-failure的16通道目录冲突用例客户端退出3/protocol而非原要求4/conflict，原文件保留，服务端最近事件仍报告conflict。其余三平台各30协议通过。不能因当前同测试通过就宣布这种偶发现象根治；错误应答/关闭时序需继续独立诊断，原脚本和门槛保持。
- [x] 当前1842009双Mac独立预览包已实际下载/校验并更新入口，GUI/独立CLI迁移、16通道双向与4→8八组恢复通过；保持adhoc开发预览及未公证标识。源码扫描162维护文件0遗留标记，C++14及C++格式检查通过；零标记不代替尚未实现的skip/overwrite等需求。
- [ ] 原生CPU Alpine第二轮[41997754440](https://github.com/29583855/dukto-next/actions/runs/41997754440)已完成编译和核心步骤，继续原30协议；首轮环境变量未export失败完整保留。当前生产代码的原生Ubuntu24.04包[41998140793](https://github.com/29583855/dukto-next/actions/runs/41998140793)已通过编译与核心步骤，实际X11/Wayland迁移继续。两项终态结束前不标记完整通过。
- [ ] Windows83949的当前冻结24h及旧musl4687继续，不动原输入；原VM四组协议失败继续开放。完整R6/原生选择器、skip/overwrite与汇总/最终确认、全局预算/GC、证书生命周期、物理LAN/3×3、当前全平台长测、第三方对应源码/重建、干净系统、正式签名和发布均仍待完成。


v0.47：d4626d0最新双Mac GUI/独立CLI已原生编译，双Mac各19核心通过；42007080163双架构实际独立包已success、下载校验和迁移通过，当前入口见[macOS独立预览包](macOS独立预览包.md)。完整协议42006921571仍在运行，不以编译或迁移代替整套回归/正式发布。


v0.48：d4626d0完整CI已终态，ARM31/31协议通过、Intel30/31（queue-deadline缺少queued事件），总体failure。最新本地QML修复真实首页入口和紧凑首次说明，新增Cocoa/高DPI回归及打包前门槛；尚待新提交的原生结果，旧双Mac包含入口缺陷。


v0.48终态：f230f3d双Mac独立包42013431292已success并实际下载/校验/迁移，两架构GUI/CLI、打包前Cocoa真实主窗口三场景/两尺寸通过，原生服务器/实际包截图已查看。当前下载和SHA见macOS独立预览包。源码相同的验证补充732b58d增加真实中文字形门槛，其完整CI和f230f3d完整协议继续独立运行，不以双包通过覆盖原失败或正式发布缺项。


v0.48字形终态补记：732b58d四runner各19核心通过；双Mac Cocoa/150%/200%均28个标签字形/0缺字，两尺寸导航通过，原始附件和Mac高DPI截图已核对。仅该字形/核心子项通过，42014821263完整协议仍运行。


### v0.60 双架构Mac交付与完整原生终态（2026-11-06）

- [x] 用户授权的公开仓库[29583855/dukto-next](https://github.com/29583855/dukto-next)已上传共用C++14/Qt5源码。精确74dd5ce的[双Mac部署工作流](https://github.com/29583855/dukto-next/actions/runs/42066089117)整体success；Intel与Apple Silicon自动安装Qt5/OpenSSL，完成GUI与独立CLI原生编译、部署和实际迁移，当前[下载与SHA](macOS独立预览包.md)已切换到该提交。
- [x] 两架构各229份内附应用源码与精确Git树全集逐字节匹配；arm64的1547份载荷、Intel的1705份载荷及各71框架链接核验，Mach-O架构、执行位、依赖来源和adhoc签名通过。各五份原业务报告SHA核验：独立CLI、16通道双向、1/4/16覆盖、覆盖恢复及4→8默认恢复；两张Cocoa服务器页截图已查看。主窗口导航夹具的Cocoa与150%/200%独立offscreen通过，不能扩大为所有原生选择器验收。
- [x] 同源码[四runner完整CI](https://github.com/29583855/dukto-next/actions/runs/42065923177)全部success：Windows、Ubuntu glibc、macOS arm64/x86_64各21核心/GUI，合计150项协议子报告全部读取并核验原SHA（Windows39，其余各37）。[Alpine musl](https://github.com/29583855/dukto-next/actions/runs/42066082958)另21核心/37协议通过，五种原生环境的QtTest原报告均核对。
- [x] d2a5359的四runner最终原报告补齐，按旧提交Windows38/POSIX36合计146项核验，不能误用新增专项后的150项门槛。历史失败、原日志、Qt头像既有警告及首轮尚未证实根因的两项观察保留。
- [x] 新包和GitHub原ZIP持久归档于dist/macos-preview-20261106-r59-dispositions；[公开核验回执](ci-verification-20261106-r60.json)、验证索引、README和Mac说明已同步更新。文档保持原UTF-8/BOM/换行，本轮未修改生产代码；r59的176文件无TODO/占位标记结论仍仅限原审计范围。
- [ ] Mac仍为adhoc开发预览；Developer ID签名/公证、干净系统、完整对应依赖源码及独立重建继续。公开skip、客户机上传发送处置、对等摘要、R6完整策略、预算/GC、原版全交互/原生选择器、物理LAN提速/3×3及当前全平台24h仍未全部完成。冻结旧长测输入保持不变，deliveryComplete=false。


### v0.63 精确3fbec42双Mac包交付（2026-11-06）

- [x] 授权公开仓库29583855/dukto-next已上传共用C++14/Qt5源码；[双架构打包42083741936](https://github.com/29583855/dukto-next/actions/runs/42083741936)整体与两job均success。CI自行安装Qt5/OpenSSL，Intel与Apple Silicon实际编译GUI/独立CLI、部署依赖并迁移运行。[下载与SHA](macOS独立预览包.md)现指向精确3fbec42。
- [x] 每包234份应用源码与精确Git树全集逐字节一致；arm64的1547份、Intel的1705份载荷和各71框架链接、Mach-O架构、执行位及adhoc签名核验。各五份业务原报告按父SHA逐份核验：独立CLI、16通道双向、1/4/16覆盖、覆盖恢复及4→8恢复。两种架构的真实首次说明主窗口与Cocoa服务器页共四张截图已查看，中文和控件可见。
- [x] 原ZIP、tar.gz及BUILD-RECEIPT已保存在dist/macos-preview-20261106-r62-overwrite；[公开回执](ci-verification-20261106-r63.json)、当前索引和下载文档同步。旧包、历史失败及原文件编码/BOM/换行保留。
- [ ] 同源码四runner42083656124和Alpine42083735291的终态及全部协议原报告继续核验；门槛为各21核心、Windows41/POSIX38、四runner155和Alpine38。独立包通过不代替完整矩阵通过。
- [ ] adhoc开发预览不代表正式发布；完整部署GUI/原生选择器、公开skip/对等摘要、服务器历史文件重验、R6完整策略、预算/GC、物理LAN提速/3×3、当前全平台24h、依赖源码重建、干净系统和签名/公证按主计划继续，deliveryComplete=false、releaseQualified=false。


### v0.64 私有状态原子替换竞争修复与原矩阵终态（2026-11-06）

- [x] 精确3fbec42的四runner42083656124终态failure：Windows、Ubuntu及双Mac各21核心通过；Ubuntu/双Mac各38协议、Windows40/41，合计154/155。唯一失败为活动传输时serve share add改共享根，返回5/identity“私有状态原子替换失败”。Alpine42083735291另21核心/38协议通过；全部实际存在的通过子报告均读取并核对SHA，缺失失败子报告和原job日志保留。[原终态汇总](validation/2026-11-06/overwrite-r62-native-terminal-summary.json)。
- [x] 新源码[7772151](https://github.com/29583855/dukto-next/commit/7772151314c5c6f9414a2d6d64c5aa81d1382b97)已非强制上传：PrivateStore保留同目录原子替换，仅对Windows5/32/33进行500ms/最多21次有界等待；每次重验私有根ACL和目标安全类型，持续占用返回5/identity-busy，保留旧配置并清理临时文件。[设计0024](decisions/0024-私有状态原子替换与读者竞争.md)。
- [x] 真实原生读句柄三行回归在修复前全部失败，修复后UCRT/MSVC实际C++14 GUI/CLI编译、各21项完整CTest（125.015/126.047秒）及各五份真实协议报告通过。短暂/持续/连续16次读者验证旧内容、显式重执行、临时清理和句柄无累积；源变化30秒、撤权/根改配15秒原门槛不变。[原报告与源码/二进制关联](validation/2026-11-06/private-r64-windows/summary.json)。
- [x] 178份维护源码无TODO/占位，clang-format、C++14和修改文件原编码/BOM/换行通过；Win32探针确认读者竞争机制，但没有识别原CI具体占用句柄。补收b9d9b78原失败：四平台transfer均有临时库glob误判；另Windows并发隔离最终空闲线程5/基线3，根因未确认，不能全部归因glob。
- [ ] 新提交[四runner42095096486](https://github.com/29583855/dukto-next/actions/runs/42095096486)、[Alpine42096266855](https://github.com/29583855/dukto-next/actions/runs/42096266855)和[双Mac包42096271845](https://github.com/29583855/dukto-next/actions/runs/42096271845)已启动，终态和原附件待核验；不继承3fbec42资格。当前Mac下载仍保持已核验的精确3fbec42，各234份应用源码、各五业务原报告和四张截图，见[下载与SHA](macOS独立预览包.md)。
- [ ] 公开skip、对等处置摘要/显式正文裁决、任务/GUI/CLI跳过结果、服务器历史completed当前文件重验、R6完整策略、全局预算/安全GC、完整原版交互/原生选择器、物理LAN提速/3×3、当前全平台24h、第三方对应源码/独立重建、干净系统与正式签名/公证继续。旧冻结长测保持原输入，本轮不推断其运行状态；deliveryComplete=false、releaseQualified=false。
