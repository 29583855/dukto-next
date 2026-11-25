#include "platformfiles.h"
#include "importstore.h"

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QDirIterator>
#include <QFile>
#include <QFileInfo>
#include <QStandardPaths>
#import <UIKit/UIKit.h>
#import <UniformTypeIdentifiers/UniformTypeIdentifiers.h>
#include <atomic>
#include <memory>

namespace {
std::shared_ptr<std::atomic_bool> importCancellation;
// 日期：2026-11-25；在协调读取期间复制快照，拒绝符号链接，保留提供器安全作用域至读取完成。
bool copyTree(ImportStore &store, const QString &path, const QString &relative, QString &error,
              const std::shared_ptr<std::atomic_bool> &cancellation) {
    if (cancellation->load()) {
        error = QStringLiteral("已取消导入");
        return false;
    }
    const QFileInfo before(path);
    if (before.isSymLink() || !before.exists()) {
        error = QStringLiteral("所选文件已消失或为符号链接");
        return false;
    }
    if (before.isDir()) {
        if (!store.directory(relative)) {
            error = store.error();
            return false;
        }
        QDirIterator iterator(path, QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden |
                                        QDir::System);
        while (iterator.hasNext()) {
            iterator.next();
            if (!copyTree(store, iterator.filePath(), relative + '/' + iterator.fileName(), error,
                          cancellation))
                return false;
        }
        return true;
    }
    if (!before.isFile()) {
        error = QStringLiteral("仅支持普通文件与目录");
        return false;
    }
    QFile input(path);
    if (!input.open(QIODevice::ReadOnly) ||
        !store.copy(input, relative, before.size(),
                    [cancellation] { return cancellation->load(); })) {
        error = store.error().isEmpty() ? input.errorString() : store.error();
        return false;
    }
    const QFileInfo after(path);
    if (after.size() != before.size() || after.lastModified() != before.lastModified()) {
        error = QStringLiteral("导入期间文件发生变化，请重新选择");
        return false;
    }
    return true;
}

// 日期：2026-11-25；从活动窗口找到展示控制器，避免使用旧keyWindow接口及后台窗口。
UIViewController *presenter() {
    for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
        if (![scene isKindOfClass:UIWindowScene.class] ||
            scene.activationState != UISceneActivationStateForegroundActive)
            continue;
        for (UIWindow *window in ((UIWindowScene *)scene).windows) {
            if (!window.isKeyWindow)
                continue;
            UIViewController *controller = window.rootViewController;
            while (controller.presentedViewController)
                controller = controller.presentedViewController;
            return controller;
        }
    }
    return nil;
}
} // namespace

@interface DuktoDocumentPicker : NSObject <UIDocumentPickerDelegate> {
  @public
    mobile::FileResult result;
    bool exporting;
    bool folder;
    QString exportPath;
}
@property(nonatomic, strong) UIDocumentPickerViewController *controller;
@end

static DuktoDocumentPicker *activePicker;

@implementation DuktoDocumentPicker
// 日期：2026-11-25；取消仅关闭选择器，不生成空任务或假成功记录。
- (void)documentPickerWasCancelled:(UIDocumentPickerViewController *)controller {
    Q_UNUSED(controller);
    auto callback = result;
    result = {};
    activePicker = nil;
    if (callback)
        callback({}, QString());
}

// 日期：2026-11-25；提供器读取在后台协调，回调主线程之前完成有限沙箱事务。
- (void)documentPicker:(UIDocumentPickerViewController *)controller
    didPickDocumentsAtURLs:(NSArray<NSURL *> *)urls {
    Q_UNUSED(controller);
    auto callback = result;
    result = {};
    const bool wasExporting = exporting;
    const bool wantFolder = folder;
    const auto exportedPath = exportPath;
    activePicker = nil;
    if (!callback)
        return;
    if (wasExporting) {
        callback(urls.count ? QStringList{exportedPath} : QStringList(), QString());
        return;
    }
    importCancellation = std::make_shared<std::atomic_bool>(false);
    const auto cancellation = importCancellation;
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
      @autoreleasepool {
          const auto root = QDir(QStandardPaths::writableLocation(QStandardPaths::AppDataLocation))
                                .filePath(QStringLiteral("imports"));
          QString error;
          QStringList names;
          if (!QDir().mkpath(root))
              error = QStringLiteral("无法创建私有导入目录");
          ImportStore store(root, ImportStore::Limits());
          if (urls.count > 512 || urls.count == 0)
              error = QStringLiteral("未选择文档或超过512项限制");
          for (NSURL *url in urls) {
              if (!error.isEmpty())
                  break;
              const bool scoped = [url startAccessingSecurityScopedResource];
              NSFileCoordinator *coordinator =
                  [[NSFileCoordinator alloc] initWithFilePresenter:nil];
              NSError *coordinationError = nil;
              ImportStore *storePointer = &store;
              __block QString copyError;
              __block QString name;
              [coordinator coordinateReadingItemAtURL:url
                                              options:0
                                                error:&coordinationError
                                           byAccessor:^(NSURL *coordinatedURL) {
                                             const QString path =
                                                 QString::fromUtf8(coordinatedURL.path.UTF8String);
                                             const QFileInfo info(path);
                                             name = info.fileName();
                                             if (info.isDir() != wantFolder)
                                                 copyError =
                                                     QStringLiteral("请选择对应类型的文件或文件夹");
                                             else
                                                 copyTree(*storePointer, path, name, copyError,
                                                          cancellation);
                                           }];
              if (scoped)
                  [url stopAccessingSecurityScopedResource];
              if (coordinationError)
                  error = QString::fromUtf8(coordinationError.localizedDescription.UTF8String);
              else if (!copyError.isEmpty())
                  error = copyError;
              else
                  names.append(name);
          }
          const auto path = error.isEmpty() ? store.commit() : QString();
          QStringList paths;
          if (path.isEmpty() && error.isEmpty())
              error = store.error();
          for (const auto &name : names) {
              if (!path.isEmpty())
                  paths.append(QDir(path).filePath(name));
          }
          QMetaObject::invokeMethod(
              QCoreApplication::instance(), [callback, paths, error] { callback(paths, error); },
              Qt::QueuedConnection);
      }
    });
}
@end

