/* 日期：2026-11-08；同一翻译单元编译已核验的原版SQLite，适配读取真实类型，不猜测结构偏移。 */
#if defined(_WIN32) && !defined(_WIN32_WINNT)
#define _WIN32_WINNT 0x0602
#endif
#include <sqlite3.c>

#include "sqlitefileinfo.h"
#include <limits.h>
#include <stdint.h>

#if SQLITE_OS_WIN
/* 日期：2026-11-08；从SQLite实际持有的句柄查询128位身份与分配量，不重新按名称打开文件。 */
static int duktoWindowsFileInfo(HANDLE handle, DuktoSqliteFileInfo *info) {
    FILE_ID_INFO identity;
    FILE_STANDARD_INFO standard;
    if (GetFileType(handle) != FILE_TYPE_DISK ||
        !GetFileInformationByHandleEx(handle, FileIdInfo, &identity, sizeof(identity)) ||
        !GetFileInformationByHandleEx(handle, FileStandardInfo, &standard, sizeof(standard)) ||
        standard.Directory || standard.EndOfFile.QuadPart < 0 ||
        standard.AllocationSize.QuadPart < 0) {
        return SQLITE_IOERR_FSTAT;
    }
    info->kind = 1;
    info->platform = 2;
    info->volume = identity.VolumeSerialNumber;
    memcpy(info->identity, identity.FileId.Identifier, sizeof(info->identity));
    info->logicalBytes = standard.EndOfFile.QuadPart;
    info->allocatedBytes = standard.AllocationSize.QuadPart;
    info->links = standard.NumberOfLinks;
    return SQLITE_OK;
}
#elif SQLITE_OS_UNIX
/* 日期：2026-11-08；直接fstat已打开描述符，允许匿名临时文件的零链接计数，不增开/关闭文件。 */
static int duktoPosixFileInfo(int descriptor, DuktoSqliteFileInfo *info) {
    struct stat observed;
    sqlite3_uint64 inode;
    unsigned int index;
    if (osFstat(descriptor, &observed) != 0 || !S_ISREG(observed.st_mode) || observed.st_size < 0 ||
        observed.st_blocks < 0 ||
        (sqlite3_uint64)observed.st_blocks > (sqlite3_uint64)INT64_MAX / 512 ||
        (sqlite3_uint64)observed.st_nlink > (sqlite3_uint64)INT64_MAX) {
        return SQLITE_IOERR_FSTAT;
    }
    info->kind = 1;
    info->platform = 1;
    info->volume = (sqlite3_uint64)observed.st_dev;
    inode = (sqlite3_uint64)observed.st_ino;
    for (index = 0; index < sizeof(inode); ++index) {
        info->identity[index] = (unsigned char)(inode & 255);
        inode >>= 8;
    }
    info->logicalBytes = observed.st_size;
    info->allocatedBytes = (sqlite3_int64)observed.st_blocks * 512;
    info->links = (sqlite3_int64)observed.st_nlink;
    return SQLITE_OK;
}
#endif

/* 日期：2026-11-08；仅识别本引擎原生方法表，所属连接保证pShm寿命，共享节点字段在原互斥内读取。 */
int duktoSqliteNativeFileInfo(sqlite3_file *file, int sharedMemory, DuktoSqliteFileInfo *info) {
    int result = SQLITE_NOTFOUND;
    if (!info) {
        return SQLITE_MISUSE;
    }
    memset(info, 0, sizeof(*info));
    if (!file || !file->pMethods || (sharedMemory != 0 && sharedMemory != 1)) {
        return SQLITE_MISUSE;
    }
#if SQLITE_OS_WIN
    if (file->pMethods->xFileControl != winFileControl) {
        return SQLITE_NOTFOUND;
    }
    if (!sharedMemory) {
        result = duktoWindowsFileInfo(((winFile *)file)->h, info);
    }
#ifndef SQLITE_OMIT_WAL
    else {
        winShm *shared = ((winFile *)file)->pShm;
        if (!shared) {
            return SQLITE_OK;
        }
        sqlite3_mutex_enter(shared->pShmNode->mutex);
        result = duktoWindowsFileInfo(shared->pShmNode->hSharedShm, info);
        if (result == SQLITE_OK) {
            info->mappedFileBytes =
                (sqlite3_int64)shared->pShmNode->nRegion * shared->pShmNode->szRegion;
        }
        sqlite3_mutex_leave(shared->pShmNode->mutex);
    }
#endif
#elif SQLITE_OS_UNIX
    if (file->pMethods->xFileControl != unixFileControl) {
        return SQLITE_NOTFOUND;
    }
    if (!sharedMemory) {
        result = duktoPosixFileInfo(((unixFile *)file)->h, info);
    }
#ifndef SQLITE_OMIT_WAL
    else {
        unixShm *shared = ((unixFile *)file)->pShm;
        if (!shared) {
            return SQLITE_OK;
        }
        sqlite3_mutex_enter(shared->pShmNode->pShmMutex);
        if (shared->pShmNode->hShm >= 0) {
            result = duktoPosixFileInfo(shared->pShmNode->hShm, info);
        } else {
            info->kind = 2;
            result = SQLITE_OK;
        }
        if (result == SQLITE_OK) {
            info->mappedFileBytes =
                (sqlite3_int64)shared->pShmNode->nRegion * shared->pShmNode->szRegion;
        }
        sqlite3_mutex_leave(shared->pShmNode->pShmMutex);
    }
#endif
#else
    (void)sharedMemory;
#endif
    if (result != SQLITE_OK) {
        memset(info, 0, sizeof(*info));
    }
    return result;
}

/* 日期：2026-11-08；POSIX与原unixShmMap采用相同页分组，Windows按实际文件扩展长度计算。 */
int duktoSqliteSharedMemoryExtent(int page, int pageSize, sqlite3_int64 *bytes) {
    sqlite3_int64 regions = 1;
    sqlite3_int64 count;
    if (!bytes) {
        return SQLITE_MISUSE;
    }
    *bytes = 0;
    if (page < 0 || pageSize <= 0) {
        return SQLITE_IOERR_SHMMAP;
    }
#if SQLITE_OS_UNIX && !defined(SQLITE_OMIT_WAL)
    regions = unixShmRegionPerMap();
#elif !SQLITE_OS_WIN
    return SQLITE_NOTFOUND;
#endif
    if (regions <= 0 || (sqlite3_int64)page > INT_MAX - regions) {
        return SQLITE_IOERR_SHMMAP;
    }
    count = (((sqlite3_int64)page + regions) / regions) * regions;
#if SQLITE_OS_UNIX
    /* 日期：2026-11-08；固定unixShmNode的nRegion为u16，过大映射不能截断为小计数。 */
    if (count > UINT16_MAX) {
        return SQLITE_IOERR_SHMMAP;
    }
#endif
    if (count > INT64_MAX / pageSize) {
        return SQLITE_IOERR_SHMMAP;
    }
    *bytes = count * pageSize;
    return SQLITE_OK;
}
