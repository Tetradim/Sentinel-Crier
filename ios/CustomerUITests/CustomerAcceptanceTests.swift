import XCTest

final class CustomerAcceptanceTests: XCTestCase {
    private func capture(_ name: String, app: XCUIApplication) {
        let screenshot = app.screenshot()
        let attachment = XCTAttachment(screenshot: screenshot)
        attachment.name = name; attachment.lifetime = .keepAlways
        add(attachment)
        let encoded = Array(screenshot.pngRepresentation.base64EncodedString())
        for offset in stride(from: 0, to: encoded.count, by: 4000) {
            print("CRIER_SCREENSHOT|\(name)|\(offset)|" + String(encoded[offset..<min(offset + 4000, encoded.count)]))
        }
    }

    func testCaptureDisconnectedWorkspace() {
        let app = XCUIApplication(); app.launch()
        XCTAssertTrue(app.tabBars.buttons["Home"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Stop all"].isHittable)
        XCTAssertTrue(app.buttons["Add connection"].isHittable)
        XCTAssertTrue(app.buttons["Account ID bank"].isHittable)
        XCTAssertTrue(app.staticTexts["TOTAL ACCOUNT VALUE"].exists)
        capture("ios-home-disconnected", app: app)
        app.tabBars.buttons["Orders"].tap()
        XCTAssertTrue(app.staticTexts["No saved orders loaded"].waitForExistence(timeout: 5))
        capture("ios-orders-disconnected", app: app)
        app.tabBars.buttons["Trade"].tap()
        XCTAssertTrue(app.buttons["crier.order.review"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["crier.order.review"].isEnabled)
        capture("ios-trade-disconnected", app: app)
        app.tabBars.buttons["Positions"].tap()
        XCTAssertTrue(app.searchFields.firstMatch.waitForExistence(timeout: 5))
        capture("ios-positions-disconnected", app: app)
        app.navigationBars.buttons["Recovery"].tap()
        XCTAssertTrue(app.staticTexts["Local records, not a fresh broker check"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.staticTexts["Read-only order evidence. Open Account ID bank in the header for shared-account IDs, broker checks and guided recovery."].exists)
        capture("ios-recovery-disconnected", app: app)
        app.tabBars.buttons["Markets"].tap()
        capture("ios-markets-disconnected", app: app)
    }

    func testOptionalGuidesReturnHomeWithoutConnecting() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["Home"].tap()
        let open = app.buttons["open-practice-guide"]
        XCTAssertTrue(open.waitForExistence(timeout: 15))
        for purpose in ["alerts", "trade", "follow"] {
            for _ in 0..<3 where !open.isHittable { app.swipeUp() }
            XCTAssertTrue(open.isHittable)
            open.tap()
            let journey = app.buttons["practice-\(purpose)"]
            XCTAssertTrue(journey.waitForExistence(timeout: 5))
            if !journey.isHittable { app.swipeUp() }
            journey.tap()
            let step = app.descendants(matching: .any).matching(identifier: "practice-step-\(purpose)-0").firstMatch
            XCTAssertTrue(step.waitForExistence(timeout: 5))
            XCTAssertTrue(step.label.lowercased().contains("paper"))
            let attachment = XCTAttachment(screenshot: app.screenshot())
            attachment.name = "Optional practice \(purpose)"; attachment.lifetime = .keepAlways
            add(attachment)
            app.navigationBars.buttons.element(boundBy: 0).tap()
            app.navigationBars.buttons.element(boundBy: 0).tap()
            XCTAssertTrue(open.waitForExistence(timeout: 5))
            XCTAssertFalse(app.buttons["Disconnect"].exists)
        }
    }
}
