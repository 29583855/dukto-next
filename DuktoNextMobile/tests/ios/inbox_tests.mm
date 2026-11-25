#import "Inbox.h"
#include <cstdio>
#include <cstdlib>

// 日期：2026-11-25；失败立即终止原生合同门禁，不以断言编译开关跳过验证。
static void check(BOOL ok, const char *message) {
    if (!ok) {
        fprintf(stderr, "FAIL: %s\n", message);
        exit(1);
    }
}
// 日期：2026-11-25；在隔离目录创建实际文件，不依赖Apple签名或真实App Group授权。
static NSURL *stage(DNShareInbox *inbox, NSString *name) {
    NSURL *directory = [inbox.root
        URLByAppendingPathComponent:[@"staging-" stringByAppendingString:NSUUID.UUID.UUIDString]];
    check([NSFileManager.defaultManager createDirectoryAtURL:directory
                                 withIntermediateDirectories:NO
                                                  attributes:nil
                                                       error:nil],
          "create stage");
    if (name)
        check([[@"sample文件" dataUsingEncoding:NSUTF8StringEncoding]
                  writeToURL:[directory URLByAppendingPathComponent:name]
                     options:0
                       error:nil],
              "write file");
    return directory;
}
// 日期：2026-11-25；覆盖真实原子提交/单槽/分项消费、重启、锁、损坏、配额与软链接拒绝。
int main() {
    @autoreleasepool {
        NSURL *root =
            [NSURL fileURLWithPath:[NSTemporaryDirectory()
                                       stringByAppendingPathComponent:NSUUID.UUID.UUIDString]
                       isDirectory:YES];
        DNShareInbox *inbox = [[DNShareInbox alloc] initWithRoot:root];
        NSError *error = nil;
        check([[inbox snapshot:&error] count] == 0 && !error, "empty slot");
        NSURL *directory = stage(inbox, @"中文.txt");
        check([inbox commit:directory names:@[ @"中文.txt" ] text:@"hello 中文" error:&error],
              "mixed commit");
        NSDictionary *first = [inbox snapshot:&error];
        check([first[@"urls"] count] == 1 && [first[@"text"] isEqualToString:@"hello 中文"],
              "mixed snapshot");
        DNShareInbox *restarted = [[DNShareInbox alloc] initWithRoot:root];
        check([[[restarted snapshot:&error] objectForKey:@"id"] isEqualToString:first[@"id"]],
              "restart snapshot");
        check(![inbox commit:stage(inbox, nil) names:@[] text:@"replace" error:&error],
              "reject slot replacement");
        check(![inbox consume:NSUUID.UUID.UUIDString files:YES text:YES error:&error],
              "reject wrong UUID");
        check([inbox consume:first[@"id"] files:NO text:YES error:&error], "consume text");
        NSDictionary *remaining = [inbox snapshot:&error];
        check([remaining[@"text"] length] == 0 && [remaining[@"urls"] count] == 1,
              "files retained");
        int fd = [inbox lock];
        check(fd >= 0, "lock acquisition");
        error = nil;
        check(![restarted snapshot:&error] && error, "cross-handle lock exclusion");
        [inbox unlock:fd];
        check([inbox consume:first[@"id"] files:YES text:NO error:&error], "consume last files");
        check([[inbox snapshot:nil] count] == 0, "slot removed");
        check(![inbox commit:stage(inbox, @"manifest.json")
                       names:@[ @"manifest.json" ]
                        text:@""
                       error:&error],
              "reserved metadata name");
        NSMutableString *over = [NSMutableString string];
        for (int i = 0; i < 87382; i++)
            [over appendString:@"中"];
        check(![inbox commit:stage(inbox, nil) names:@[] text:over error:&error], "UTF8 quota");
        directory = stage(inbox, nil);
        check([NSFileManager.defaultManager
                  createSymbolicLinkAtPath:[directory URLByAppendingPathComponent:@"link.txt"].path
                       withDestinationPath:@"/etc/hosts"
                                     error:nil],
              "create symlink fixture");
        check(![inbox commit:directory names:@[ @"link.txt" ] text:@"" error:&error],
              "reject symlink");
        check([inbox commit:stage(inbox, nil) names:@[] text:@"text only" error:&error],
              "text-only commit");
        NSURL *manifest = [[root URLByAppendingPathComponent:@"pending"]
            URLByAppendingPathComponent:@"manifest.json"];
        check([[@"{\"id\":null,\"text\":[],\"names\":false}" dataUsingEncoding:NSUTF8StringEncoding]
                  writeToURL:manifest
                     options:NSDataWritingAtomic
                       error:nil],
              "corrupt manifest");
        error = nil;
        check(![inbox snapshot:&error] && error, "corrupt snapshot rejected");
        check(![inbox consume:NSUUID.UUID.UUIDString files:YES text:YES error:&error],
              "corrupt consume rejected");
        check([NSFileManager.defaultManager removeItemAtURL:root error:nil], "cleanup fixture");
        puts("iOS inbox native contracts passed: atomic mixed/text slot, restart, locks, "
             "consumption, UUID, quotas, metadata corruption and symlink rejection");
    }
    return 0;
}
