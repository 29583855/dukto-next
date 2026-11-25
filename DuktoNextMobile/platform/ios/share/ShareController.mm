#import "Inbox.h"
#import <UIKit/UIKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <fcntl.h>
#include <sys/file.h>
#include <sys/statvfs.h>
#include <unistd.h>

@interface DuktoShareController : UIViewController
@property(nonatomic) UILabel *status;
@property(nonatomic) UIButton *save;
@property(nonatomic) NSArray<NSItemProvider *> *providers;
@property(nonatomic) NSMutableArray<NSString *> *names;
@property(nonatomic) NSMutableString *text;
@property(nonatomic) DNShareInbox *inbox;
@property(nonatomic) NSURL *staging;
@property(nonatomic) NSUInteger index;
@property(nonatomic) unsigned long long bytes;
@property(atomic) BOOL cancelled;
@property(nonatomic) int producerLock;
@end

@implementation DuktoShareController
// 日期：2026-11-25；扩展取消或系统销毁后归还进程锁，下次启动可清理遗留暂存。
- (void)dealloc {
    if (_producerLock >= 0)
        close(_producerLock);
}
// 日期：2026-11-25；原生扩展只保存待处理快照，联网和目标选择留给主应用。
- (void)viewDidLoad {
    [super viewDidLoad];
    self.producerLock = -1;
    self.view.backgroundColor = UIColor.systemBackgroundColor;
    self.status = [[UILabel alloc] init];
    self.status.numberOfLines = 0;
    self.status.text =
        @"将文件或文字保存到待发送区，然后打开Dukto Next选择接收设备。不会自动发送。";
    self.save = [UIButton buttonWithType:UIButtonTypeSystem];
    [self.save setTitle:@"保存到Dukto Next" forState:UIControlStateNormal];
    [self.save addTarget:self
                  action:@selector(beginImport)
        forControlEvents:UIControlEventTouchUpInside];
    UIButton *cancel = [UIButton buttonWithType:UIButtonTypeSystem];
    [cancel setTitle:@"取消" forState:UIControlStateNormal];
    [cancel addTarget:self
                  action:@selector(cancelImport)
        forControlEvents:UIControlEventTouchUpInside];
    UIStackView *stack =
        [[UIStackView alloc] initWithArrangedSubviews:@[ self.status, self.save, cancel ]];
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 24;
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    [self.view addSubview:stack];
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.leadingAnchor
                                            constant:24],
        [stack.trailingAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.trailingAnchor
                                             constant:-24],
        [stack.topAnchor constraintEqualToAnchor:self.view.safeAreaLayoutGuide.topAnchor
                                        constant:24]
    ]];
    self.preferredContentSize = CGSizeMake(420, 320);
}
// 日期：2026-11-25；取消仅清理本次扩展临时副本；提供器回调会看到原子取消状态。
- (void)cancelImport {
    self.cancelled = YES;
    // 日期：2026-11-25；进行中的回调负责收尾，系统终止后遗留暂存由下一次扩展启动清理。
    [self.extensionContext cancelRequestWithError:[NSError errorWithDomain:NSCocoaErrorDomain
                                                                      code:NSUserCancelledError
                                                                  userInfo:nil]];
}
// 日期：2026-11-25；使用明确可见错误，已有单槽时不能悄悄替换旧分享。
- (void)failed:(NSString *)message {
    self.status.text = message.length ? message : @"读取分享失败，请从源应用重新分享";
    self.save.enabled = NO;
    if (self.staging)
        [NSFileManager.defaultManager removeItemAtURL:self.staging error:nil];
    if (self.producerLock >= 0) {
        close(self.producerLock);
        self.producerLock = -1;
    }
}
// 日期：2026-11-25；锁内清理旧扩展暂存并保留待处理槽，总提供器最多512个。
- (void)beginImport {
    self.save.enabled = NO;
    self.inbox = DNShareInbox.sharedInbox;
    if (!self.inbox) {
        [self failed:@"App Group未获授权，请使用主应用与扩展均正确签名的版本"];
        return;
    }
    self.producerLock =
        open([[self.inbox.root
                  URLByAppendingPathComponent:@"producer.lock"].path fileSystemRepresentation],
             O_CREAT | O_RDWR | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (self.producerLock < 0 || flock(self.producerLock, LOCK_EX | LOCK_NB)) {
        [self failed:@"另一个分享正在处理，请稍后重试"];
        return;
    }
    NSError *error = nil;
    NSDictionary *pending = [self.inbox snapshot:&error];
    if (!pending || [pending count]) {
        [self failed:error.localizedDescription ?: @"已有待处理分享，请先在Dukto Next发送或丢弃"];
        return;
    }
    NSMutableArray *providers = [NSMutableArray array];
    self.text = [NSMutableString string];
    self.names = [NSMutableArray array];
    for (NSExtensionItem *item in self.extensionContext.inputItems) {
        for (NSItemProvider *provider in item.attachments) {
            if (providers.count >= 512) {
                [self failed:@"一次最多分享512项"];
                return;
            }
            [providers addObject:provider];
        }
        if (!item.attachments.count && item.attributedContentText.length)
            [self.text appendString:item.attributedContentText.string];
    }
    if ([self.text lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 262144) {
        [self failed:@"分享文字超过256KiB"];
        return;
    }
    int fd = [self.inbox lock];
    if (fd < 0) {
        [self failed:@"另一个分享正在处理，请稍后重试"];
        return;
    }
    for (NSURL *url in [NSFileManager.defaultManager contentsOfDirectoryAtURL:self.inbox.root
                                                   includingPropertiesForKeys:nil
                                                                      options:0
                                                                        error:nil]) {
        if ([url.lastPathComponent hasPrefix:@"staging-"])
            [NSFileManager.defaultManager removeItemAtURL:url error:nil];
    }
    self.staging = [self.inbox.root
        URLByAppendingPathComponent:[@"staging-" stringByAppendingString:NSUUID.UUID.UUIDString]
                        isDirectory:YES];
    BOOL created = [NSFileManager.defaultManager createDirectoryAtURL:self.staging
                                          withIntermediateDirectories:NO
                                                           attributes:nil
                                                                error:&error];
    [self.inbox unlock:fd];
    if (!created) {
        [self failed:error.localizedDescription];
        return;
    }
    self.providers = providers;
    self.index = 0;
    self.bytes = 0;
    [self nextProvider];
}
// 日期：2026-11-25；固定1MiB缓冲复制普通文件；16GiB全批预算、空间保留及源变化检测。
- (BOOL)copyFile:(NSURL *)url provider:(NSItemProvider *)provider error:(NSError **)error {
    NSNumber *regular = nil, *symbolic = nil;
    [url getResourceValue:&regular forKey:NSURLIsRegularFileKey error:error];
    [url getResourceValue:&symbolic forKey:NSURLIsSymbolicLinkKey error:error];
    if (!regular.boolValue || symbolic.boolValue) {
        if (error)
            *error = [NSError errorWithDomain:@"DuktoShare"
                                         code:2
                                     userInfo:@{
                                         NSLocalizedDescriptionKey :
                                             @"分享扩展只接受普通文件；文件夹请在主应用中选择"
                                     }];
        return NO;
    }
    NSString *name = provider.suggestedName.length ? provider.suggestedName.lastPathComponent
                                                   : url.lastPathComponent;
    if (!name.length || [name hasPrefix:@"."] ||
        [name rangeOfCharacterFromSet:[NSCharacterSet characterSetWithCharactersInString:@"/\\:"]]
                .location != NSNotFound ||
        [name rangeOfCharacterFromSet:NSCharacterSet.controlCharacterSet].location != NSNotFound ||
        [name caseInsensitiveCompare:@"manifest.json"] == NSOrderedSame || name.length > 240)
        return NO;
    // 日期：2026-11-25；保留提供器实际扩展名，禁止同名覆盖；用户可回主应用逐项选择。
    if (!name.pathExtension.length && url.pathExtension.length)
        name = [name stringByAppendingPathExtension:url.pathExtension];
    for (NSString *old in self.names)
        if ([old caseInsensitiveCompare:name] == NSOrderedSame)
            return NO;
    NSDictionary *before = [NSFileManager.defaultManager attributesOfItemAtPath:url.path
                                                                          error:error];
    unsigned long long expected = [before[NSFileSize] unsignedLongLongValue];
    if (!before || expected > 16ULL * 1024 * 1024 * 1024 - self.bytes)
        return NO;
    struct statvfs space;
    if (statvfs(self.staging.path.fileSystemRepresentation, &space) ||
        (unsigned long long)space.f_bavail * space.f_frsize < expected + 64ULL * 1024 * 1024)
        return NO;
    int input = open(url.path.fileSystemRepresentation, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    int output =
        open([[self.staging URLByAppendingPathComponent:name].path fileSystemRepresentation],
             O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
    BOOL ok = input >= 0 && output >= 0;
    NSMutableData *buffer = [NSMutableData dataWithLength:1024 * 1024];
    unsigned long long copied = 0;
    while (ok && !self.cancelled) {
        ssize_t size = read(input, buffer.mutableBytes, buffer.length);
        if (!size)
            break;
        if (size < 0 || (unsigned long long)size > expected - copied) {
            ok = NO;
            break;
        }
        ssize_t written = 0;
        while (written < size) {
            ssize_t step = write(output, (char *)buffer.bytes + written, size - written);
            if (step <= 0) {
                ok = NO;
                break;
            }
            written += step;
        }
        copied += size;
    }
    if (output >= 0) {
        if (ok && fsync(output))
            ok = NO;
        close(output);
    }
    if (input >= 0)
        close(input);
    NSDictionary *after = [NSFileManager.defaultManager attributesOfItemAtPath:url.path
                                                                         error:error];
    ok = ok && !self.cancelled && copied == expected &&
         [before[NSFileSize] isEqual:after[NSFileSize]] &&
         [before[NSFileModificationDate] isEqual:after[NSFileModificationDate]];
    if (ok) {
        self.bytes += copied;
        [self.names addObject:name];
    }
    return ok;
}
// 日期：2026-11-25；一次处理一个提供器，不将整批文件载入内存；临时URL只在提供器回调期间使用。
- (void)nextProvider {
    if (self.cancelled) {
        [self failed:@"已取消分享"];
        return;
    }
    if (self.index >= self.providers.count) {
        NSError *error = nil;
        if (![self.inbox commit:self.staging names:self.names text:self.text error:&error]) {
            [self failed:error.localizedDescription];
            return;
        }
        self.staging = nil;
        close(self.producerLock);
        self.producerLock = -1;
        [self.extensionContext completeRequestReturningItems:@[] completionHandler:nil];
        return;
    }
    self.status.text = [NSString stringWithFormat:@"正在保存 %lu/%lu，请保持此窗口打开",
                                                  (unsigned long)self.index + 1,
                                                  (unsigned long)self.providers.count];
    NSItemProvider *provider = self.providers[self.index++];
    if ([provider hasItemConformingToTypeIdentifier:UTTypePlainText.identifier]) {
        [provider
            loadItemForTypeIdentifier:UTTypePlainText.identifier
                              options:nil
                    completionHandler:^(id item, NSError *error) {
                      NSString *part = [item isKindOfClass:NSString.class] ? item : nil;
                      dispatch_async(dispatch_get_main_queue(), ^{
                        if (!part || error ||
                            [self.text lengthOfBytesUsingEncoding:NSUTF8StringEncoding] +
                                    [part lengthOfBytesUsingEncoding:NSUTF8StringEncoding] + 1 >
                                262144) {
                            [self failed:@"读取文字失败或文字超过256KiB"];
                            return;
                        }
                        if (self.text.length)
                            [self.text appendString:@"\n"];
                        [self.text appendString:part];
                        [self nextProvider];
                      });
                    }];
    } else {
        NSString *type = nil;
        for (NSString *candidate in provider.registeredTypeIdentifiers)
            if ([[UTType typeWithIdentifier:candidate] conformsToType:UTTypeData]) {
                type = candidate;
                break;
            }
        if (!type) {
            [self failed:@"此内容无法导出普通文件，请在源应用中先保存到文件"];
            return;
        }
        [provider loadFileRepresentationForTypeIdentifier:type
                                        completionHandler:^(NSURL *url, NSError *error) {
                                          BOOL scoped = [url startAccessingSecurityScopedResource];
                                          NSError *failure = error;
                                          BOOL ok = url && !error &&
                                                    [self copyFile:url
                                                          provider:provider
                                                             error:&failure];
                                          if (scoped)
                                              [url stopAccessingSecurityScopedResource];
                                          dispatch_async(dispatch_get_main_queue(), ^{
                                            if (!ok) {
                                                [self failed:failure.localizedDescription
                                                                 ?: @"文件不可读、重名、空间不足或"
                                                                    @"超出16GiB预算"];
                                                return;
                                            }
                                            [self nextProvider];
                                          });
                                        }];
    }
}
@end
