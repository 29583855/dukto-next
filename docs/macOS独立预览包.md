# macOS程序包

更新日期：2026-11-09。当前R158分别提供Apple Silicon及Intel原生依赖包，已通过Cocoa启动、导航/DPI、仅系统PATH迁移及五项传输/恢复业务验收。

[程序与启动说明](../dist/交付程序-20261109/README.md) · [完整验收记录](三平台程序交付验收.md)。

两个架构均在macOS15验证，更早macOS未在本次验证兼容。包内包含Qt/OpenSSL；当前adhoc签名、未Developer ID签名或公证，首次打开可能需要系统允许。请在目标Mac上解压，并保留完整app、依赖、执行权限和框架链接。