// 日期：2026-11-25；iOS原生文档选择器授予选中范围，云端下载及授权错误由协调器报告。
void mobile::selectDocuments(bool folder, FileResult done) {
    UIViewController *host = presenter();
    if (!host || activePicker) {
        done({}, QStringLiteral("请回到前台并关闭其他文件选择器"));
        return;
    }
    activePicker = [[DuktoDocumentPicker alloc] init];
    activePicker->result = done;
    activePicker->exporting = false;
    activePicker->folder = folder;
    activePicker.controller = [[UIDocumentPickerViewController alloc]
        initForOpeningContentTypes:@[ folder ? UTTypeFolder : UTTypeItem ]
                            asCopy:NO];
    activePicker.controller.allowsMultipleSelection = !folder;
    activePicker.controller.delegate = activePicker;
    [host presentViewController:activePicker.controller animated:YES completion:nil];
}

// 日期：2026-11-25；系统导出在完成回调后才显示成功，不把沙箱路径当作客户可见位置。
void mobile::exportDocument(const QString &path, FileResult done) {
    UIViewController *host = presenter();
    if (!host || activePicker || !QFileInfo::exists(path)) {
        done({}, QStringLiteral("文件不存在或无法显示系统导出界面"));
        return;
    }
    NSURL *url = [NSURL fileURLWithPath:[NSString stringWithUTF8String:path.toUtf8().constData()]];
    activePicker = [[DuktoDocumentPicker alloc] init];
    activePicker->result = done;
    activePicker->exporting = true;
    activePicker->exportPath = path;
    activePicker.controller = [[UIDocumentPickerViewController alloc] initForExportingURLs:@[ url ]
                                                                                    asCopy:YES];
    activePicker.controller.delegate = activePicker;
    [host presentViewController:activePicker.controller animated:YES completion:nil];
}

// 日期：2026-11-25；释放原生选择器的回调并关闭界面，已开始的协调读取须自行收尾。
void mobile::cancelDocumentPicker() {
    if (importCancellation)
        importCancellation->store(true);
    if (activePicker) {
        activePicker->result = {};
        [activePicker.controller dismissViewControllerAnimated:YES completion:nil];
        activePicker = nil;
    }
}

namespace {
UIBackgroundTaskIdentifier cleanupTask = UIBackgroundTaskInvalid;
}
// 日期：2026-11-25；iOS不提供Android式后台传输服务。
bool mobile::setBackgroundTransfer(bool) {
    return false;
}
// 日期：2026-11-25；iOS不宣称持续后台监听资格。
bool mobile::backgroundTransferAlive() {
    return false;
}
// 日期：2026-11-25；iOS任务取消由宿主切入后台触发。
bool mobile::takeBackgroundStop() {
    return false;
}
// 日期：2026-11-25；在取消及检查点落盘前申请有限系统时间，过期立即归还。
void mobile::beginBackgroundCleanup() {
    void (^begin)(void) = ^{
      if (cleanupTask != UIBackgroundTaskInvalid)
          return;
      cleanupTask = [UIApplication.sharedApplication beginBackgroundTaskWithName:@"DuktoCheckpoint"
                                                               expirationHandler:^{
                                                                 mobile::endBackgroundCleanup();
                                                               }];
    };
    if (NSThread.isMainThread)
        begin();
    else
        dispatch_sync(dispatch_get_main_queue(), begin);
}
// 日期：2026-11-25；所有UIKit后台任务操作在主线程，重复归还无副作用。
void mobile::endBackgroundCleanup() {
    void (^end)(void) = ^{
      if (cleanupTask == UIBackgroundTaskInvalid)
          return;
      const auto task = cleanupTask;
      cleanupTask = UIBackgroundTaskInvalid;
      [UIApplication.sharedApplication endBackgroundTask:task];
    };
    if (NSThread.isMainThread)
        end();
    else
        dispatch_async(dispatch_get_main_queue(), end);
}
