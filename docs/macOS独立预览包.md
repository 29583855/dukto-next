# macOS独立开发预览包

R118精确e84f34f5dfec9c1edd465a443b37c3bc2696c633已公开，新增客户端/服务器状态占用查询；双Windows各28核心通过。双Mac C++14 GUI、独立CLI及含Qt5/OpenSSL预览、迁移运行和四截图已验。[ubuntu-22.04、macos-15、macos-15-intel、windows-2022各28核心已验](ci-verification-20261107-r118.json)；完整协议另按终态核验。

R117精确`a46454d0ece59d178f1763c56f60cc61298e3154`已公开，修复Windows提升进程创建SQLite热日志时的默认所有者误拒绝，保留私有ACL及普通文件严格规则。双Windows各27核心及GitHub Windows两轮专项各29条通过。Apple Silicon/Intel C++14 GUI、独立CLI及含Qt5/OpenSSL预览均已核验；迁移运行、各五项CLI/传输、Cocoa导航/高DPI和四张截图通过。[完整CI](https://github.com/29583855/dukto-next/actions/runs/42379391549)继续按终态收验，[打包](https://github.com/29583855/dukto-next/actions/runs/42379506896)双架构终态success。

R116精确`0a60da9120b6be49d1768fa500d042ff394ac9f7`已公开，增加上传扫描中断后的按请求清理及资源申请失败恢复。Apple Silicon/Intel C++14 GUI和独立CLI编译归档均已核验；[含依赖打包](https://github.com/29583855/dukto-next/actions/runs/42375918838)双架构终态success；[完整原生CI](https://github.com/29583855/dukto-next/actions/runs/42375666807)继续按终态原件收验，Windows热journal所有权诊断单独保留。下方R116含依赖双架构预览、迁移运行和四张截图已验，R114包保留为历史版本。

R114精确`d922dc4c793c77de0553ddf44c0fe1fa2d998c24`已上传，增加私有配置原子换代有界重读。Apple Silicon/Intel的C++14 GUI及独立CLI已编译并核验两份归档；原生核心已验3/4。含依赖双架构预览、迁移运行及四张截图已验，下方可下载R114包。[完整原生CI](https://github.com/29583855/dukto-next/actions/runs/42370990486)按实际附件另验。

R113精确`400e0621745dc250b3390ad01a5e9f47dfc924a4`已上传，修复跳过目录的接收/维护交错恢复。Apple Silicon/Intel C++14 GUI及独立CLI均已编译并核验归档；四平台核心已验4/4。双架构包和截图均已验，完整协议与整体交付继续按实际原件验收。

R111精确`dfe245b502f586e7df7219e8fb0d5e4030a6b032`已在Apple Silicon和Intel原生环境以C++14/Qt5编译GUI及独立CLI；四平台各26个CTest和目录专项各49条已验，完整协议Ubuntu通过，Apple Silicon 46/47、overwrite-faults原失败保留，Intel 45/47（凭据轮换与会话恢复失败），Windows完整协议51/51且终态success。R111含Qt5/OpenSSL预览[构建42363743119](https://github.com/29583855/dukto-next/actions/runs/42363743119)双架构终态success，系统PATH迁移与包内运行报告已验。

R115仅修正面板测试的读取时序，产品应用输入与R114完全一致。双Mac各两轮完整面板专项已通过，四轮各7方法；原Intel失败日志继续保留。[专项回执](validation/2026-11-07/panel-timing-r115-macos/receipt.json)。

## R118含依赖开发预览

[逐层回执](validation/2026-11-07/state-storage-r118-macos-package/receipt.json)。这是adhoc开发预览，正式签名/公证、最低干净系统及完整项目仍待验。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42383349465/artifacts/13579125540) | c41d71edd0277e657115af54302b32df74b4f90f8f4aa19168266b4ca748eb79 | 9719c75d98bb4375ddab1b116152bb256f300f5a933dfb105a54befec0b0d164 |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42383349465/artifacts/13579126824) | 77bb214aefab90025242d6c9f85bdf5809d39363109a98a7d18934b1456e3fe9 | cdd2a682c0b114c1cd242af54a91e66ce44441dc6cb0100fed66e798903ad605 |

本机副本：dist/macos-preview-20261107-r118-state-storage/。解压与CLI用法见本文下方说明。

## R117含依赖开发预览（历史）

[逐层回执](validation/2026-11-07/sqlite-journal-r117-macos-package/receipt.json)。这是adhoc开发预览，正式签名/公证、最低干净系统及完整项目仍待验。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42379506896/artifacts/13577251125) | `90d7a515493282be236e89497d4f941a944c6c0746452a9e49b06ff4f9fb1313` | `1fda4f0a9a598fc2a1766e695875e95bfd139ebf3939267fac192f90b6f65948` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42379506896/artifacts/13577302509) | `d6321e29450f7798eb2300454bd937ff00a404c65ac8f1eb4e6927b9effba200` | `8583d6ab3a56cf5a2a3af0f3627663d49107d544d099d6fceec185dcff45afcf` |

本机副本：`dist/macos-preview-20261107-r117-upload-scan/`。解压与CLI用法见本文下方说明。

## R116含依赖开发预览（历史）

两架构Qt5/OpenSSL、GUI/独立CLI、对应应用源码、全部载荷与框架链接均逐件核验；各五项真实CLI/传输报告、系统PATH迁移、Cocoa导航/高DPI通过，四张截图已查看。[回执](validation/2026-11-07/upload-scan-r116-macos-package/receipt.json)。这是adhoc开发预览，正式签名/公证、干净系统与完整项目继续验收。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42375918838/artifacts/13575304889) | `ffc11de25341aba2b2baec03f0032c1f6089e36900cb8b374b0df0435064dbe4` | `f6d3db8dd983aa82b2d9130f342d7b0c727504ad5840437ee69516f4ca0bd9c8` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42375918838/artifacts/13576046892) | `711addb244c805b6d0354ce90a35709cab65454df9c78840f8148138cd1ec040` | `2cf2ace7aea638175db3f9f3611a74d6c42eaa8f67e3e5bb2c334c42322fd3df` |

