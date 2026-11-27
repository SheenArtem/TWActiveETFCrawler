"""Focused browser acceptance checks for the public Pages entry point, run in CI."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ui-screenshots"


def ready(page):
    expect(page.locator("#content")).to_have_attribute("aria-busy", "false")
    expect(page.get_by_role("heading", name="報表暫時無法顯示")).to_have_count(0)


def no_horizontal_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), page.url


def accept(page, base, device):
    errors = []
    initial_files = set()
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on("request", lambda req: initial_files.add(Path(urlparse(req.url).path).name))
    page.goto(base + "index.html?date=2026-11-26")
    ready(page)
    expect(page.get_by_role("heading", name="每日持股異動")).to_be_visible()
    expect(page.locator(".coverage-number")).to_have_text(re.compile(r"20\s*/\s*23"))
    assert page.locator(".metric strong").all_text_contents() == ["66", "45", "21"]
    assert [f for f in initial_files if f.startswith("data_")] == ["data_2026-11-26.json"], initial_files
    no_horizontal_overflow(page)
    page.screenshot(path=ARTIFACTS / f"{device}-overview.png", animations="disabled")

    page.get_by_role("link", name="方向分歧", exact=True).click()
    mixed = page.locator(".stock-table tbody tr").filter(has_text="南亞科")
    expect(mixed).to_contain_text("+935")
    expect(mixed).to_contain_text("增 1")
    expect(mixed).to_contain_text("減 1")
    page.get_by_role("link", name="僅一檔", exact=True).click()
    page.get_by_role("button", name=re.compile("搜尋")).click()
    page.get_by_role("searchbox").fill("緯創")
    page.get_by_role("searchbox").press("Enter")
    expect(page.locator(".detail-header h1")).to_contain_text("3231")
    event = page.get_by_role("table", name="持股異動紀錄").locator("tr").filter(has_text="00981A")
    expect(event).to_contain_text("+2,291")
    expect(event).to_contain_text("11,967")
    expect(event).to_contain_text("14,258")
    no_horizontal_overflow(page)
    page.go_back()
    expect(page.locator(".chip[aria-current]")).to_have_text("僅一檔")
    expect(page.locator("#open-search")).to_be_focused()
    page.go_forward()
    expect(page.locator(".detail-header h1")).to_contain_text("3231")
    page.get_by_role("button", name=re.compile("^追蹤 ")).click()
    page.get_by_role("navigation", name="主要導覽").get_by_role("link", name="我的追蹤").click()
    expect(page.get_by_role("table", name="追蹤的股票")).to_contain_text("3231")
    page.reload()
    expect(page.get_by_role("table", name="追蹤的股票")).to_contain_text("3231")

    page.goto(base + "index.html?view=etf&date=2026-11-18&code=00404A")
    ready(page)
    meta = page.locator(".detail-header")
    expect(meta).to_contain_text("2026-11-10")
    expect(meta).to_contain_text("2026-11-18")
    expect(meta).to_contain_text("跨期")
    no_horizontal_overflow(page)
    page.screenshot(path=ARTIFACTS / f"{device}-fund.png", animations="disabled")

    page.get_by_role("link", name="完整持股", exact=True).click()
    expect(page.get_by_role("heading", name="完整持股")).to_be_visible()
    page.get_by_role("link", name="與其他 ETF 比較").click()
    form = page.locator("form[data-route]")
    form.locator('[name="first"]').select_option("00981A")
    form.locator('[name="second"]').select_option("00985A")
    form.get_by_role("button", name="比較").click()
    expect(page.get_by_role("table", name="兩檔 ETF 的持股比較")).to_be_visible()
    no_horizontal_overflow(page)
    page.goto(base + "index.html?date=2026-11-26&view=compare&kind=dates&first=00981A&from=2026-11-25")
    ready(page)
    expect(page.locator("#content")).to_contain_text("2,291")

    # The live market file only retains recent AUM. Pin an as-of value to test a historical edition.
    page.route("**/etf_market_data.json", lambda route: route.fulfill(json={"data": [
        {"etf_code": "00981A", "aum_billion": 2730.98, "aum_date": "2026/11/26"}
    ]}))
    page.get_by_role("navigation", name="主要導覽").get_by_role("link", name="ETF 清單").click()
    page.locator('select[data-set="sort"]').select_option("aum")
    size = page.locator(".by-size tbody tr").first.locator(".fund-size")
    expect(size).to_be_visible()
    expect(size).to_contain_text("2,730.98")
    expect(size).to_contain_text("2026-11-26")
    no_horizontal_overflow(page)

    page.route("**/data_2026-11-13.json", lambda route: route.fulfill(status=503, body="temporary"))
    page.goto(base + "index.html?date=2026-11-13")
    expect(page.get_by_role("heading", name="報表暫時無法顯示")).to_be_visible()
    expect(page.locator("#report-date")).to_be_enabled()
    page.unroute("**/data_2026-11-13.json")
    page.get_by_role("button", name="重新載入").click()
    expect(page.get_by_role("heading", name="每日持股異動")).to_be_visible()

    page.goto(base + "report_2026-11-18.html")
    page.locator('a[href="index.html"]').click()
    expect(page.locator("#report-date")).to_have_value("2026-11-18")
    expect(page.locator("#edition")).to_contain_text("歷史報表")
    page.get_by_role("link", name="前往最新一期").click()
    ready(page)
    expect(page.locator("#edition")).to_have_text("最新一期")
    assert not errors, errors


if __name__ == "__main__":
    ARTIFACTS.mkdir(exist_ok=True)
    # A path prefix exercises the same relative links and fetches used by project Pages.
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, sync_playwright() as playwright:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
        try:
            for device, size in [("mobile", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 960})]:
                page = browser.new_page(viewport=size, locale="zh-TW", is_mobile=device == "mobile", has_touch=device == "mobile")
                try:
                    accept(page, f"http://127.0.0.1:{server.server_port}/docs/", device)
                finally:
                    page.close()
        finally:
            browser.close()
            server.shutdown()
