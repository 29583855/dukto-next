import XCTest

// 日期：2026-11-26；独立Next验收工程只操作完整Qt产品，不启动测试版控制器。
final class MobileSendTests: XCTestCase {
    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func capture(_ app: XCUIApplication, _ name: String) {
        let tree = XCTAttachment(string: app.debugDescription)
        tree.name = name + "-accessibility"
        tree.lifetime = .keepAlways
        add(tree)
        let screen = XCTAttachment(screenshot: app.screenshot())
        screen.name = name
        screen.lifetime = .keepAlways
        add(screen)
        print("MOBILE_UI_TREE " + name + "\n" + app.debugDescription)
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func dismissKeyboardTeaching(_ app: XCUIApplication) {
        let teaching = app.staticTexts[
            "Speed up your typing by sliding your finger across the letters to compose a word."
        ]
        if teaching.waitForExistence(timeout: 60) {
            capture(app, "keyboard-teaching-preview")
            let proceed = app.buttons["Continue"]
            XCTAssertTrue(proceed.waitForExistence(timeout: 5))
            XCTAssertTrue(proceed.isHittable)
            proceed.tap()
            let closed = NSPredicate(format: "exists == false")
            expectation(for: closed, evaluatedWith: teaching)
            waitForExpectations(timeout: 10)
            XCTAssertTrue(app.keyboards.firstMatch.waitForExistence(timeout: 5))
            capture(app, "keyboard-teaching-dismissed")
        }
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func tapKeyboard(_ app: XCUIApplication, _ text: String) throws {
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 5))
        for character in text {
            let value = String(character)
            let identifier = value == " " ? "space" : value
            if !keyboard.keys[identifier].exists {
                if character.isLetter {
                    if keyboard.keys["letters"].exists {
                        keyboard.keys["letters"].tap()
                    }
                    if !keyboard.keys[identifier].exists {
                        let shift = keyboard.buttons["shift"]
                        XCTAssertTrue(shift.exists, "系统键盘缺少大小写切换键：" + value)
                        shift.tap()
                    }
                } else {
                    let numbers = keyboard.keys["numbers"]
                    XCTAssertTrue(numbers.exists, "系统键盘缺少数字布局切换键：" + value)
                    numbers.tap()
                }
            }
            let key = keyboard.keys[identifier]
            XCTAssertTrue(key.waitForExistence(timeout: 3), "系统键盘缺少实际按键：" + value)
            key.tap()
        }
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func documentCell(_ app: XCUIApplication, _ label: String) -> XCUIElement {
        return app.collectionViews["File View"].cells
            .containing(.staticText, identifier: label).firstMatch
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func tapDocumentCell(_ app: XCUIApplication, _ label: String) {
        let cell = documentCell(app, label)
        XCTAssertTrue(cell.waitForExistence(timeout: 15), "系统文件界面缺少文件单元：" + label)
        XCTAssertTrue(cell.isHittable, "系统文件单元不可点击：" + label)
        cell.tap()
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func documentNavigation(_ app: XCUIApplication) -> XCUIElement {
        return app.navigationBars["FullDocumentManagerViewControllerNavigationBar"]
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func waitForDocumentPicker(_ app: XCUIApplication) {
        XCTAssertTrue(documentNavigation(app).waitForExistence(timeout: 60), "系统Files导航栏未出现")
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func tapSystemNavigationButton(_ app: XCUIApplication, _ button: XCUIElement) {
        XCTAssertTrue(button.exists)
        XCTAssertTrue(button.isEnabled)
        if button.isHittable {
            button.tap()
        } else {
            capture(app, "picker-navigation-hit-test")
            let frame = button.frame
            XCTAssertGreaterThan(frame.width, 0)
            XCTAssertGreaterThan(frame.height, 0)
            XCTAssertTrue(documentNavigation(app).frame.contains(frame))
            XCTAssertTrue(app.frame.contains(frame))
            button.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5)).tap()
        }
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func cancelSystemDocuments(_ app: XCUIApplication) {
        let navigation = documentNavigation(app)
        for level in 0..<6 {
            let cancel = navigation.buttons["Cancel"]
            let back = navigation.buttons.matching(NSPredicate(
                format: "label IN %@", ["On My iPhone", "Browse", "Back", "Dukto Next",
                                        "a-ios-io-source", "a-ios-io-export", "a-ios-directory-probe"]
            )).firstMatch
            let ready = NSPredicate { _, _ in cancel.exists || back.exists }
            expectation(for: ready, evaluatedWith: app)
            waitForExpectations(timeout: 30)
            capture(app, "picker-cancel-navigation-" + String(level))
            if cancel.exists {
                tapSystemNavigationButton(app, cancel)
                waitForDocumentPickerClosed(app)
                return
            }
            XCTAssertTrue(back.exists, "系统Files缺少可验证的返回或取消按钮")
            tapSystemNavigationButton(app, back)
        }
        XCTFail("系统Files返回六级后仍缺少取消入口")
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func waitForDocumentPickerClosed(_ app: XCUIApplication) {
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: documentNavigation(app))
        waitForExpectations(timeout: 30)
    }

    // 日期：2026-11-26；复用已验的真实系统控件操作，缺失或不可点击立即失败。
    @MainActor
    func openApplicationDocuments(_ app: XCUIApplication, _ required: String) {
        for _ in 0..<5 {
            if documentCell(app, required).exists { return }
            let application = documentCell(app, "Dukto Next")
            if application.exists && application.isHittable {
                application.tap()
                continue
            }
            var navigated = false
            for label in ["a-ios-io-source", "Dukto Next", "On My iPhone", "Browse"] {
                let back = app.navigationBars.buttons[label].firstMatch
                if back.exists && back.isHittable {
                    back.tap()
                    navigated = true
                    break
                }
            }
            if navigated { continue }
            let local = app.buttons["On My iPhone"]
            if local.exists && local.isHittable {
                local.tap()
                continue
            }
            capture(app, "storage-navigation-unavailable")
            XCTFail("系统Files无法导航到应用目录")
            return
        }
        XCTAssertTrue(documentCell(app, required).waitForExistence(timeout: 15))
    }

    // 日期：2026-11-26；从真实标签栏与屏幕尺寸确定正文区域，避免点击底部状态区后误判产品。
    @MainActor
    func serverSeek(_ app: XCUIApplication, _ element: XCUIElement) {
        let tab = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", "连接与文件")).firstMatch
        XCTAssertTrue(tab.waitForExistence(timeout: 15))
        let top = tab.frame.maxY + 16
        let bottom = app.frame.maxY - 130
        XCTAssertGreaterThan(bottom - top, 120)
        for attempt in 0..<16 {
            var upward = true
            if element.exists && !element.frame.isEmpty {
                if element.isHittable && element.frame.minY >= top && element.frame.maxY <= bottom {
                    return
                }
                upward = element.frame.minY >= top
            }
            if attempt == 15 { break }
            let x = app.frame.minX + app.frame.width * 0.75
            let high = top + 40
            let low = bottom - 30
            let origin = app.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: x, dy: upward ? low : high))
            let target = app.coordinate(withNormalizedOffset: .zero).withOffset(
                CGVector(dx: x, dy: upward ? high : low))
            origin.press(forDuration: 0.05, thenDragTo: target)
        }
        capture(app, "next-control-unreachable")
        XCTFail("服务器控件无法滚入正文安全区域：" + element.label)
    }

    // 日期：2026-11-26；参数逐键从真实键盘输入，完成键退出键盘后才继续滚动。
    @MainActor
    func serverEnter(_ app: XCUIApplication, _ label: String, _ value: String) throws {
        let field = app.textFields[label]
        serverSeek(app, field)
        XCTAssertTrue(field.isHittable)
        field.tap()
        dismissKeyboardTeaching(app)
        try tapKeyboard(app, value)
        XCTAssertEqual(field.value as? String, value)
        capture(app, "next-field-entered")
        let keyboard = app.keyboards.firstMatch
        let finish = keyboard.descendants(matching: .any).matching(NSPredicate(
            format: "label IN %@ OR identifier IN %@",
            ["Return", "return", "Done", "done", "Go", "go"],
            ["Return", "return", "Done", "done", "Go", "go"])).firstMatch
        XCTAssertTrue(finish.waitForExistence(timeout: 5), "系统键盘缺少完成键")
        XCTAssertTrue(finish.isHittable)
        finish.tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: keyboard)
        waitForExpectations(timeout: 10)
    }

    // 日期：2026-11-26；按已滚入正文的输入框及相邻按钮实际矩形选择，拒绝第一个同名按钮。
    @MainActor
    func serverChoose(_ app: XCUIApplication, _ label: String) {
        let field = app.textFields[label]
        serverSeek(app, field)
        let buttons = app.buttons.matching(NSPredicate(format: "label == %@", "选择")).allElementsBoundByIndex
        let candidates = buttons.filter {
            $0.isEnabled && $0.isHittable && $0.frame.minX >= field.frame.maxX - 1 &&
            abs($0.frame.midY - field.frame.midY) < 8
        }
        XCTAssertEqual(candidates.count, 1, "输入框没有唯一可操作的相邻选择按钮：" + label)
        guard let button = candidates.first else { return }
        button.tap()
    }

    // 日期：2026-11-26；只承认产品实际状态文字，超时保留界面；服务端与落盘还须独立核验。
    @MainActor
    func serverStatus(_ app: XCUIApplication, _ text: String) {
        let status = app.descendants(matching: .any).matching(NSPredicate(
            format: "label CONTAINS %@ OR value CONTAINS %@", text, text)).firstMatch
        XCTAssertTrue(status.waitForExistence(timeout: 60), "未出现服务器状态：" + text)
        capture(app, "next-status")
    }

    // 日期：2026-11-26；真实Files取消重开后导入临时配对文件，仅传入公开目标和证书摘要。
    @MainActor
    func testNextPairAndBrowse() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "next-pair-final") }
        let welcome = app.buttons["开始使用"]
        if welcome.waitForExistence(timeout: 5) { welcome.tap() }
        let open = app.buttons["服务器 · 上传 / 下载"]
        XCTAssertTrue(open.waitForExistence(timeout: 15))
        XCTAssertTrue(open.isHittable)
        open.tap()
        let pairing = app.descendants(matching: .any).matching(
            NSPredicate(format: "label == %@", "首次连接：展开配对设置")).firstMatch
        serverSeek(app, pairing)
        pairing.tap()
        try serverEnter(app, "服务器 IP:端口（默认 4646）", "__NEXT_TARGET__")
        try serverEnter(app, "核对服务器 SHA-256 指纹", "__NEXT_FINGERPRINT__")
        for attempt in 0..<2 {
            serverChoose(app, "配对文件路径")
            waitForDocumentPicker(app)
            capture(app, "next-pair-picker-" + String(attempt))
            if attempt == 0 { cancelSystemDocuments(app) }
        }
        openApplicationDocuments(app, "a-next-pairing.json")
        tapDocumentCell(app, "a-next-pairing.json")
        let confirm = app.buttons["Open"]
        if confirm.waitForExistence(timeout: 3) && confirm.isHittable { confirm.tap() }
        waitForDocumentPickerClosed(app)
        let submit = app.buttons["配对并保存资料"]
        serverSeek(app, submit)
        submit.tap()
        serverStatus(app, "配对成功；客户端 UUID：")
        serverSeek(app, pairing)
        pairing.tap()
        let browse = app.buttons["浏览"]
        serverSeek(app, browse)
        browse.tap()
        serverStatus(app, "当前页 1 项")
    }

    // 日期：2026-11-26；应用目录选择后下载含中文、空文件与空目录的真实服务器目录。
    @MainActor
    func testNextDownload() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "next-download-final") }
        try serverEnter(app, "共享内相对路径；空表示共享根", "bundle")
        serverChoose(app, "本地保存目录（须已存在）")
        let confirm = app.buttons["OK"]
        XCTAssertTrue(confirm.waitForExistence(timeout: 15))
        XCTAssertTrue(confirm.isHittable)
        confirm.tap()
        let download = app.buttons["下载"]
        serverSeek(app, download)
        XCTAssertTrue(download.isEnabled)
        download.tap()
        serverStatus(app, "任务状态：completed")
    }

    // 日期：2026-11-26；系统Files选择真实上传目录，保留双方结果由独立服务端逐条回读。
    @MainActor
    func testNextUploadDirectory() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "next-upload-final") }
        let upload = app.buttons["上传目录"]
        for attempt in 0..<2 {
            serverSeek(app, upload)
            upload.tap()
            waitForDocumentPicker(app)
            capture(app, "next-upload-picker-" + String(attempt))
            if attempt == 0 { cancelSystemDocuments(app) }
        }
        openApplicationDocuments(app, "a-next-upload")
        tapDocumentCell(app, "a-next-upload")
        let confirm = app.navigationBars.buttons.matching(
            NSPredicate(format: "label IN %@", ["Open", "Done"])).firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10))
        XCTAssertTrue(confirm.isEnabled && confirm.isHittable)
        confirm.tap()
        waitForDocumentPickerClosed(app)
        serverStatus(app, "任务状态：completed")
    }

}