本机副本：`dist/macos-preview-20261107-r116-upload-scan/`。解压与CLI用法见本文下方说明。

## R116原生编译归档

双架构原始ZIP/内部tar摘要、精确源码、LICENSE、Mach-O架构与执行权限已核验。这是编译产物，需要匹配的Qt5/OpenSSL依赖；含依赖预览另验。[回执](validation/2026-11-07/upload-scan-r116-macos-compiled/receipt.json)。

| 架构 | 下载 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42375666807/artifacts/13575144094) | `be1ffc1339542f9ea57ac62e7b9d6ce3f3551b2709c934680961756621a6099d` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42375666807/artifacts/13575058009) | `672bb0c885c76de396d96c8a66e720b7d7194505f7f040e2d2498ed6c8e2eabf` |

## R114含依赖预览（历史）

两架构包内Qt5/OpenSSL、全部载荷与框架链接、对应应用源码逐件核验。各五项真实CLI/传输报告、系统PATH迁移和Cocoa/高DPI通过，四张首页/服务器截图已查看。本机副本`dist/macos-preview-20261107-r114-private-read/`。[原件回执](validation/2026-11-07/private-read-r114-macos-package/receipt.json)。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42371059159/artifacts/13573737190) | `7786b95be731348ace2bba0dc62f0eb5b1ca78000975c7fbf3ce51860f7a6543` | `8154e7e263e0afa5eeccf536ce2c3bb7d86cb223975db533ee04954fcef046ac` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42371059159/artifacts/13573569843) | `e06db2fb996c398479330dacbab3793845cac46e746097254b4debdaa2b62f5c` | `825a10f7f543838226d95ef9904b4dbc05800d433588e48935ba240cc584283f` |

这是adhoc签名开发预览。正式签名、公证、干净系统、当前版本24h与完整项目仍待验；包部署通过不能替代完整协议。解压与CLI用法见下文。

## R114原生编译归档

双架构官方ZIP、内部tar摘要、源码提交、LICENSE、Mach-O架构和执行权限均已核验。本机副本`dist/macos-compiled-20261107-r114-private-read/`。[回执](validation/2026-11-07/private-read-r114-macos-compiled/receipt.json)。这是编译归档，仍需匹配Qt5/OpenSSL运行依赖。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42370990486/artifacts/13573921451) | `db06fddb869b2c4bd4463e840bb6f8cc3ad04fe9bf59166f77cb31a6bcb7884a` | `57fad4a3a7587511b8bd2c70e8c572fe07fb8d02c1cdde8a50a166108dbc8cdb` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42370990486/artifacts/13573767547) | `ac2bea6cbb727e53dca4baf32e22b06c11aac0960e893a23281b694ba4def064` | `aae32fe2d01ad352a14ccc472fffd7a9eda4273dbee923468c5ca4718f63ed5b` |

## R113含依赖预览（历史）

双架构Qt5/OpenSSL运行依赖、各372份应用源码、全部载荷与框架链接均逐件核验。两包各五项真实CLI/传输报告、系统PATH迁移、Cocoa导航及150%/200%高DPI通过；四张首页/服务器截图已查看。本机副本在`dist/macos-preview-20261107-r113-skip-reconcile/`。[回执](validation/2026-11-07/skip-reconcile-r113-macos-package-retry/receipt.json)。

| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42368208979/artifacts/13572073615) | `7f798d6f1be047bfe856ce10e86cce8d8187c0c5b8be6d9838b83560e0ce747a` | `106d95a80c4760b709fa2451e98ccc5df2b76a9a6e0b733e10505ec9299c288b` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42368208979/artifacts/13573099177) | `5e4c2b93823aac62c59f18249a3a86d35ffd6381c040b04e5ed19653958f81a5` | `4e514239a92848f07ed45d0dbf5f2a580998ff9bdfbff37e90cd1d06d45cf87f` |

这是adhoc签名开发预览；正式签名、公证、干净系统与完整项目交付仍待验。下方保留R111历史包及原失败，打包成功不覆盖完整协议失败。

## R113原生编译归档

双架构官方ZIP、内部tar摘要、源码提交、LICENSE、Mach-O架构及执行权限均通过。[回执](validation/2026-11-07/skip-reconcile-r113-macos-compiled/receipt.json)。这是编译归档，需要匹配Qt5/OpenSSL运行依赖。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42368086270/artifacts/13572920192) | `8e12a442314fe331fc3a01e94503971668c66f88459a94f930642b972feb493d` | `59f1329ab42fa2949d060c0431024ed15979df5bcf53a214a17ebf895577092e` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42368086270/artifacts/13572870643) | `57a9cc640fab14a63152b8bbc43d4b467b9a550a0e5322976891db1bbbcc2f2b` | `14f254b5ed464d69b7031e50c82f7edb1a8d3cfe4c6d35321925507cf3d4e9c3` |

## R111含依赖预览（历史）

双架构Qt5/OpenSSL依赖、各364份应用源码、全部载荷与71个框架链接、Mach-O架构/执行权限及归档摘要均逐件核验。两包各五项真实CLI/传输报告、系统PATH迁移、Cocoa导航与150%/200%高DPI通过，四张界面截图已查看。[原件回执](validation/2026-11-07/skip-directory-r111-macos-package/receipt.json)。本机副本在`dist/macos-preview-20261107-r111-skip-directory/`。

| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42363743119/artifacts/13571515179) | `550e797501be43dd9bb9a46eace199b378a0681b6beebd1d1aa041435ee25967` | `ec45a9b4299c058c4252dfe6c39fd2fef8ed5dad58929953b291880434c7cec4` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42363743119/artifacts/13571616789) | `c078087c81c701ec19efd746e5809c62fa7af8df5cd5c1547be1ba5587479dfb` | `82d56192c22437071ee0d77f1369d1a465ee04e196182631237b80ca314002c4` |

这是adhoc签名开发预览；Developer ID、公证、干净系统和完整项目仍待验。原协议失败不由打包成功覆盖。解压与CLI命令见本文下方使用说明。

## R111原生编译归档

对应[运行42362014363](https://github.com/29583855/dukto-next/actions/runs/42362014363)。官方ZIP/内部tar摘要、精确源码、LICENSE、Mach-O架构及GUI/CLI执行权限逐件通过；本机副本在`dist/macos-compiled-20261107-r111-skip-directory/`。[回执](validation/2026-11-07/skip-directory-r111-macos-compiled/receipt.json)。编译归档需要匹配Qt5/OpenSSL运行依赖，含依赖预览另验。

| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42362014363/artifacts/13569553162) | `fd73acc36657dfcc798fffea93ec180ad9679b49289bf02639b13deae03f869c` | `655ea1f7111dc8bd894ae68cbad54db3e9fd87de2eadbc69d9a319d551168f92` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42362014363/artifacts/13570575207) | `4cb34a919c1c68a9785ede0945fa1dceeda022ba5c61652e1b34300d4410dbb0` | `b194aae927c421b8cb86bd010c44b0551335276fa00089664666a5a6a37e1ec0` |

## R110已验含依赖预览及历史编译

更新日期：2026-11-07。R110精确`a29960a38fb46368dd8ac190caed2f4c515f8731`已在Apple Silicon和Intel原生环境以C++14/Qt5编译GUI及独立CLI；两架构各26个CTest、目录清理各45条已验，归档摘要/架构/执行位通过。双架构Qt5/OpenSSL含依赖预览、系统PATH搬迁、各五项真实CLI/传输报告和Cocoa导航均通过；四平台完整协议终态success。各一条精确Darwin端口独占XFAIL保留。

## R110最新含依赖预览

[双架构打包运行42352207494](https://github.com/29583855/dukto-next/actions/runs/42352207494)终态success。两架构的Qt/OpenSSL依赖、364份应用源码、全部载荷与框架链接、归档摘要和Mach-O身份均通过核验；系统PATH下搬迁启动、各五项CLI/传输报告及Cocoa导航均通过。[原件回执](validation/2026-11-07/directory-cleanup-r110-macos-package/receipt.json)。

| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42352207494/artifacts/13566366056) | `4420124e5e966524ee19cadc666d4401d261b45bae6132e7ed0e8319d4f47b3e` | `e6545125a4b1f65ed91ccd72c6e929991855e67e6d32a8b1dcb6a9d76d8a39c2` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42352207494/artifacts/13566343168) | `0cb9443e3053bd87b8d3bef504935b9683172a316bf8013789548d8a2a36d60a` | `f8bb4793cfb6b90ad82697a43c6c00f9acb193dc13abab5a37734bc445f95ce6` |

## R110原生编译归档

对应[运行42351739970](https://github.com/29583855/dukto-next/actions/runs/42351739970)。官方ZIP、内部tar SHA、精确源码、LICENSE、Mach-O架构及GUI/CLI执行权限逐件通过；本机副本在`dist/macos-compiled-20261107-r110-directory-cleanup/`。[回执](validation/2026-11-07/directory-cleanup-r110-macos-compiled/receipt.json)。

| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42351739970/artifacts/13565863520) | `a45ff1143b9f7714196ab246142b5f265794e38c677b97b3ca1f634a9231c2e4` | `3107555534a54211ac84540419409c5709fa7a49e23efaf590f50d2288058d3d` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42351739970/artifacts/13566320998) | `b13f83388ff82efbbe7b4573f950e366b0b32de7294822cb54fc6f7e8d87fc87` | `900d9d04d0ff46cf986d9ea4cf733d6262c29132051c20b9f0f60638e1af65b0` |

这是编译归档，需要匹配Qt5/OpenSSL运行依赖；当前双架构含依赖预览见本节顶部。核心通过不替代完整协议、干净系统或正式签名公证。

## R109原生编译归档（历史）

