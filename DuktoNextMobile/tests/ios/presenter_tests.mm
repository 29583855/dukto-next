#import "presenter.h"

@interface PresenterTestDelegate : UIResponder <UIApplicationDelegate>
@property(nonatomic, strong) UIWindow *window;
@property(nonatomic) BOOL exercised;
@end

@implementation PresenterTestDelegate
// 日期：2026-11-25；与Qt5一致创建未关联Scene的真实UIKit窗口。
- (BOOL)application:(UIApplication *)application
    didFinishLaunchingWithOptions:(NSDictionary *)options {
    (void)application;
    (void)options;
    self.window = [[UIWindow alloc] initWithFrame:UIScreen.mainScreen.bounds];
    self.window.rootViewController = [[UIViewController alloc] init];
    self.window.rootViewController.view.backgroundColor = UIColor.systemBackgroundColor;
    [self.window makeKeyAndVisible];
    return YES;
}

// 日期：2026-11-25；将实际运行结果写入沙箱，CI必须读取此文件才能通过。
- (void)record:(BOOL)passed reason:(NSString *)reason {
    NSURL *documents = [NSFileManager.defaultManager URLsForDirectory:NSDocumentDirectory
                                                            inDomains:NSUserDomainMask]
                           .firstObject;
    NSDictionary *receipt = @{
        @"passed" : @(passed),
        @"reason" : reason,
        @"systemVersion" : UIDevice.currentDevice.systemVersion,
        @"sceneCount" : @(UIApplication.sharedApplication.connectedScenes.count),
        @"legacyWindow" : @(self.window.windowScene == nil),
        @"deviceTest" : @NO
    };
    NSData *data = [NSJSONSerialization dataWithJSONObject:receipt
                                                   options:NSJSONWritingPrettyPrinted
                                                     error:nil];
    [data writeToURL:[documents URLByAppendingPathComponent:@"presenter-test.json"] atomically:YES];
}

// 日期：2026-11-25；验证无Scene窗口、模态顶层、关闭后恢复及隐藏窗口拒绝。
- (void)applicationDidBecomeActive:(UIApplication *)application {
    (void)application;
    if (self.exercised)
        return;
    self.exercised = YES;
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 2), dispatch_get_main_queue(), ^{
      if (DuktoActivePresenter() != self.window.rootViewController) {
          [self record:NO reason:@"传统窗口未找到根展示控制器"];
          return;
      }
      UIViewController *modal = [[UIViewController alloc] init];
      [self.window.rootViewController
          presentViewController:modal
                       animated:NO
                     completion:^{
                       if (DuktoActivePresenter() != modal) {
                           [self record:NO reason:@"未定位已展示的模态控制器"];
                           return;
                       }
                       [modal
                           dismissViewControllerAnimated:NO
                                              completion:^{
                                                if (DuktoActivePresenter() !=
                                                    self.window.rootViewController) {
                                                    [self record:NO
                                                          reason:@"关闭模态后未恢复根控制器"];
                                                    return;
                                                }
                                                self.window.hidden = YES;
                                                const BOOL refusedHidden =
                                                    DuktoActivePresenter() == nil;
                                                [self.window makeKeyAndVisible];
                                                [self
                                                    record:refusedHidden
                                                    reason:refusedHidden
                                                               ? @"传统窗口/模态/恢复/隐藏拒绝通过"
                                                               : @"隐藏窗口未被拒绝"];
                                              }];
                     }];
    });
}
@end

// 日期：2026-11-25；在真实iOS模拟器启动UIKit，不使用主机替身伪造窗口行为。
int main(int argc, char **argv) {
    @autoreleasepool {
        return UIApplicationMain(argc, argv, nil, NSStringFromClass(PresenterTestDelegate.class));
    }
}
