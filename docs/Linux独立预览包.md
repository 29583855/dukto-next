# Linux 独立预览包

2026-11-05 v0.48：下述d4626d0旧包的首页“服务器”入口存在QML作用域错误。本地源码已修复并通过双Windows原生/高DPI专项，新包尚待编译与验证；旧包原迁移和CLI结果保留，不能当作入口通过。

更新日期：2026-11-05。当前目标为 Ubuntu 24.04 或更新版本的 x86_64 glibc 环境，要求 glibc 2.39 或更新版本。此包不覆盖 Alpine musl、其他架构或 macOS；正式发布资格仍为 false。


## 当前可下载包（2026-11-05）

[下载x86_64 glibc证书版独立预览包](https://github.com/29583855/dukto-next/actions/runs/42007092492/artifacts/13405122545)（GitHub Actions附件下载可能需要登录）。附件ZIP内含tar、SHA清单及迁移证据。tar SHA-256：

```text
45289312b01d4534e5bfebdc302239828bfe3f91ee80532237f2739a0019f729
```

源码提交d4626d0，Ubuntu24.04/glibc2.39起，x86_64，GUI与独立CLI；包含证书续期、资料查询和显式指纹迁移。19/19核心与实际Xvfb/Weston两种迁移、包内依赖、16通道双向、完整性及幂等断言均通过，两截图已查看。708文件、2链接、132 ELF和207应用输入与精确Git树匹配。[完整回执](validation/2026-11-05/github-evidence-r47-certificate-linux-terminal/receipt.json)。完整协议回归仍在同次运行；干净系统、物理桌面、完整第三方对应源码/重建和正式发布尚未验收。旧44892f0包保持原目录和摘要。

## 构建依赖

开发助手负责安装和记录 Qt5 工具链。已准备的 Ubuntu 环境使用 Qt 5.15.13、GCC 13.3、CMake/Ninja、OpenSSL 3.0.13 及发行版安全补丁，并安装 SQLite、Qt Quick Controls 2、Qt QML/Models/WorkerScript、Qt Graphical Effects 和 Qt Wayland 模块。

QML 模块属于运行依赖。`qmlimportscanner` 若报告缺失模块，打包立即失败；不得忽略该项。前一轮实际因缺少 `qml-module-qtgraphicaleffects` 而失败，现已从 Ubuntu 官方签名仓库安装，并补入 Linux CI 依赖列表。安装记录与后续包测试分别保存。

## 生成

必须在固定源码快照安装成功、Qt5 GUI/CLI 编译和对应测试结束后打包。首次快照安装刷新所有输入文件时间，不能用保留旧 mtime 的 tar 覆盖来证明增量构建正确。

```sh
cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel 2
ctest --test-dir build --output-on-failure
python3 scripts/package_linux.py --output dist/linux-preview-<唯一名称>
```

输出目录必须不存在。脚本部署 GUI、独立 CLI、实际 QML 导入、Qt 平台/SQLite 插件以及递归 ELF 依赖，并逐文件记录 SHA-256、来源和发行版包版本。系统 glibc 及列明的基础系统库由目标系统提供，不将宿主动态加载器混入包中。

产物包括 `DuktoNext-linux-glibc-x64-preview.tar.gz`、摘要清单及展开目录。`package-manifest.json` 和 `dependency-packages.json` 记录实际内容；许可和本工程对应源码随包保存。第三方准确对应源码、补丁及构建配方的完整分发仍在实施。

## 运行

解压到用户可访问的目录后，使用顶层启动器：

```sh
./dukto-gui
./dukto-cli --help
./dukto-cli doctor --json
```

启动器配置包内依赖搜索路径。GUI 需要 X11 或 Wayland 会话及适合显示中文的系统字体；CLI 可以在 SSH 和无桌面服务器独立运行。服务器初始化、共享、配对、上传、下载和恢复命令见项目 README。

## 迁移验证与当前状态

测试须解压实际 tar 包到包含中文和空格的新目录，在移除开发环境路径后执行：

```sh
python3 tests/linux_package_integration.py <tar包> --platform xcb --report <X11结果.json>
python3 tests/linux_package_integration.py <tar包> --platform wayland --report <Wayland结果.json>
```

调用方分别提供真实 X11/Wayland 会话。测试核对依赖实际从迁移目录加载、CLI 不加载图形模块、GUI 原生平台插件与渲染、SQLite/TLS、16 通道双向及幂等重试。Xvfb/Weston 的结果属于虚拟显示环境，不替代物理桌面、物理局域网或干净系统验收。

当前最新固定源码正在 Ubuntu 重建，完成后顺序执行大于虚拟机内存的文件专项、打包及两种显示会话迁移验证；结果结束前不标记打包通过。较早源码的 X11/Wayland 面板验证与最新包验收分别记录在主计划。


2026-11-05 会话/公平排队 160 文件固定快照已完成构建及 17/17 CTest，完整业务驱动已结束归档，但会话/隔离/256 MiB 恢复失败仍开放。r5 包生成成功后，X11/Wayland 迁移都捕获 OpenSSL 实际来自系统路径，因此尚不能作为通过的独立包。

[动态加载器记录](validation/2026-11-05/linux-glibc-package-loader-r1.log)显示 Qt 首先请求 libcrypto.so/libssl.so，而原包只有 libcrypto.so.3/libssl.so.3。打包器补同目录相对别名，避免单独复制两份 ELF；包测试只允许这两个准确的相对链接，继续拒绝其他符号/硬链接，并要求仅有包内一份 crypto/ssl 映射。修复的实际 X11/Wayland 验证按独立隔离快照继续，不将脚本修改本身标为包验收通过。

2026-11-05 当前部署增量：r6 OpenSSL 别名包 X11 实际迁移通过；Wayland 的 EGL/装饰错误保留。临时副本补 wayland-decoration-client 插件并默认软件 EGL 的探针已通过，截图已核对；正式脚本已纳入这两项，r7 实际归档包验证仍运行。GUI 启动器默认 LIBGL_ALWAYS_SOFTWARE=1，可由用户显式设为 0；CLI 不设置该图形选项。Wayland 需要目标系统兼容的 Mesa/EGL 及驱动依赖，不能把宿主图形驱动宣称为包内依赖。最新 166 源码两 Linux 的构建/专项驱动独立进行，不把旧二进制包作为最新重试版。

r7归档已生成，SHA c4212ec28875737815d64c2b0ed0ac20ebf7ed37eca500dd7b5d7284a11e6ab3。实际X11/Wayland界面/装饰/依赖断言及截图通过后，双会话后续16通道上传均在原90秒超时，整包仍失败，见[完整终态](validation/2026-11-05/linux-glibc-package-wayland-runtime-r3/driver-result.json)。截图已核对。原包只含160生产源码；同包在前置负载退出归档后再独立复验，不能用较长诊断替代默认门槛。新测试在业务失败时写入passed=false的部分报告，保留实际运行模块而不伪装为完整包通过。

## v0.28 同包独立复验（2026-11-05）

同一 r7 tar（SHA c4212ec28875737815d64c2b0ed0ac20ebf7ed37eca500dd7b5d7284a11e6ab3）在前置驱动退出归档后[实际独立复验](validation/2026-11-05/linux-glibc-package-runtime-recheck-r4/driver-result.json)通过。[X11](validation/2026-11-05/linux-glibc-package-runtime-recheck-r4/results/x11.json)与 [Wayland](validation/2026-11-05/linux-glibc-package-runtime-recheck-r4/results/wayland.json)各核对 705 清单文件、真实 GUI/装饰/依赖来源/空标准错误和原 90 秒 16 通道业务，截图已检查，runtimeChecksPassed/transferChecksPassed/passed 均 true。原负载下超时保留，此结果不证明超时原因已修复。包仍含旧 160 生产二进制，早于新重试和 fail；干净系统/正式发布及最新源码包仍未验收。


v0.42当前1842009生产代码的独立原生CPU打包工作流linux-package.yml已接入，使用Ubuntu24.04/C++14/Qt5，先执行19项核心测试，再生成真实tar并分别在Xvfb和Weston会话迁移验证。包清单增加精确Git提交和原始GUI/CLI摘要；仅记录元数据，不改变应用代码。实际结果、摘要和下载地址待运行完成后填写。旧r7包及原失败不替换、不冒充新构建。


v0.43当前Linux包首轮终态：41998140793在Ubuntu24.04实际编译、19项核心和打包通过；tar SHA f3fd661d111dd7af1c21ee5b6d2533582fe5797e3e48a4fd311ea4ce0734376c。已实际下载，708清单文件、2同目录OpenSSL链接、132 ELF和204应用输入/精确0a38ceb树核对。Wayland完整迁移/双向16通道通过；X11在GUI映射采样得到空列表时失败，未完成整包资格，原始附件/日志/包保留于github-evidence-r43-linux-native-initial及dist/linux-preview-20261105-r43-linux-native-initial。

映射采样修正只处理可确认的退出竞争：遇到空映射最多等待100ms确认进程已经退出，才转为既有NoSuchProcess退出路径；活动进程空映射仍失败。GUI最终退出码、无标准错误、真实平台插件/依赖来源、截图和原90秒16通道断言均保留，未获得模块证据仍不能通过。新增实际活进程/已退出进程四边界自检，同时确认外部Qt和CLI图形模块仍拒绝；Windows本机自检及163文件0标记/C++14/格式通过。首次自检开发时的Windows模拟映射路径改为POSIX规范路径后通过，不涉及应用代码。独立新原生包复验继续；原VM、Mac和Windows冻结输入均不改。


2026-11-05 v0.46版本范围补记：上方已验收的实际包早于证书续期/指纹迁移功能，不含serve renew、profile-info及trust；新源码和新包的资格分别记录，新包实际下载校验结束后再更换入口。


v0.47：当前下载入口已更新为d4626d0证书版。此前v0.46范围补记指当时旧包，旧记录保留。