对应[运行42347962868](https://github.com/29583855/dukto-next/actions/runs/42347962868)。两架构的官方ZIP摘要、内部tar摘要、源码提交、LICENSE、Mach-O CPU架构及GUI/CLI执行权限已逐件核验；本机副本存于`dist/macos-compiled-20261107-r109-client-cleanup/`。[核验回执](validation/2026-11-07/client-cleanup-r109-macos-compiled/receipt.json)。

| 架构 | Actions下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [macos-compiled-ARM64](https://github.com/29583855/dukto-next/actions/runs/42347962868/artifacts/13564775658) | `b9cadc32ba39beab41316cb98dc9ee040973b1e35f4c103513ccd077e46023b2` | `71fca3707db61d1750e5b71421d82eafa6d68c8ce2f1cfe07abc6fd1aa095512` |
| x86_64 | [macos-compiled-X64](https://github.com/29583855/dukto-next/actions/runs/42347962868/artifacts/13564417308) | `22a57ffda0573c70c13a00c5f989534ed543bacb38a8f00c9d682a492ce1bb22` | `e7eac194d2e7bb16a5fda861f61ec270d637a69f739d0c791e0ecbe6daa2480b` |

这些是原生编译产物，需要匹配的Qt5/OpenSSL运行依赖；完整含依赖预览见下方R108。R109新增本机客户端下载普通文件临时正文清理，完整原生测试及正式签名公证资格仍单独验收，不能由编译成功替代。

## R108含依赖部署包（历史）

[双架构原生部署与搬迁工作流](https://github.com/29583855/dukto-next/actions/runs/42333318212)终态success。两架构均完成GUI/CLI编译、依赖部署、系统PATH下迁移验证与五项业务报告；附件下载可能需要登录GitHub。

| 架构 | 下载 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [macos-preview-ARM64](https://github.com/29583855/dukto-next/actions/runs/42333318212/artifacts/13559720206) | `1dc1c2bf48228cef5bfbeacb004df8177d52e87762fbdcda3e4b743faddbe1a3` | `c1498796487c4300cde52c3a39fbafbfc0f120471e9a1388c1a9b2392beb484d` |
| x86_64 | [macos-preview-X64](https://github.com/29583855/dukto-next/actions/runs/42333318212/artifacts/13558991748) | `ff50e8c020b5d264f3078cb3f85579a378ded297f075e761e3acd69793f71707` | `0fef11835e4abfa6c967fb45aa63c377e876624c39ba48c213c643e91686d2c4` |

两包各含356份应用源码全集与71个框架链接，逐blob匹配打包提交；Mach-O架构、执行权限、全部载荷及内部SHA均通过。Intel包1705个部署文件、Apple Silicon包1547个；每包独立CLI、16通道双向、覆盖/恢复等五项运行报告均通过。Cocoa及150%/200%界面导航通过，四张首页和服务器导航截图已查看。[双架构原件与回执](validation/2026-11-07/expiry-r108-macos-package-terminal/)。

先解压ZIP，再用tar保留框架链接和执行权限。Apple Silicon示例（Intel将arm64替换为x86_64）：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

保留整个目录，CLI启动器与.app相邻；CLI独立运行不要求GUI先启动。当前为adhoc签名开发预览，Developer ID、公证、最低/干净系统、完整GUI和选择器、各平台长期与正式发布继续验收。

## R108原生编译归档

R108应用源码`73cd10ac95be6c97fd67134ba14b6edee4b2c189`已在 [公开仓库](https://github.com/29583855/dukto-next) 编译。Apple Silicon与Intel两个原生任务均成功生成GUI与CLI；官方附件摘要、内部tar摘要、来源提交、许可证、Mach-O架构和执行位已核验，详见[编译回执](validation/2026-11-07/expiry-r108-macos-compiled/receipt.json)。

| 架构 | Actions编译归档 | 官方ZIP SHA-256 | 内部tar.gz SHA-256 |
| --- | --- | --- | --- |
| arm64 | [macos-compiled-ARM64](https://github.com/29583855/dukto-next/actions/runs/42332515396/artifacts/13557513668) | `8262cd8a5910e77b553198406137a5fd61bcd153477c67b71322f243721ce360` | `11300e5cdeafa83603849ac5b0f6c6609a13b6b27983f1b4032484daa3c4c25c` |
| x86_64 | [macos-compiled-X64](https://github.com/29583855/dukto-next/actions/runs/42332515396/artifacts/13558426195) | `fb4b8c0396308396fff7d5b761a81d324e610043c9cb5495a3ec4f4c81e46a23` | `3d0322b09639c58c85d979468d10671034d00c9bf8f20a8aa8b62aa3210f2deb` |

这两个是源码提交`73cd10a`的原始编译归档，未打包Qt5/OpenSSL运行依赖；对应的含依赖可运行包已更新到上方R108。该提交原生完整CI `42332515396`终态failure，Windows CLI端口选择测试失败，其他三个runner成功。后续`cef3759`运行`42336003722`终态failure，Apple Silicon核心/GUI控制器及协议测试失败，Ubuntu、Intel、Windows成功。最新`6eea9d2`复验见下节。

## `6eea9d2`原生复验（终态失败，原件保留）

[GitHub Actions运行42340140189](https://github.com/29583855/dukto-next/actions/runs/42340140189)对应精确源码`6eea9d23a254ac0095e588b03d76c19faf7bf5cf`，已终态failure。两架构GUI/CLI编译均成功；Windows、Ubuntu和Apple Silicon job成功，Intel `transfer-retry`在1秒总时限内未进入queued状态，排队期限断言失败且未生成该项报告。原job日志、执行清单和官方附件摘要已[收验保存](validation/2026-11-07/client-cleanup-r109-prior-ci/receipt.json)，未授予整轮通过资格。当前最新编译归档和核心结果见上方R110；R108含依赖包仍单独标记其源码身份。

## R105含依赖部署包（历史）

[双架构原生部署及迁移工作流](https://github.com/29583855/dukto-next/actions/runs/42321257970)终态success。ZIP含tar.gz、SHA-256和运行原件，附件下载可能需要登录GitHub。

| 架构 | 下载 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42321257970/artifacts/13552932598) | `d3b0c4bf119c50b686c21bd5fc1865285614d37342fa84172b360e1b8b8d8dd4` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42321257970/artifacts/13553163728) | `fdd310dfc86d96c099fe7a172226f90a6303820089676568bf5eea25b64dbc99` |

每包348份应用源码全集逐字节匹配精确Git提交；全部载荷、各71个框架链接、Mach-O架构和执行位已核验。包在中文空格新目录、仅系统PATH下实际运行，CLI不加载GUI框架；每包五份业务原报告通过：独立CLI、16通道双向、1/4/16覆盖、覆盖恢复及4→8恢复。Cocoa及150%/200%导航通过，四张实际启动/导航截图已查看。[原件与视觉收验](validation/2026-11-07/task-items-r105-macos-package-terminal/qualified-receipt.json)。

先解压ZIP，再用tar保留框架链接和执行权限。Apple Silicon示例（Intel将arm64替换为x86_64）：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

保留整个目录，CLI启动器与.app相邻；CLI独立运行不要求GUI启动。当前为adhoc签名开发预览，Developer ID、公证、最低/干净系统、完整GUI及选择器、各平台长期与正式发布继续验收。

## R105原生编译归档

以下是同提交的原始编译输出，仍需匹配运行依赖；直接运行优先使用上方含依赖包。

| 架构 | 编译归档 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42321115720/artifacts/13553316446) | `4e9bc456c3d38016efbe30649e975220cb48077459ddf88c6ccb68e0ec7abc93` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42321115720/artifacts/13552799237) | `1034698c77c56794f0e0f07e7196c6482455386f3cf638c3bddb4274dd2b106b` |

[编译回执](validation/2026-11-07/task-items-r105-macos-compiled/receipt.json)。完整原生协议仍按其自身终态收验；R104 Ubuntu及Apple Silicon原失败均保留，各47项中46项通过、task-items旧夹具失败。R105仅修正夹具，未声称修复生产传输缺陷或完成整体稳定性验收。

## 历史版本与原始记录

## 当前R100含依赖部署包

[双架构打包与原生迁移工作流](https://github.com/29583855/dukto-next/actions/runs/42286046864)终态success；ZIP含tar.gz、校验文件和运行原件，附件可能需要登录GitHub。

| 架构 | 下载 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42286046864/artifacts/13538291807) | `8a383b4f06e06163ae598cf64e558049b3f57053d8af919ddca9adb6865d5fde` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42286046864/artifacts/13537109669) | `244adf11797860213e8039f0be8fa9ef5b8beed5ddf365c33839a094bd5ecdb4` |

每包338份应用源码全集与精确Git对象一致；各71框架链接、全部载荷、Mach-O架构和执行权限已验。每包五份原业务报告通过，覆盖独立CLI、16通道双向、1/4/16覆盖及4→8恢复；系统PATH/中文空格路径迁移通过。Cocoa及150%/200%导航和中文覆盖通过，四张实际原生启动/导航截图已查看。[收验及独立视觉回执](validation/2026-11-07/clipboard-r100-macos-package-terminal/qualified-receipt.json)。

解压ZIP后用tar保留权限和框架链接，启动方式见下方示例。当前是adhoc开发预览；Developer ID、公证、干净系统、最低系统、完整GUI/选择器、第三方源码独立重建及正式发行继续验收。完整协议和长期按各自真实终态收验。

## R104最新编译产物（2026-11-07）

精确源码9c1e9419f7acb9bc3ddf2b8133eb330ead0c3fa6的双Mac GUI/独立CLI已编译、归档并上传；附件及内部tar摘要、源码、Mach-O架构、执行位和许可已逐项核验。

| 架构 | 编译产物 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42316601470/artifacts/13551071933) | 2177469af5c44bc8a4e3c1972ec6459163c41538e7021850a03dba6eacc82a60 |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42316601470/artifacts/13551037372) | 52023b03e3485504d06560f31e45a071f50d847314b4c3a3030df9955eb50014 |

[编译回执](validation/2026-11-07/state-use-r104-macos-compiled/receipt.json)。这些编译归档仍需匹配Qt5/OpenSSL运行依赖；含依赖预览仍为顶部R100。R104四runner各23核心/88份Qt原报告已验，新增状态目录共享/独占互斥方法实际通过，两条精确Darwin预期失败保留。[核心回执](validation/2026-11-07/state-use-r104-native-core/receipt.json)。Ubuntu POSIX八进程/链接拒绝专项已核验；其完整协议作业因task-items旧夹具失败，两项磁盘步骤跳过。R105只修正夹具并通过双Windows定向复验，独立Ubuntu上传超时未通过，新原生CI待验；本节Mac编译产物仍为R104。过期回收及整个R04继续。

## R103编译记录（2026-11-07）

精确源码cd92c43f301e5a60584b7896a450247855f0bdfd已公开；[原生CI 42311369310](https://github.com/29583855/dukto-next/actions/runs/42311369310)的Apple Silicon/Intel编译、归档及上传成功。两份GUI/独立CLI的GitHub附件/内部tar摘要、源码、Mach-O架构、执行位及许可已逐件核验。

| 架构 | 编译产物 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42311369310/artifacts/13548786324) | f19fe9714db4aba9f5579f5504af26b95f830ee03ab974210a9a38f08e0adfb7 |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42311369310/artifacts/13547644596) | 1f6a12a3b2aee1c264b66b6f4dd99727a817d4091ca0c6193c31f96b117abbd6 |

[R103编译回执](validation/2026-11-07/diagnostics-r103-macos-compiled/receipt.json)。归档需要匹配Qt5/OpenSSL依赖，CI自行下载安装；含依赖预览仍为顶部R100。四runner各23核心/88份Qt原报告已验，含新增诊断核心及GUI方法，两条精确Darwin预期失败保留。[核心回执](validation/2026-11-07/diagnostics-r103-native-core/receipt.json)。完整协议、真实CLI诊断原生专项、保存选择器及整个R10仍待验。

## R102编译记录（2026-11-07）

精确源码`c1325b0b33ff4df116449c1e1c00d5b27a1a125c`已公开；[原生CI 42304553041](https://github.com/29583855/dukto-next/actions/runs/42304553041)的Apple Silicon/Intel原生编译、归档及附件上传均成功。两份GUI/独立CLI已取回，官方附件摘要、内部tar摘要、源码、Mach-O架构、执行权限及许可逐件核验。

| 架构 | 编译产物 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42304553041/artifacts/13545078414) | `039ad27382e784ca236c33737ed69e552fc44809e8420fa806b0787305ac38d5` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42304553041/artifacts/13545822719) | `24b7cf4800fef5cb220b5fa228a10c00af7f57df716ab77dc58ee6ee6105dbd5` |

[R102编译原件回执](validation/2026-11-07/cancel-r102-macos-compiled/receipt.json)。归档需要匹配Qt5/OpenSSL依赖；CI自行下载安装。含依赖开发预览包继续使用顶部R100入口，未更换其源码身份。

R102四runner各23核心、88份Qt原报告及48行取消回归已核验，含每平台原生/150%/200%场景、清理后同控制器双向内容核验；两条Darwin预期失败明确保留。[核心与取消子集回执](validation/2026-11-07/cancel-r102-native-core/receipt.json)。完整协议和原生槽负例总JSON仍待最终附件；不授完整F18、整个GUI或正式发布资格。R101原生发送取消失败继续保留，独立Ubuntu旧夹具三次成功复查也不覆盖该失败。

## R101编译及原始失败记录（2026-11-07）

精确源码`1f82d5d3b9ae36e77ee98da942c2fc5369310c7a`已公开；[原生CI 42300792120](https://github.com/29583855/dukto-next/actions/runs/42300792120)的Apple Silicon和Intel实际编译、归档及附件上传成功。GUI与独立CLI的附件摘要、内部tar摘要、源码、Mach-O架构和执行权限均已核验。

| 架构 | 编译产物 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42300792120/artifacts/13543243824) | `629ab2ca00f35e59268ec391ba294f5d76d328acfe3b7779d2bb1246f0a7cb15` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42300792120/artifacts/13543578499) | `ca4c89fd5724d621618ec594d169d3295207a5b24002afbd1cc0c1402552e87f` |

[R101编译原件回执](validation/2026-11-07/cancel-r101-macos-compiled/receipt.json)。这些归档需要匹配的Qt5/OpenSSL依赖；含依赖预览包继续使用本页顶部R100入口。Qt5/OpenSSL由CI自动下载安装，无需用户手动配置构建环境。

R101新增取消回归在四runner均观察到发送场景失败：Linux未稳定停在取消点，云Windows及两Mac出现对端EOF五秒超时；接收两场景通过。原报告已保留，[原始观察](validation/2026-11-07/cancel-r101-native-observation/observation-221303.json)。新慢端夹具仍在本机验证，不能把编译成功记为完整测试通过。

## R100编译记录（2026-11-07）

精确源码`ed4f5cf08c96f04671e49e5138eda8ce1790ead3`已上传公开仓库；[四平台CI 42282812778](https://github.com/29583855/dukto-next/actions/runs/42282812778)已自动启动，Apple Silicon与Intel的实际编译、归档和附件上传步骤均成功。两份GUI/独立CLI归档的GitHub摘要、内部tar摘要、源码提交、Mach-O架构及执行权限已逐件核验。

| 架构 | 最新编译产物 |
| --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42282812778/artifacts/13535778206) |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42282812778/artifacts/13535669142) |

