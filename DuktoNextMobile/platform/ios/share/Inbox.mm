#import "Inbox.h"
#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>

namespace {
// 日期：2026-11-25；提供可显示的有界错误，不附用户文档路径。
BOOL fail(NSError **error, NSString *message) {
    if (error)
        *error = [NSError errorWithDomain:@"DuktoShare"
                                     code:1
                                 userInfo:@{NSLocalizedDescriptionKey : message}];
    return NO;
}
// 日期：2026-11-25；跨平台名称只允许单个普通段，拒绝隐藏/控制字符及路径分隔符。
BOOL safeName(NSString *name) {
    return
        [name isKindOfClass:NSString.class] && name.length && name.length <= 240 &&
        ![name hasPrefix:@"."] && [name caseInsensitiveCompare:@"manifest.json"] != NSOrderedSame &&
        [name rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"/\\:"]]
                .location == NSNotFound &&
        [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location == NSNotFound;
}
} // namespace
@implementation DNShareInbox
// 日期：2026-11-25；缺少签名App Group时返回nil并由界面提示，禁止隐式放宽授权。
+ (instancetype)sharedInbox {
    NSURL *root = [NSFileManager.defaultManager
        containerURLForSecurityApplicationGroupIdentifier:@"group.org.duktonext.mobile"];
    return root ? [[self alloc] initWithRoot:[root URLByAppendingPathComponent:@"ShareInbox"
                                                                   isDirectory:YES]]
                : nil;
}
// 日期：2026-11-25；收件箱和锁均位于私有授权容器。
- (instancetype)initWithRoot:(NSURL *)root {
    self = [super init];
    if (self) {
        _root = root;
        if (![NSFileManager.defaultManager createDirectoryAtURL:root
                                    withIntermediateDirectories:YES
                                                     attributes:nil
                                                          error:nil])
            return nil;
    }
    return self;
}
// 日期：2026-11-25；所有发布/消费和读取共用非阻塞进程锁。
- (int)lock {
    int fd = open([[_root URLByAppendingPathComponent:@"inbox.lock"].path fileSystemRepresentation],
                  O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0)
        return -1;
    if (flock(fd, LOCK_EX | LOCK_NB) != 0) {
        close(fd);
        return -1;
    }
    return fd;
}
// 日期：2026-11-25；重复失败调用不关闭其它描述符。
- (void)unlock:(int)fd {
    if (fd >= 0) {
        flock(fd, LOCK_UN);
        close(fd);
    }
}
// 日期：2026-11-25；读取单个有界清单，根目录与每个文件禁止符号链接。
- (NSDictionary *)snapshot:(NSError **)error {
    int fd = [self lock];
    if (fd < 0) {
        fail(error, @"分享收件箱正忙，请稍后重试");
        return nil;
    }
    @try {
        NSURL *pending = [_root URLByAppendingPathComponent:@"pending" isDirectory:YES];
        NSURL *manifest = [pending URLByAppendingPathComponent:@"manifest.json"];
        NSDictionary *attributes =
            [NSFileManager.defaultManager attributesOfItemAtPath:manifest.path error:nil];
        if (!attributes)
            return @{};
        if (![attributes[NSFileType] isEqualToString:NSFileTypeRegular] ||
            [attributes[NSFileSize] unsignedLongLongValue] > 1048576) {
            fail(error, @"分享清单损坏或超限");
            return nil;
        }
        if (![[NSFileManager.defaultManager attributesOfItemAtPath:pending.path
                                                             error:nil][NSFileType]
                isEqualToString:NSFileTypeDirectory]) {
            fail(error, @"分享目录无效");
            return nil;
        }
        NSData *data = [NSData dataWithContentsOfURL:manifest options:0 error:error];
        id value = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:error] : nil;
        if (![value isKindOfClass:NSDictionary.class]) {
            fail(error, @"分享清单格式无效");
            return nil;
        }
        NSString *identifier = value[@"id"], *text = value[@"text"];
        NSArray *names = value[@"names"];
        if (![identifier isKindOfClass:NSString.class] ||
            ![[NSUUID alloc] initWithUUIDString:identifier] ||
            ![text isKindOfClass:NSString.class] ||
            [text lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 262144 ||
            ![names isKindOfClass:NSArray.class] || names.count > 512) {
            fail(error, @"分享清单内容无效");
            return nil;
        }
        NSMutableArray *urls = [NSMutableArray array];
        NSMutableSet *seen = [NSMutableSet set];
        for (NSString *name in names) {
            if (!safeName(name) || [seen containsObject:name.lowercaseString]) {
                fail(error, @"分享名称无效或重复");
                return nil;
            }
            [seen addObject:name.lowercaseString];
            NSURL *url = [pending URLByAppendingPathComponent:name];
            if (![[NSFileManager.defaultManager attributesOfItemAtPath:url.path
                                                                 error:nil][NSFileType]
                    isEqualToString:NSFileTypeRegular]) {
                fail(error, @"分享文件缺失或不是普通文件");
                return nil;
            }
            [urls addObject:url];
        }
        return @{@"id" : identifier, @"text" : text, @"names" : names, @"urls" : urls};
    } @finally {
        [self unlock:fd];
    }
}
// 日期：2026-11-25；完整复制后在同一卷原子发布，失败保留旧槽内容。
- (BOOL)commit:(NSURL *)directory
         names:(NSArray<NSString *> *)names
          text:(NSString *)text
         error:(NSError **)error {
    int fd = [self lock];
    if (fd < 0)
        return fail(error, @"分享收件箱正忙");
    @try {
        NSURL *pending = [_root URLByAppendingPathComponent:@"pending" isDirectory:YES];
        if ([NSFileManager.defaultManager fileExistsAtPath:pending.path])
            return fail(error, @"已有待处理分享，请在Dukto Next中发送或丢弃后重试");
        if (![[directory.URLByDeletingLastPathComponent URLByResolvingSymlinksInPath].path
                isEqualToString:[_root URLByResolvingSymlinksInPath].path] ||
            ![directory.lastPathComponent hasPrefix:@"staging-"])
            return fail(error, @"分享暂存目录无效");
        if (![[NSFileManager.defaultManager attributesOfItemAtPath:directory.path
                                                             error:nil][NSFileType]
                isEqualToString:NSFileTypeDirectory])
            return fail(error, @"分享暂存不是普通目录");
        if (names.count > 512 || [text lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 262144 ||
            (!names.count && !text.length))
            return fail(error, @"分享内容为空或超限");
        NSMutableSet *seen = [NSMutableSet set];
        for (NSString *name in names) {
            if (!safeName(name) || [seen containsObject:name.lowercaseString] ||
                ![[NSFileManager.defaultManager
                    attributesOfItemAtPath:[directory URLByAppendingPathComponent:name].path
                                     error:nil][NSFileType] isEqualToString:NSFileTypeRegular])
                return fail(error, @"分享文件名无效或重复");
            [seen addObject:name.lowercaseString];
        }
        NSDictionary *manifest =
            @{@"id" : NSUUID.UUID.UUIDString, @"text" : text, @"names" : names};
        NSData *data = [NSJSONSerialization dataWithJSONObject:manifest options:0 error:error];
        return data &&
               [data writeToURL:[directory URLByAppendingPathComponent:@"manifest.json"]
                        options:NSDataWritingAtomic
                          error:error] &&
               [NSFileManager.defaultManager moveItemAtURL:directory toURL:pending error:error];
    } @finally {
        [self unlock:fd];
    }
}
// 日期：2026-11-25；先原子更新清单再清理已脱离引用的文件，避免断电后误删待处理内容。
- (BOOL)consume:(NSString *)identifier files:(BOOL)files text:(BOOL)text error:(NSError **)error {
    int fd = [self lock];
    if (fd < 0)
        return fail(error, @"分享收件箱正忙");
    @try {
        NSURL *pending = [_root URLByAppendingPathComponent:@"pending" isDirectory:YES];
        NSURL *manifest = [pending URLByAppendingPathComponent:@"manifest.json"];
        NSDictionary *attributes =
            [NSFileManager.defaultManager attributesOfItemAtPath:manifest.path error:nil];
        if (![attributes[NSFileType] isEqualToString:NSFileTypeRegular] ||
            [attributes[NSFileSize] unsignedLongLongValue] > 1048576)
            return fail(error, @"分享清单损坏或超限");
        NSData *data = [NSData dataWithContentsOfURL:manifest options:0 error:error];
        id value = data ? [NSJSONSerialization JSONObjectWithData:data
                                                          options:NSJSONReadingMutableContainers
                                                            error:error]
                        : nil;
        if (![value isKindOfClass:NSMutableDictionary.class] ||
            ![value[@"id"] isKindOfClass:NSString.class] ||
            ![value[@"id"] isEqualToString:identifier] ||
            ![value[@"names"] isKindOfClass:NSArray.class] ||
            ![value[@"text"] isKindOfClass:NSString.class])
            return fail(error, @"分享已变化，请重新确认");
        if (files)
            value[@"names"] = @[];
        if (text)
            value[@"text"] = @"";
        if (![value[@"names"] count] && ![value[@"text"] length])
            return [NSFileManager.defaultManager removeItemAtURL:pending error:error];
        NSData *updated = [NSJSONSerialization dataWithJSONObject:value options:0 error:error];
        if (!updated || ![updated writeToURL:manifest options:NSDataWritingAtomic error:error])
            return NO;
        // 日期：2026-11-25；剩余文字期间暂留无引用文件，最后消费时整槽回收，避免不可信清单路径参与删除。
        return YES;
    } @finally {
        [self unlock:fd];
    }
}
@end
