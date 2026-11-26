import XCTest

final class MobileSendTests: XCTestCase {
    // 日期：2026-11-26；失败时保留完整系统节点树和屏幕，不在产品中注入发送入口。
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

    // 日期：2026-11-26；系统教学冷启动可能超过3秒，初次限定等待60秒；正文消失才表示关闭。
    // 日期：2026-11-26；Preview是普通键盘也保留的内部节点，不能据其存在断言教学显示。
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

    // 日期：2026-11-26；逐键点击实际系统键盘，避免Qt5虚拟字段缺失键盘焦点属性阻止XCTest输入。
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

    // 日期：2026-11-26；只激活已安装且已通过接收的原始应用，经真实控件指定目标并发送。
    @MainActor
    func testSendTextFromProductionUI() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "final") }
        let welcome = app.buttons["开始使用"]
        if welcome.waitForExistence(timeout: 5) { welcome.tap() }
        capture(app, "devices")
        let manual = app.buttons["IP 连接 · 发送到指定设备"]
        XCTAssertTrue(manual.waitForExistence(timeout: 15))
        manual.tap()
        capture(app, "target")
        let host = app.textFields["目标 IP 或主机名"]
        XCTAssertTrue(host.waitForExistence(timeout: 10))
        host.tap()
        dismissKeyboardTeaching(app)
        capture(app, "keyboard-ready")
        try tapKeyboard(app, "127.0.0.1")
        let port = app.textFields["目标端口"]
        XCTAssertTrue(port.waitForExistence(timeout: 10))
        port.tap()
        let initialPort = try XCTUnwrap(port.value as? String)
        XCTAssertEqual(initialPort, "4644")
        capture(app, "port-keyboard-ready")
        // 日期：2026-11-26；数字键盘删除键可为Button且名称大小写不同，按实际语义节点查找。
        let delete = app.keyboards.firstMatch.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier ==[c] %@ OR label ==[c] %@", "delete", "delete"))
            .firstMatch
        XCTAssertTrue(delete.waitForExistence(timeout: 5), "系统数字键盘缺少删除控件")
        for _ in initialPort {
            delete.tap()
        }
        try tapKeyboard(app, "49231")
        // 日期：2026-11-26；从实际字段读取目标值，避免键盘删除失败后误向其他端口发送。
        XCTAssertEqual(host.value as? String, "127.0.0.1")
        XCTAssertEqual(port.value as? String, "49231")
        let textAction = app.buttons["发送文字"]
        XCTAssertTrue(textAction.waitForExistence(timeout: 5))
        textAction.tap()
        capture(app, "text-dialog")
        // 日期：2026-11-26；Qt多行编辑器的系统类型随版本变化，按产品读屏名称定位正文。
        let editor = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", "发送文字正文")).firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.tap()
        let body = "Dukto iOS production UI send / ASCII 20261126"
        try tapKeyboard(app, body)
        XCTAssertEqual(editor.value as? String, body)
        capture(app, "editor")
        let submit = app.buttons.matching(NSPredicate(format: "label == %@", "发送")).firstMatch
        XCTAssertTrue(submit.waitForExistence(timeout: 5))
        // 日期：2026-11-26；发送键须在键盘上方且实际可点，不能依靠测试框架滚动掩盖产品遮挡。
        XCTAssertTrue(submit.isHittable)
        let keyboard = app.keyboards.firstMatch
        if keyboard.exists {
            XCTAssertLessThanOrEqual(submit.frame.maxY, keyboard.frame.minY + 1)
        }
        submit.tap()
        let closed = NSPredicate(format: "exists == false")
        expectation(for: closed, evaluatedWith: submit)
        waitForExpectations(timeout: 15)
    }

    // 日期：2026-11-26；仅点击系统File View中的文件单元，避免匹配产品后台同名标题。
    @MainActor
    func documentCell(_ app: XCUIApplication, _ label: String) -> XCUIElement {
        return app.collectionViews["File View"].cells
            .containing(.staticText, identifier: label).firstMatch
    }

    // 日期：2026-11-26；选择实际可点击的文件单元，不能依靠自动滚动点击后台标题。
    @MainActor
    func tapDocumentCell(_ app: XCUIApplication, _ label: String) {
        let cell = documentCell(app, label)
        XCTAssertTrue(cell.waitForExistence(timeout: 15), "系统文件界面缺少文件单元：" + label)
        XCTAssertTrue(cell.isHittable, "系统文件单元不可点击：" + label)
        cell.tap()
    }

    // 日期：2026-11-26；以真实Files导航栏判断选择器出现，目录深层页面可能没有Cancel按钮。
    @MainActor
    func documentNavigation(_ app: XCUIApplication) -> XCUIElement {
        return app.navigationBars["FullDocumentManagerViewControllerNavigationBar"]
    }

    // 日期：2026-11-26；首次系统Files冷启动限定等待60秒，不依赖仅在部分页面出现的Cancel。
    @MainActor
    func waitForDocumentPicker(_ app: XCUIApplication) {
        XCTAssertTrue(documentNavigation(app).waitForExistence(timeout: 60), "系统Files导航栏未出现")
    }

    // 日期：2026-11-26；真实导航按钮可能被同坐标Other节点影响可点击判定，保留节点并验证屏内位置。
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

    // 日期：2026-11-26；等待实际Cancel或返回按钮出现，取消仍必须由系统选择器关闭及重开验证。
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

    // 日期：2026-11-26；关闭必须由系统Files导航栏整体消失确认，不能以当前目录没有Cancel误判成功。
    @MainActor
    func waitForDocumentPickerClosed(_ app: XCUIApplication) {
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: documentNavigation(app))
        waitForExpectations(timeout: 30)
    }

    // 日期：2026-11-26；Files冷启动实测约25秒，等待限定60秒；不重发或重启产品以掩盖失败。
    // 日期：2026-11-26；接收样本后走真实系统文件选择器，取消重开，再由独立接收器核对发送字节。
    @MainActor
    func testSendFileFromSystemDocuments() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "documents-final") }
        for attempt in 0..<2 {
            let manual = app.buttons["IP 连接 · 发送到指定设备"]
            XCTAssertTrue(manual.waitForExistence(timeout: 15))
            manual.tap()
            XCTAssertEqual(app.textFields["目标 IP 或主机名"].value as? String, "127.0.0.1")
            XCTAssertEqual(app.textFields["目标端口"].value as? String, "49231")
            let files = app.buttons["发送文件"]
            XCTAssertTrue(files.waitForExistence(timeout: 10))
            files.tap()
            capture(app, "documents-picker-" + String(attempt))
            waitForDocumentPicker(app)
            if attempt == 0 { cancelSystemDocuments(app) }
        }
        // 日期：2026-11-26；Files会记忆应用目录，已看到样本则直接选取；否则按系统按钮和单元导航。
        let sampleName = "a-ios-document-probe.bin"
        if !documentCell(app, sampleName).exists {
            if !documentCell(app, "Dukto Next").exists {
                let local = app.buttons["On My iPhone"]
                if !local.exists {
                    let browse = app.buttons["Browse"].firstMatch
                    XCTAssertTrue(browse.waitForExistence(timeout: 15))
                    XCTAssertTrue(browse.isHittable)
                    browse.tap()
                }
                capture(app, "documents-locations")
                XCTAssertTrue(local.waitForExistence(timeout: 15))
                XCTAssertTrue(local.isHittable)
                local.tap()
            }
            capture(app, "documents-local")
            tapDocumentCell(app, "Dukto Next")
        }
        capture(app, "documents-application")
        tapDocumentCell(app, sampleName)
        let open = app.buttons["Open"]
        if open.waitForExistence(timeout: 3) && open.isHittable { open.tap() }
        waitForDocumentPickerClosed(app)
    }

    // 日期：2026-11-26；真实Files目录选择必须取消后重开，进入授权目录再确认，由独立接收器核对结构。
    @MainActor
    func testSendDirectoryFromSystemDocuments() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "directory-final") }
        for attempt in 0..<2 {
            let manual = app.buttons["IP 连接 · 发送到指定设备"]
            XCTAssertTrue(manual.waitForExistence(timeout: 15))
            manual.tap()
            XCTAssertEqual(app.textFields["目标 IP 或主机名"].value as? String, "127.0.0.1")
            XCTAssertEqual(app.textFields["目标端口"].value as? String, "49231")
            let folder = app.buttons["发送文件夹"]
            XCTAssertTrue(folder.waitForExistence(timeout: 10))
            folder.tap()
            capture(app, "directory-picker-" + String(attempt))
            waitForDocumentPicker(app)
            if attempt == 0 { cancelSystemDocuments(app) }
        }
        let folderName = "a-ios-directory-probe"
        if !documentCell(app, folderName).exists {
            if !documentCell(app, "Dukto Next").exists {
                let local = app.buttons["On My iPhone"]
                if !local.exists {
                    let browse = app.buttons["Browse"].firstMatch
                    XCTAssertTrue(browse.waitForExistence(timeout: 15))
                    XCTAssertTrue(browse.isHittable)
                    browse.tap()
                }
                XCTAssertTrue(local.waitForExistence(timeout: 15))
                XCTAssertTrue(local.isHittable)
                local.tap()
            }
            tapDocumentCell(app, "Dukto Next")
        }
        capture(app, "directory-application")
        tapDocumentCell(app, folderName)
        capture(app, "directory-selected")
        let open = app.buttons["Open"]
        XCTAssertTrue(open.waitForExistence(timeout: 10))
        XCTAssertTrue(open.isHittable)
        open.tap()
        waitForDocumentPickerClosed(app)
    }

    // 日期：2026-11-26；只沿系统导航按钮返回应用Files根，不点击后台同名Qt文字。
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
            for label in ["Dukto Next", "On My iPhone", "Browse"] {
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

    // 日期：2026-11-26；系统导入先取消再重开，成功关闭后按钮必须恢复可用。
    @MainActor
    func importFromSystem(_ app: XCUIApplication, _ directory: Bool) {
        let action = app.buttons[directory ? "导入目录" : "导入文件"]
        for attempt in 0..<2 {
            XCTAssertTrue(action.waitForExistence(timeout: 15))
            XCTAssertTrue(action.isEnabled && action.isHittable)
            action.tap()
            waitForDocumentPicker(app)
            capture(app, "storage-import-picker-" + String(attempt))
            if attempt == 0 { cancelSystemDocuments(app) }
        }
        openApplicationDocuments(app, "a-ios-io-source")
        tapDocumentCell(app, "a-ios-io-source")
        tapDocumentCell(app, directory ? "a-ios-import-directory" : "a-ios-import.bin")
        let open = app.buttons["Open"]
        if directory {
            XCTAssertTrue(open.waitForExistence(timeout: 10))
            XCTAssertTrue(open.isHittable)
            open.tap()
        } else if open.waitForExistence(timeout: 3) && open.isHittable {
            open.tap()
        }
        waitForDocumentPickerClosed(app)
        expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: action)
        waitForExpectations(timeout: 20)
    }

    // 日期：2026-11-26；只通过产品导入按钮复制系统文件，宿主稍后逐字节读取目标验证。
    @MainActor
    func testImportFileFromSystemDocuments() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "storage-import-file-final") }
        let files = app.buttons["应用文件"]
        XCTAssertTrue(files.waitForExistence(timeout: 15))
        files.tap()
        importFromSystem(app, false)
    }

    // 日期：2026-11-26；系统目录授权覆盖中文、空文件及空目录，不能从宿主直接写入导入结果。
    @MainActor
    func testImportDirectoryFromSystemDocuments() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "storage-import-directory-final") }
        importFromSystem(app, true)
    }

    // 日期：2026-11-26；Qt列表ItemDelegate实际映射为Other，按精确名称选择行而非同名StaticText。
    @MainActor
    func applicationFileEntry(_ app: XCUIApplication, _ label: String) -> XCUIElement {
        return app.otherElements.matching(NSPredicate(format: "label == %@", label)).firstMatch
    }

    // 日期：2026-11-26；实际导出选择器取消重开，并由系统复制到指定目标目录。
    @MainActor
    func exportToSystem(_ app: XCUIApplication, _ directory: Bool) {
        let action = directory ? app.buttons["导出目录"] : applicationFileEntry(app, "a-ios-import.bin")
        for attempt in 0..<2 {
            XCTAssertTrue(action.waitForExistence(timeout: 15))
            XCTAssertTrue(action.isEnabled && action.isHittable)
            action.tap()
            waitForDocumentPicker(app)
            capture(app, "storage-export-picker-" + String(attempt))
            if attempt == 0 { cancelSystemDocuments(app) }
        }
        openApplicationDocuments(app, "a-ios-io-export")
        tapDocumentCell(app, "a-ios-io-export")
        capture(app, "storage-export-target")
        let confirm = app.navigationBars.buttons.matching(
            NSPredicate(format: "label IN %@", ["Export", "Save", "Copy", "Move"])
        ).firstMatch
        XCTAssertTrue(confirm.waitForExistence(timeout: 10), "系统导出缺少完成按钮")
        XCTAssertTrue(confirm.isEnabled && confirm.isHittable)
        confirm.tap()
        waitForDocumentPickerClosed(app)
        let available = app.buttons["导入文件"]
        expectation(for: NSPredicate(format: "enabled == true"), evaluatedWith: available)
        waitForExpectations(timeout: 15)
    }

    // 日期：2026-11-26；点击已导入文件发起系统导出，宿主回读检查内容和源保留。
    @MainActor
    func testExportFileToSystemDocuments() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "storage-export-file-final") }
        exportToSystem(app, false)
    }

    // 日期：2026-11-26；进入已导入目录再导出整个目录，保留真实系统节点和屏幕证据。
    @MainActor
    func testExportDirectoryToSystemDocuments() throws {
        continueAfterFailure = false
        let app = XCUIApplication(bundleIdentifier: "org.duktonext.mobile")
        app.activate()
        defer { capture(app, "storage-export-directory-final") }
        let folder = applicationFileEntry(app, "[目录] a-ios-import-directory")
        XCTAssertTrue(folder.waitForExistence(timeout: 15))
        XCTAssertTrue(folder.isHittable)
        folder.tap()
        exportToSystem(app, true)
    }
}
