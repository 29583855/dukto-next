"""日期：2026-11-05；仅供独立小型挂载点的真实ENOSPC注入，固定缓冲且不填充宿主系统卷。"""

import errno
import os
import sys
import time


# 日期：2026-11-05；APFS用原生物理空间预留避免慢填充先触发帧超时，逐级消耗尾部空闲块。
def reserve_apfs(output, capacity):
    import fcntl
    import struct

    reserved = 0
    observed = False
    for chunk in (4 * 1024**2, 1024**2, 64 * 1024, 4096):
        while reserved <= capacity:
            # 日期：2026-11-05；Darwin fstore_t固定32字节，ALL要求完整分配；偏移从物理EOF计算。
            store = struct.pack('=Iiqqq', 0x04, 3, 0, chunk, 0)
            try:
                result = fcntl.fcntl(output.fileno(), 42, store)
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
                observed = True
                break
            allocated = struct.unpack('=Iiqqq', result)[4]
            assert chunk <= allocated <= capacity, (chunk, allocated, capacity)
            reserved += allocated
            os.ftruncate(output.fileno(), reserved)
        else:
            raise AssertionError('Dedicated APFS filesystem was not exhausted within capacity')
    status = os.fstat(output.fileno())
    assert observed and status.st_blocks > 0
    return {'fillerBytes': reserved, 'physicalBytes': status.st_blocks * 512,
            'method': 'Darwin F_PREALLOCATE physical reservation', 'kernelError': 'ENOSPC'}


# 日期：2026-11-05；调用方先验证独立挂载；本函数只新建自有filler并要求精确容量及真实内核ENOSPC。
def exhaust(path, capacity):
    filesystem = os.statvfs(path.parent)
    assert filesystem.f_blocks * filesystem.f_frsize == capacity
    assert 4 * 1024**2 <= capacity <= 512 * 1024**2
    started = time.monotonic()
    with path.open('xb', buffering=0) as output:
        if sys.platform == 'darwin':
            result = reserve_apfs(output, capacity)
        else:
            written = 0
            try:
                while written <= capacity:
                    written += output.write(b'f' * (64 * 1024))
            except OSError as error:
                if error.errno != errno.ENOSPC:
                    raise
                result = {'fillerBytes': written, 'physicalBytes': os.fstat(output.fileno()).st_blocks * 512,
                          'method': 'bounded writes on dedicated filesystem', 'kernelError': 'ENOSPC'}
            else:
                raise AssertionError('Dedicated filesystem was not exhausted within capacity')
    result['elapsedSeconds'] = round(time.monotonic() - started, 3)
    return result