[R100编译原件回执](validation/2026-11-07/clipboard-r100-macos-compiled/receipt.json)绑定实际GUI和CLI摘要。这些归档需要匹配的Qt5/OpenSSL运行依赖；当前含依赖R100包见顶部；本节保留独立编译原件。R100定向补跑后四runner终态success，原件已核验各23核心及合计188协议，两条Darwin预期失败明确披露；首轮附件上传超时保持历史失败。正式发布继续验收。

## R99编译记录（2026-11-07）

精确源码`a316e4a4f947ac9a53aa6dd4477eb5b8e2a7fb38`已上传；[原生CI 42276738981](https://github.com/29583855/dukto-next/actions/runs/42276738981)的ARM64、Intel编译步骤均成功。两份实际归档、源码提交、Mach-O架构和执行权限已核验，包含GUI与独立CLI。

| 架构 | 编译产物附件 |
| --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42276738981/artifacts/13533422500) |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42276738981/artifacts/13534425181) |

[编译原件回执](validation/2026-11-07/text-send-r99-macos-compiled/receipt.json)绑定实际程序摘要。本节归档需要匹配的Qt5/OpenSSL运行依赖；当前含依赖R100包见顶部；本节保留R99编译身份。R99完整原生回归现已严格收验四平台各23核心和合计188协议，通过原件见R99终态回执；编译产物本身不授予正式发布资格。

