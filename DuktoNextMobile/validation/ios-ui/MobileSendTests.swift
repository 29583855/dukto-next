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
        // 日期：2026-11-26；新模拟器首次键盘教学会覆盖焦点，按系统实际按钮关闭并留存现场。
        let springboard = XCUIApplication(bundleIdentifier: "com.apple.springboard")
        let appKeyboardContinue = app.buttons["Continue"]
        let systemKeyboardContinue = springboard.buttons["Continue"]
        if appKeyboardContinue.waitForExistence(timeout: 2) && appKeyboardContinue.isHittable {
            capture(app, "keyboard-onboarding")
            appKeyboardContinue.tap()
            host.tap()
        } else if systemKeyboardContinue.waitForExistence(timeout: 2) && systemKeyboardContinue.isHittable {
            capture(springboard, "keyboard-onboarding")
            systemKeyboardContinue.tap()
            host.tap()
        }
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
        let editor = app.textViews.firstMatch
        XCTAssertTrue(editor.waitForExistence(timeout: 5))
        editor.tap()
        let body = "Dukto iOS production UI send / ASCII 20261126"
        try tapKeyboard(app, body)
        XCTAssertEqual(editor.value as? String, body)
        capture(app, "editor")
        let submit = app.buttons.matching(NSPredicate(format: "label == %@", "发送")).firstMatch
        XCTAssertTrue(submit.waitForExistence(timeout: 5))
        submit.tap()
        let closed = NSPredicate(format: "exists == false")
        expectation(for: closed, evaluatedWith: submit)
        waitForExpectations(timeout: 15)
    }
}
