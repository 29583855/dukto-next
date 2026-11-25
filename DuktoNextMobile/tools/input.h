#pragma once

#include <QByteArray>
#include <functional>

// 日期：2026-11-04；有界读取标准输入，支持空闲超时与取消，不要求管道先关闭才能退出。
QByteArray readStandardInput(int timeoutMs, const std::function<bool()> &cancelled,
                             bool allowTerminal = true);