## R96下载与校验（历史）

[R96双架构原生打包与迁移工作流](https://github.com/29583855/dukto-next/actions/runs/42253077233)终态success，全部产物已按精确Git树和原报告核验。附件下载可能需要登录GitHub；ZIP包含tar.gz、校验文件及运行报告。

| 架构 | GitHub附件 | 内部tar.gz的SHA-256 |
| --- | --- | --- |
| Apple Silicon / arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42253077233/artifacts/13522446070) | `21b7c187ecdb49734240f668e0e6f7c21660929a92ea73059d1125c40962245a` |
| Intel / x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42253077233/artifacts/13523845555) | `749abede37be1ae1cb87acaf9289c4eef39e7f251887fed44b0c86b9e1fb9590` |

先解压ZIP。Apple Silicon示例（Intel将arm64替换为x86_64）：

```sh
shasum -a 256 -c DuktoNext-macos-arm64-preview.tar.gz.sha256
tar -xzf DuktoNext-macos-arm64-preview.tar.gz
cd DuktoNext-macos-arm64-preview
open "Dukto Next.app"
./dukto-cli --help
```

使用tar解包保留框架链接和执行权限。移动时保留整个目录，CLI启动器与.app相邻；应用内CLI位于`Dukto Next.app/Contents/MacOS/dukto-cli`，独立运行不要求GUI启动。

## R96已验证范围（历史）

GUI保留Dukto设备/最近/关于布局，底部“服务器 · 上传 / 下载”进入服务器页。两包分别在原生Mac运行器的中文空格目录和系统PATH下验证：独立CLI、16通道双向传输、1/4/16通道覆盖、覆盖恢复和4→8通道恢复，每包五份原业务报告逐摘要一致。

