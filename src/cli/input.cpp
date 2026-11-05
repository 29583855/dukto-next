#include "input.h"
#include "core/error.h"
#include "core/files.h"

#include <QElapsedTimer>
#include <QThread>

#ifdef Q_OS_WIN
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <atomic>
#include <exception>
#include <thread>
#include <windows.h>
#else
#include <cerrno>
#include <poll.h>
#include <unistd.h>
#endif

// 日期：2026-11-05；管道空闲也检查超时；Windows 取消使用真实 HANDLE，兼容 MSVC/MinGW 线程实现。
QByteArray readStandardInput(int timeoutMs, const std::function<bool()> &cancelled,
                             bool allowTerminal) {
    QByteArray result;
    QElapsedTimer idle;
    idle.start();
#ifdef Q_OS_WIN
    std::atomic_bool done{false};
    std::atomic_bool stopping{false};
    std::atomic_int progress{0};
    std::atomic<HANDLE> readerHandle{nullptr};
    std::exception_ptr failure;
    // 日期：2026-11-05；复制当前线程的原生句柄，不假定 C++ 库的 native_handle_type 是 HANDLE。
    std::thread reader([&]() {
        try {
            HANDLE threadHandle = nullptr;
            if (!DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(),
                                 &threadHandle, THREAD_TERMINATE, FALSE, 0))
                throw dukto::Error(dukto::ExitCode::Runtime,
                                   QStringLiteral("无法创建标准输入取消句柄"), "stdin");
            readerHandle.store(threadHandle);
            const auto handle = GetStdHandle(STD_INPUT_HANDLE);
            if (!handle || handle == INVALID_HANDLE_VALUE)
                throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("标准输入不可用"),
                                   "stdin");
            DWORD mode = 0;
            const bool console = GetConsoleMode(handle, &mode) != 0;
            if (console && !allowTerminal)
                throw dukto::Error(dukto::ExitCode::Config,
                                   QStringLiteral("非交互模式请使用文件或管道提供文本"), "stdin");
            while (!stopping.load()) {
                DWORD count = 0;
                bool end = false;
                QByteArray bytes;
                if (console) {
                    wchar_t characters[4096];
                    if (!ReadConsoleW(handle, characters, 4096, &count, nullptr)) {
                        if (stopping.load())
                            break;
                        throw dukto::Error(dukto::ExitCode::Disk,
                                           QStringLiteral("控制台输入读取失败"), "stdin");
                    }
                    auto text = QString::fromWCharArray(characters, static_cast<int>(count));
                    const auto eof = text.indexOf(QChar(0x1a));
                    if (eof >= 0) {
                        text.truncate(eof);
                        end = true;
                    }
                    bytes = text.toUtf8();
                } else {
                    char buffer[65536];
                    const auto remaining = dukto::MaxTextBytes + 1 - result.size();
                    if (!ReadFile(handle, buffer,
                                  static_cast<DWORD>(qMin(qint64(65536), remaining)), &count,
                                  nullptr)) {
                        if (stopping.load() || GetLastError() == ERROR_BROKEN_PIPE)
                            break;
                        throw dukto::Error(dukto::ExitCode::Disk,
                                           QStringLiteral("标准输入读取失败"), "stdin");
                    }
                    bytes = QByteArray(buffer, static_cast<int>(count));
                }
                if (stopping.load())
                    break;
                result.append(bytes);
                progress.store(result.size());
                if (result.size() > dukto::MaxTextBytes)
                    throw dukto::Error(dukto::ExitCode::Config,
                                       QStringLiteral("文本不能超过 8 MiB"), "stdin");
                if (count == 0 || end)
                    break;
            }
        } catch (...) {
            failure = std::current_exception();
        }
        done.store(true);
    });
    int observed = 0;
    bool wasCancelled = false;
    bool timedOut = false;
    while (!done.load()) {
        const auto current = progress.load();
        if (current != observed) {
            observed = current;
            idle.restart();
        }
        wasCancelled = wasCancelled || cancelled();
        timedOut = timedOut || idle.elapsed() >= timeoutMs;
        if (wasCancelled || timedOut) {
            stopping.store(true);
            // 日期：2026-11-05；重复取消覆盖读取前的竞态；句柄只在 join 完成后关闭。
            if (const auto handle = readerHandle.load())
                CancelSynchronousIo(handle);
        }
        QThread::msleep(20);
    }
    reader.join();
    if (const auto handle = readerHandle.load())
        CloseHandle(handle);
    if (wasCancelled)
        throw dukto::Error(dukto::ExitCode::Cancelled, QStringLiteral("已取消读取标准输入"),
                           "stdin");
    if (timedOut)
        throw dukto::Error(dukto::ExitCode::Network, QStringLiteral("标准输入无进展超时"), "stdin");
    if (failure)
        std::rethrow_exception(failure);
#else
    if (!allowTerminal && ::isatty(STDIN_FILENO))
        throw dukto::Error(dukto::ExitCode::Config,
                           QStringLiteral("非交互模式请使用文件或管道提供文本"), "stdin");
    while (true) {
        if (cancelled())
            throw dukto::Error(dukto::ExitCode::Cancelled, QStringLiteral("已取消读取标准输入"),
                               "stdin");
        if (idle.elapsed() >= timeoutMs)
            throw dukto::Error(dukto::ExitCode::Network, QStringLiteral("标准输入无进展超时"),
                               "stdin");
        pollfd descriptor{STDIN_FILENO, POLLIN, 0};
        const int ready = ::poll(&descriptor, 1, 50);
        if (ready < 0) {
            if (errno == EINTR)
                continue;
            throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("标准输入轮询失败"), "stdin");
        }
        if (ready == 0)
            continue;
        char buffer[65536];
        const auto count = ::read(
            STDIN_FILENO, buffer,
            static_cast<size_t>(qMin(qint64(65536), dukto::MaxTextBytes + 1 - result.size())));
        if (count < 0) {
            if (errno == EINTR)
                continue;
            throw dukto::Error(dukto::ExitCode::Disk, QStringLiteral("标准输入读取失败"), "stdin");
        }
        if (count == 0)
            break;
        result.append(buffer, static_cast<int>(count));
        if (result.size() > dukto::MaxTextBytes)
            throw dukto::Error(dukto::ExitCode::Config, QStringLiteral("文本不能超过 8 MiB"),
                               "stdin");
        idle.restart();
    }
#endif
    return result;
}
