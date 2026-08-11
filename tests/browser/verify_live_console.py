from __future__ import annotations

from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = "http://localhost:9293"
SCREENSHOTS = Path("test-results/live-screenshots")
MODEL_NAME = "Qwen3.6 27B Fable Fusion - NVFP4"


def assert_no_horizontal_overflow(page) -> None:
    dimensions = page.evaluate(
        "() => ({scroll: document.documentElement.scrollWidth, "
        "client: document.documentElement.clientWidth})"
    )
    assert dimensions["scroll"] <= dimensions["client"], dimensions


def main() -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.locator("#model-list .model-row").first.wait_for(timeout=30_000)
        page.locator("#gpu-summary .gpu-device").wait_for(timeout=30_000)

        assert page.locator("#model-list .model-row").count() == 8
        assert "RTX 5090" in page.locator("#gpu-summary").inner_text()
        assert page.locator("#process-list .process-row").count() > 0
        assert int(page.locator("#running-count").inner_text()) >= 1

        page.get_by_text(MODEL_NAME, exact=True).last.click()
        page.locator("#detail-name").wait_for()
        assert page.locator("#detail-status").inner_text() == "loaded"
        assert "8192" in page.locator("#memory-settings").inner_text()
        assert_no_horizontal_overflow(page)
        page.screenshot(path=SCREENSHOTS / "live-console-1440x900.png", full_page=True)

        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("button", name="状态", exact=True).click()
        assert page.locator("#operations-panel").is_visible()
        assert page.locator("#process-list .process-row").count() > 0
        assert_no_horizontal_overflow(page)
        page.screenshot(path=SCREENSHOTS / "live-console-390x844.png", full_page=True)

        for screenshot in SCREENSHOTS.glob("live-console-*.png"):
            assert screenshot.stat().st_size > 10_000, screenshot
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
