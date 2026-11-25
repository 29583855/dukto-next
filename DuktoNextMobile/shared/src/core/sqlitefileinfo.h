#pragma once

#include <sqlite3.h>

#ifdef __cplusplus
extern "C" {
#endif

/* 日期：2026-11-08；固定大小的实际句柄观察，不含路径、正文或可关闭的原生句柄。 */
typedef struct DuktoSqliteFileInfo {
    /* kind：0表示本连接没有该句柄，1为磁盘普通文件，2为仅内存共享区；0不证明磁盘对象消失。 */
    int kind;
    /* platform：1为POSIX的设备/inode，2为Windows卷序号/128位文件ID。 */
    int platform;
    sqlite3_uint64 volume;
    unsigned char identity[16];
    sqlite3_int64 logicalBytes;
    sqlite3_int64 allocatedBytes;
    sqlite3_int64 links;
    /* 覆盖的共享文件范围，不等同于虚拟映射总量或实际物理分配量。 */
    sqlite3_int64 mappedFileBytes;
} DuktoSqliteFileInfo;

/* 日期：2026-11-08；只接受同引擎原生文件，调用方持有所属连接；失败不能当作零占用。 */
int duktoSqliteNativeFileInfo(sqlite3_file *file, int sharedMemory, DuktoSqliteFileInfo *info);
/* 日期：2026-11-08；按固定原生VFS的共享区分组计算实际扩展范围，拒绝64位和原生int溢出。 */
int duktoSqliteSharedMemoryExtent(int page, int pageSize, sqlite3_int64 *bytes);

#ifdef __cplusplus
}
#endif
