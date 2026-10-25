import XCTest

final class CustomerAcceptanceTests: XCTestCase {
    func testOptionalGuidesReturnHomeWithoutConnecting() {
        let app = XCUIApplication()
        app.launch()
        app.tabBars.buttons["Home"].tap()
        let open = app.buttons["open-practice-guide"]
        XCTAssertTrue(open.waitForExistence(timeout: 15))
        for purpose in ["alerts", "trade", "follow"] {
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
