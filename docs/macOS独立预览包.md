# macOS程序包

更新日期：2026-11-09。当前推荐macOS12兼容版，分别提供Apple Silicon与Intel原生依赖包；最低目标为macOS12.0，包含客户的12.7.6。GUI、CLI、Qt5和OpenSSL已统一重编译，并逐一核对全部原生载荷的实际最低版本。

[下载兼容版](https://github.com/29583855/dukto-next/releases/tag/preview-macos12-20261109) · [安装、选包和兼容说明](macOS12兼容说明.md) · [本地程序目录](../dist/macOS12兼容版-20261109/README-macOS12.md)。

两架构各35/35核心及5项业务测试通过，Cocoa界面、仅系统PATH迁移、16通道传输、覆盖及恢复已在macOS15原生验证；macOS12.7.6客户机器仍待现场确认。当前adhoc签名、未Developer ID签名或公证，首次打开方法见兼容说明。旧R158 Mac包要求macOS15，请勿用于macOS12。
