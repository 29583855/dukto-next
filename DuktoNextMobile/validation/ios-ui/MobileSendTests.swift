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

    // 日期：2026-11-26；教学正文消失才表示关闭，Preview是普通键盘也保留的内部节点。
    @MainActor
    func dismissKeyboardTeaching(_ app: XCUIApplication) {
        let teaching = app.staticTexts[
            "Speed up your typing by sliding your finger across the letters to compose a word."
        ]
        if teaching.waitForExistence(timeout: 3) {
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

    // 日期：2026-11-26；仅按系统提供的实际语义节点点击，未找到时保留完整界面并失败。
    @MainActor
    func tapDocumentNode(_ app: XCUIApplication, _ label: String) {
        let node = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", label)).firstMatch
        XCTAssertTrue(node.waitForExistence(timeout: 15), "系统文件界面缺少节点：" + label)
        node.tap()
    }

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
            let cancel = app.buttons["Cancel"]
            XCTAssertTrue(cancel.waitForExistence(timeout: 15), "系统文档选择器未出现")
            if attempt == 0 {
                cancel.tap()
            }
        }
        // 日期：2026-11-26；系统Files可能从Recents开始，按实际Browse入口切到本地应用提供器。
        let local = app.descendants(matching: .any)
            .matching(NSPredicate(format: "label == %@", "On My iPhone")).firstMatch
        if !local.exists {
            tapDocumentNode(app, "Browse")
        }
        capture(app, "documents-locations")
        tapDocumentNode(app, "On My iPhone")
        capture(app, "documents-local")
        tapDocumentNode(app, "Dukto Next")
        capture(app, "documents-application")
        tapDocumentNode(app, "a-ios-document-probe.bin")
        let open = app.buttons["Open"]
        if open.waitForExistence(timeout: 3) && open.isHittable { open.tap() }
        let cancelled = app.buttons["Cancel"]
        let closed = NSPredicate(format: "exists == false")
        expectation(for: closed, evaluatedWith: cancelled)
        waitForExpectations(timeout: 20)
    }
}
