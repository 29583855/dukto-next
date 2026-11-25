#import <Foundation/Foundation.h>

// 日期：2026-11-25；主应用与扩展通过单槽App Group快照交换，不共享身份与私钥目录。
@interface DNShareInbox : NSObject
@property(nonatomic, readonly) NSURL *root;
// 日期：2026-11-25；生产入口必须取得签名授予的App Group，不退回公共目录。
+ (instancetype)sharedInbox;
// 日期：2026-11-25；指定私有根供原生合同测试，生产入口始终使用App Group。
- (instancetype)initWithRoot:(NSURL *)root;
// 日期：2026-11-25；非阻塞跨进程锁，调用者不在主线程等待其它进程。
- (int)lock;
// 日期：2026-11-25；释放已取得的跨进程锁。
- (void)unlock:(int)descriptor;
// 日期：2026-11-25；读取有界且经过路径检查的待处理快照，返回UUID、文本和文件URL。
- (NSDictionary *)snapshot:(NSError **)error;
// 日期：2026-11-25；将完整的私有临时目录原子提交，已有单槽时拒绝覆盖。
- (BOOL)commit:(NSURL *)directory
         names:(NSArray<NSString *> *)names
          text:(NSString *)text
         error:(NSError **)error;
// 日期：2026-11-25；只操作对应UUID，分别清除文字/文件；不删除系统源文件。
- (BOOL)consume:(NSString *)identifier files:(BOOL)files text:(BOOL)text error:(NSError **)error;
@end
