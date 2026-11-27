"""Focused browser acceptance checks for the public Pages entry point, run in CI."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import threading
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "ui-screenshots"


class PagesHandler(SimpleHTTPRequestHandler):
    # The Windows workstation serves .mjs as text/plain with python -m http.server.
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".mjs": "text/plain"}


def ready(page):
    expect(page.locator("#content")).to_have_attribute("aria-busy", "false")
    expect(page.get_by_role("heading", name="報表暫時無法顯示")).to_have_count(0)


def no_horizontal_overflow(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), page.url


def site_chrome(page):
    """Measure the rendered shell rather than inferring style from the stylesheet URL."""
    header = page.locator(".masthead")
    expect(header.locator(".brand")).to_be_visible()
    expect(header.get_by_role("navigation", name="主要導覽")).to_be_visible()
    return page.evaluate("""() => {
        const header = document.querySelector('.masthead');
        const bar = header.querySelector('.topbar.frame');
        const brand = bar.querySelector('.brand');
        const mark = brand.querySelector('.brand-mark');
        const frame = document.querySelector('main.frame').getBoundingClientRect();
        const barBox = bar.getBoundingClientRect();
        const logoBox = mark.getBoundingClientRect();
        const logo = getComputedStyle(brand);
        return {
            brand: brand.innerText.trim(),
            links: Array.from(bar.querySelectorAll('.primary-nav a'), a => a.innerText.trim()),
            canvas: getComputedStyle(document.documentElement).backgroundColor,
            body: getComputedStyle(document.body).backgroundColor,
            header: getComputedStyle(header).backgroundColor,
            mark: getComputedStyle(mark).backgroundColor,
            font: [logo.fontFamily, logo.fontSize, logo.fontWeight, logo.color],
            bounds: {headerHeight: header.getBoundingClientRect().height, barLeft: barBox.left,
                barWidth: barBox.width, frameLeft: frame.left, frameWidth: frame.width,
                logoWidth: logoBox.width, logoHeight: logoBox.height}
        };
    }""")


def assert_report_shell(page, expected, date):
    heading = page.get_by_role("heading", level=1)
    expect(heading).to_contain_text("持股日報")
    expect(page.get_by_role("link", name="開啟同日互動總覽", exact=True)).to_be_visible()
    expect(page.locator('main .date-field time')).to_have_attribute('datetime', date)
    expect(page.locator("#activity")).to_be_attached()
    expect(page.locator("#funds")).to_be_attached()
    styles = page.locator('link[rel="stylesheet"]').evaluate_all("(links) => links.map(link => new URL(link.href).pathname)")
    assert any(path.endswith("/assets/site.css") for path in styles), page.url
    assert any(path.endswith("/assets/report.css") for path in styles), page.url
    actual = site_chrome(page)
    for key in ("brand", "links", "canvas", "body", "header", "mark", "font"):
        assert actual[key] == expected[key], (date, key, actual[key], expected[key])
    for key, value in expected["bounds"].items():
        assert abs(actual["bounds"][key] - value) <= 1.5, (date, key, actual["bounds"][key], value)
    no_horizontal_overflow(page)


def read_static_fund(page, date):
    code = "00981A" if date == "2026-11-26" else "00404A"
    fund = page.locator(f"#funds details.fund#etf-{code}")
    summary = fund.locator(":scope > summary")
    expect(summary).to_contain_text(code)
    if not fund.evaluate("(details) => details.open"):
        summary.click()
    changes = fund.get_by_role("table", name="兩次揭露間的持股異動")
    expect(changes).to_be_visible()
    holdings = fund.get_by_role("table", name=re.compile("完整持股"))
    expect(holdings).to_be_visible()
    assert holdings.locator("tbody tr").count() > 0
    if date == "2026-11-26":
        wistron = changes.get_by_role("row").filter(has_text="緯創")
        for number in ("11,967", "14,258", "+2,291"):
            expect(wistron).to_contain_text(number)
    else:
        for text in ("2026-11-10", "2026-11-18", "跨期"):
            expect(summary).to_contain_text(text)
        expect(changes.locator("tbody tr")).to_have_count(24)
    no_horizontal_overflow(page)


def return_to_edition(page, date, *, interactive=True):
    page.get_by_role("link", name="開啟同日互動總覽", exact=True).click()
    target = urlparse(page.url)
    assert target.path.endswith("/docs/index.html") and parse_qs(target.query).get("date") == [date], page.url
    if interactive:
        ready(page)
        expect(page.locator("#report-date")).to_have_value(date)


def accept_report_paths(page, base, device, chrome):
    """Exercise public links from both entry points, without depending on the latest edition."""
    current, older = "2026-11-26", "2026-11-18"
    page.get_by_role("link", name="本期靜態日報", exact=True).click()
    expect(page).to_have_url(base + f"report_{current}.html")
    page.screenshot(path=ARTIFACTS / f"{device[0]}-report.png", animations="disabled")
    assert_report_shell(page, chrome, current)
    read_static_fund(page, current)
    return_to_edition(page, current)

    page.get_by_role("navigation", name="主要導覽").get_by_role("link", name="歷史報表").click()
    page.get_by_label("報表月份").select_option(older[:7])
    page.get_by_role("button", name="篩選", exact=True).click()
    entry = page.get_by_role("table", name="歷史報表").get_by_role("row").filter(has_text=older)
    entry.get_by_role("link", name="開啟日報").click()
    expect(page).to_have_url(base + f"report_{older}.html")
    assert_report_shell(page, chrome, older)
    read_static_fund(page, older)
    page.screenshot(path=ARTIFACTS / f"{device[0]}-open.png", animations="disabled")
    page.locator(".masthead").get_by_role("link", name=re.compile("^搜尋")).click()
    dialog = page.get_by_role("dialog", name="搜尋股票或 ETF")
    expect(dialog).to_be_visible()
    expect(page.locator("#report-date")).to_have_value(older)
    dialog.get_by_role("searchbox").fill("00404A")
    expect(dialog.get_by_role("link", name=re.compile("00404A"))).to_be_visible()
    dialog.get_by_role("button", name="關閉").click()
    page.go_back()
    expect(page).to_have_url(base + f"report_{older}.html")
    return_to_edition(page, older)
    expect(page.locator("#edition")).to_contain_text("歷史報表")
    page.get_by_role("link", name="前往最新一期").click()
    ready(page)
    expect(page.locator("#edition")).to_contain_text("最新一期")
    assert page.locator("#report-date").input_value() == page.locator("#report-date option").first.get_attribute("value")


def accept_stock_filters(page):
    filters = page.get_by_role("navigation", name="股票異動篩選")
    multi = filters.get_by_role("link", name="多檔調整", exact=True)
    mixed = filters.get_by_role("link", name="方向分歧", exact=True)
    added = filters.get_by_role("link", name="有新增持股", exact=True)

    def selected(link, value):
        expect(multi).to_have_count(1)
        expect(multi).to_be_visible()
        expect(filters.locator('[aria-current="true"]')).to_have_count(1)
        expect(link).to_have_attribute("aria-current", "true")
        assert parse_qs(urlparse(page.url).query).get("filter") == [value], page.url
        no_horizontal_overflow(page)

    multi.click()
    selected(multi, "multi")
    mixed.click()
    selected(mixed, "mixed")
    nanya = page.locator(".stock-table tbody tr").filter(has_text="南亞科")
    for value in ("+935", "增 1", "減 1"):
        expect(nanya).to_contain_text(value)
    added.click()
    selected(added, "added")
    multi.click()
    selected(multi, "multi")
    page.go_back()
    selected(added, "added")
    page.go_forward()
    selected(multi, "multi")


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
    page.screenshot(path=ARTIFACTS / f"{device[0]}-home.png", animations="disabled")
    chrome = site_chrome(page)
    accept_report_paths(page, base, device, chrome)
    page.goto(base + "index.html?date=2026-11-26")
    ready(page)
    accept_stock_filters(page)
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
    page.screenshot(path=ARTIFACTS / f"{device}-directory.png", animations="disabled")

    page.route("**/data_2026-11-13.json", lambda route: route.fulfill(status=503, body="temporary"))
    page.goto(base + "index.html?date=2026-11-13")
    expect(page.get_by_role("heading", name="報表暫時無法顯示")).to_be_visible()
    expect(page.locator("#report-date")).to_be_enabled()
    page.unroute("**/data_2026-11-13.json")
    page.get_by_role("button", name="重新載入").click()
    expect(page.get_by_role("heading", name="每日持股異動")).to_be_visible()

    assert not errors, errors
    return chrome


if __name__ == "__main__":
    ARTIFACTS.mkdir(exist_ok=True)
    # A path prefix exercises the same relative links and fetches used by project Pages.
    handler = partial(PagesHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, sync_playwright() as playwright:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
        try:
            for device, size in [("mobile", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 960})]:
                options = dict(viewport=size, locale="zh-TW", is_mobile=device == "mobile", has_touch=device == "mobile")
                base = f"http://127.0.0.1:{server.server_port}/docs/"
                page = browser.new_page(**options)
                try:
                    chrome = accept(page, base, device)
                finally:
                    page.close()
                no_js = browser.new_page(**options, java_script_enabled=False)
                try:
                    for date in ("2026-11-18", "2026-11-26"):
                        no_js.goto(base + f"report_{date}.html")
                        assert_report_shell(no_js, chrome, date)
                        read_static_fund(no_js, date)
                        return_to_edition(no_js, date, interactive=False)
                finally:
                    no_js.close()
        finally:
            browser.close()
            server.shutdown()
