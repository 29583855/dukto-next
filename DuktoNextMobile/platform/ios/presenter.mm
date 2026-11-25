#import "presenter.h"

namespace {
// 日期：2026-11-25；仅在可见主窗口定位最上层控制器，不使用隐藏或无根控制器的窗口。
UIViewController *topPresenter(UIWindow *window) {
    if (!window.isKeyWindow || window.isHidden || window.alpha <= 0 || !window.rootViewController)
        return nil;
    UIViewController *controller = window.rootViewController;
    while (controller.presentedViewController &&
           !controller.presentedViewController.isBeingDismissed)
        controller = controller.presentedViewController;
    return controller;
}
} // namespace

// 日期：2026-11-25；Qt5.15创建未关联UIScene的UIWindow，必须在主线程前台提供受控回退。
UIViewController *DuktoActivePresenter() {
    UIApplication *application = UIApplication.sharedApplication;
    if (!NSThread.isMainThread || application.applicationState != UIApplicationStateActive)
        return nil;
    for (UIScene *scene in application.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class] ||
            scene.activationState != UISceneActivationStateForegroundActive)
            continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows) {
            UIViewController *controller = topPresenter(window);
            if (controller)
                return controller;
        }
    }
    // 日期：2026-11-25；仅遍历无Scene的传统窗口，避免把后台Scene窗口误当成前台。
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    for (UIWindow *window in application.windows) {
#pragma clang diagnostic pop
        if (window.windowScene)
            continue;
        UIViewController *controller = topPresenter(window);
        if (controller)
            return controller;
    }
    return nil;
}