arm64有1547份载荷，Intel有1705份；各71个框架链接、Mach-O架构、执行权限、依赖来源及adhoc签名均已核验。每包内附329份应用源码，全集逐字节匹配精确提交。两架构启动页/服务器页共四张原生截图已查看，中文和主要控件正常。Cocoa主窗口导航及150%/200% offscreen紧凑布局通过；完整原生GUI操作、原生文件选择器和Retina仍各自验收。

[同提交焦点回归](https://github.com/29583855/dukto-next/actions/runs/42251051894)各23核心、五轮监听/双栈/优雅重启和各十轮原并行退出通过。每次核心明确记录一条Darwin预期失败：系统允许后来外部Qt通配/具体地址端口共享。本软件主动启动时检查并拒绝已有冲突，不声称内核独占或防止外部程序后来共享端口。

四平台完整CI的第二次运行已严格收验success：各23核心，合计188协议，双Mac各46协议。原ARM零步骤容量取消及首轮failure保留，第二次只补该ARM任务；Mac完整核心各有一条明确Darwin XFAIL。R98双Mac新退出夹具已按精确b2e4659收验，各23核心、四种退出状态及原16组、五轮监听/重启和各十次退出复查通过；每次核心明确一条Darwin XFAIL。包内源码身份仍为R96。旧R95独立Ubuntu完整回归22/23，16通道退出超时仍未证明根因；三次独立复查通过不能覆盖原失败。包内五业务通过不等于完整产品稳定性或长期验收完成。

本机归档：`dist/macos-preview-20261107-r96-boundary/BUILD-RECEIPT.json`。[当前索引](current-validation.json)和[双包原件回执](validation/2026-11-07/boundary-r96-macos-package-terminal/receipt.json)记录精确提交、附件及摘要。

## 交付边界

当前是adhoc签名开发预览。Developer ID签名、Apple公证、干净Mac/Gatekeeper、最低系统、依赖对应源码独立重建、物理网络/3×3和当前各平台长期资源验收尚未完成。releaseQualified=false，deliveryComplete=false。

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


### v0.72 终止错误与真实盘满，Mac首次失败保留（2026-11-06）

- [x] [生产dab7c0e](https://github.com/29583855/dukto-next/commit/dab7c0e25585504f9ea38bd5cff5c61e51efe9f9)已非强制上传。多通道数据先断线时，磁盘/权限/完整性及控制明确取消可保留原分类；数据组清理取消不能覆盖根因。失败读取期限仍为原连接预算与3000ms的较小值，busy/进度不续期，普通确认不能变成成功。
- [x] 双Windows UCRT/MSVC实际GUI/CLI编译、各21/21核心、190文件交换用例及九份公共协议报告通过，输入前后不变。八条新增终止边界与原32条处置拒绝通过。Ubuntu独立64MiB tmpfs真实TLS盘满专项终态成功：rename/overwrite、1/4/16通道、双向六报告/12方向均为真实ENOSPC和错误5，原件保护、有效part保留及释放空间后恢复SHA已验。
- [x] 精确dab7c0e的Alpine原生CPU运行42135996839终态success，21核心/40协议原报告及SHA逐份核验；Ubuntu40协议原报告同样已验。182维护源码零TODO/占位/简化标记，C++14和格式检查通过；零标记不等于全部验收。
- [x] 新双Mac包42136000531均原生编译、部署，全部载荷/链接/架构/权限与各253份内附应用源码核验。ARM五业务报告通过；Intel在覆盖恢复故障注入前未达50%真实落盘检查点，工作流失败。原包及日志保留，当前下载入口保持已验d973da1双包。
- [x] 新故障夹具在两Mac初次核心均20/21；五秒准备诊断仍失败。日志显示服务端约70ms握手完成后休眠等待数据，饿死后续Qt/TLS事件。测试提交234a5d2在等待中继续处理事件并恢复原两秒期限；双Windows40条边界复验通过。首次失败和无效的延长期限方案均保留。
- [x] 恢复测试新增清理前有界诊断，刻意失败自检与Windows原八项4→8覆盖恢复通过；50%检查点及原90秒恢复门槛保持。原Intel包独立复查42138790167记录包源码与诊断脚本提交，禁止用复查覆盖首次失败。
- [ ] 新Mac夹具四runner42139150179原生复验及Intel原包检查点失败根因继续；完整新原生终态与所有附件按精确提交独立核验。公开skip、全部原版交互/原生选择器、全局预算/安全GC、物理LAN提速/3×3、当前各平台24h、第三方完整对应源码/独立重建、干净系统和正式签名/公证/发布仍未完成。旧包、旧长测与旧Alpine d973本地失败保持原输入。[本轮回执](ci-verification-20261106-r72.json)。


v0.72复查补记（2026-11-06）：同一Intel原始包SHA 7a24f9d01d6fda443fce9800eddff7fe889e01f4977f0ddb3cc0ea14ced6c5a3 在独立运行42138790167通过全部五业务报告，16项双向恢复仍满足50%真实检查点与原90秒预算，原报告SHA和诊断脚本输入已核验。首次未达到检查点的失败原包/日志保留，根因仍未证明已消除，不将成功复查当作缺陷修复。[复查证据](validation/2026-11-06/terminal-r72-intel-recheck/verified-summary.json)。


v0.72核心终验补记（2026-11-06）：测试234a5d2在Windows、Ubuntu、Apple Silicon和Intel四runner均通过各21项核心、190文件交换用例。全部JUnit实际用例结果和八条故障边界逐原件核验：磁盘5、权限4、明确取消7，异常/篡改/普通确认拒绝保持；busy仍受原2000ms总预算。Qt5把64条阶段qinfo计入JUnit errors计数，已逐条确认其为夹具信息注释，实际failure/error节点为零。Mac夹具休眠饿死TLS事件的问题已解决；首次2秒和5秒失败原件保留，完整协议仍在执行。[四平台原件核验](validation/2026-11-06/terminal-fixture-r73-pump-native/verified-summary.json)。

v0.73/r74补记（2026-11-06）：当前生产cf37197增加只读skip完成核验，双Windows已验；新四runner42144847843包含Apple Silicon及Intel原生Qt5/C++14构建与运行，结果待实际原件。原dab42135946545已经终态failure：四平台163协议报告全通过，但Windows核心20/21和两Mac初次夹具失败保留；后续234核心四平台21/190已验。现有d973下载包不含cf变更，Intel候选包首次检查点失败根因尚未解决。[本轮回执](ci-verification-20261106-r74.json)。

r75原生终态补记（2026-11-06）：234a5d2完整四runner已终态failure；四套核心各21/190通过，协议162/163，唯一失败是Intel凭据轮换的活动传输停止分类/状态断言，原业务报告缺失。d879f77只增加测试诊断，双Windows各12检查通过，双Mac原门槛专项42146188465待原件。生产cf37197及现有d973预览入口保持其原范围；首次包检查点失败根因仍开着。[诊断回执](ci-verification-20261106-r75.json)。

r75实际原件补记（2026-11-06）：生产cf37197的Windows、Ubuntu、Apple Silicon、Intel和Alpine五套原生核心均通过各21/21；Windows50、POSIX51接收跳过用例，以及每套190文件交换用例逐原件核验。Ubuntu和Alpine各40协议原报告及SHA已验，Alpine工作流终态success；完整四runner协议仍待收齐。

诊断d879f77的Windows原生128轮终态failure：126通过，98/124两轮在工作者commit阶段返回code5/stage conflict，定位到TargetReservation创建预约锁，尚未进入最终改名。原错误没有Qt锁分类/原生错误码，不能确认具体竞态。双Mac凭据轮换专项终态success，两份原报告各12检查及双向四通道停止/恢复原门槛已验；成功复验不等于首错根因解决。原生两轮失败、首次Intel轮换失败、原包检查点失败均保留。

另一个只在本机缓存内的DeletePending夹具假设未证实：持有旧锁观察句柄时，QLockFile解除名字后仍能建立新预约，不满足“必须等待读者关闭”的假设。失败实验归档后已从维护测试撤回，并重建原core-tests及复验并发提交通过；未改生产锁语义。下一步需要在真实原生失败时取得Qt锁错误分类并继续接公开skip。[诊断回执](ci-verification-20261106-r75.json)。

v0.74/r76更新（2026-11-06）：5e862f5已上传，新四runner42150041377与双Mac部署42150170860实际启动。Qt5/OpenSSL仍由CI自行安装；待真实编译/迁移原件验完才替换下载入口。当前入口保留d973da1及其原SHA；Intel首次轮换/包检查点失败根因未确认，不因后续成功消除。[本轮回执](ci-verification-20261106-r76.json)。


v0.74/r76交付补记（2026-11-06）：当前入口已切换到精确5e862f5双Mac包。工作流42150170860及两job终态success，各263份应用源码与Git树全集一致；全部载荷、71链接/架构/执行位、各五份业务原报告和四张截图已核验。旧d973da1包及原失败保留，正式发布未完成。


v0.77/r79收件补记（2026-11-06）：当前入口更新为精确5ebbdbc双Mac包，工作流42157539455及两job终态success。各270份应用源码与Git树全集逐字节一致；ARM1547/Intel1705载荷、各71链接、各五份业务报告及四截图已核验。5e旧包与历史失败保留。最新生产39fcd22的原生资格另行记录，不借用本包结果。


v0.78/r80收件（2026-11-06）：当前入口更新至9ac5ca7双Mac包，部署42162374097及两job终态success。各274源码与精确Git树一致；ARM1547/Intel1705载荷、各71链接、五份业务子报告和四截图已核验。旧5ebbdbc包独立保留；正式签名、公证和干净系统资格继续。


v0.79/r81收件（2026-11-06）：当前入口更新至8ff4fb6双Mac包，部署42165735963及两job终态success。各277源码与精确Git树全集一致；全部载荷、各71链接、五业务报告及四截图已核验。旧9ac5ca7包独立保留；正式签名、公证和干净系统资格继续。


v0.80/r82收件（2026-11-06）：当前入口更新至8e90778双Mac包，部署42170433020及两job终态success。各280源码与精确Git树全集一致；全部载荷、各71链接、五业务报告及四截图已核验。旧8ff4fb6包独立保留；正式签名、公证和干净系统资格继续。


R86补记（2026-11-06）：06089a5双架构原包、各290源码、五业务报告及四截图已验。旧9b880f4包仍保留，不继承新提交资格。


R87补记（2026-11-06）：精确409a73b双Mac包各293源码、五原业务报告及四截图已核验。当前下载包含公开skip；其完整原生协议独立收件，不用部署包成功代替全量回归。

## R107新源码编译归档

精确源码`e220461bdd0a409b10f483a3aaa321db927975c3`的两种架构已编译并核验GUI/CLI、Mach-O和摘要。以下归档未部署运行依赖；上方可运行含依赖预览仍为R105。R107完整协议及运行部署继续。

| 架构 | 编译归档 | 内部tar.gz SHA-256 |
| --- | --- | --- |
| arm64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42327794378/artifacts/13555753915) | `b32d3466822c21fe31796b16ee8a988a1d7976f507807874d04be7a6706a9989` |
| x86_64 | [下载](https://github.com/29583855/dukto-next/actions/runs/42327794378/artifacts/13556431606) | `39f4f750924540588d870e025945af6fbc9fa3165d6a7e931cb002eee1ccf194` |

[编译回执](validation/2026-11-07/secure-ready-r107-macos-compiled/receipt.json)。
