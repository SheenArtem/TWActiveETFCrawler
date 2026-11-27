"""Focused browser acceptance checks for the public Pages entry point, run in CI."""
from contextlib import contextmanager
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


def nav(page, name):
    return page.get_by_role("navigation", name="主要導覽").get_by_role("link", name=name, exact=True)


def app_route(page, view, date):
    target = urlparse(page.url)
    params = parse_qs(target.query)
    assert target.path.endswith("/docs/index.html") and params.get("date") == [date], page.url
    assert params.get("view", ["overview"]) == [view], page.url
    if view == "report":
        assert params == {"date": [date], "view": ["report"]}, page.url
    return params


def controls_fit(page):
    no_horizontal_overflow(page)
    issues = page.evaluate("""() => {
        const candidates = '.masthead .brand, .masthead .primary-nav a, #open-search, ' +
            '[data-theme-choice], #report-date, #content h1';
        const boxes = Array.from(document.querySelectorAll(candidates), el => ({
            name: el.getAttribute('aria-label') || el.textContent.trim(), rect: el.getBoundingClientRect()
        })).filter(({rect}) => rect.width && rect.height);
        const problems = [];
        for (const [i, {name, rect}] of boxes.entries()) {
            if (rect.left < -1 || rect.right > document.documentElement.clientWidth + 1)
                problems.push(name + ' 超出螢幕');
            for (const next of boxes.slice(i + 1)) {
                const overlapX = Math.min(rect.right, next.rect.right) - Math.max(rect.left, next.rect.left);
                const overlapY = Math.min(rect.bottom, next.rect.bottom) - Math.max(rect.top, next.rect.top);
                if (overlapX > 1 && overlapY > 1) problems.push(name + ' 與 ' + next.name + ' 重疊');
            }
        }
        return problems;
    }""")
    assert not issues, (page.url, issues)


def rendered_colors(locator):
    """Composite the text and its actual ancestor backgrounds, including transparent surfaces."""
    return locator.evaluate("""el => {
        const ctx = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
        const paint = color => {
            ctx.fillStyle = color;
            ctx.fillRect(0, 0, 1, 1);
            return Array.from(ctx.getImageData(0, 0, 1, 1).data).slice(0, 3);
        };
        const ancestors = [];
        for (let node = el; node; node = node.parentElement) ancestors.unshift(node);
        let background = paint(getComputedStyle(document.documentElement).colorScheme === 'dark' ? 'black' : 'white');
        for (const node of ancestors) background = paint(getComputedStyle(node).backgroundColor);
        return [paint(getComputedStyle(el).color), background];
    }""")


def luminance(rgb):
    channels = [channel / 255 for channel in rgb]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return sum(value * weight for value, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


def readable(locator):
    expect(locator).to_be_visible()
    colors = rendered_colors(locator)
    low, high = sorted(luminance(rgb) for rgb in colors)
    assert (high + 0.05) / (low + 0.05) >= 4.5, (str(locator), colors)


def assert_theme(page, mode, *, interactive=True):
    if interactive:
        expect(page.locator("html")).to_have_attribute("data-theme", mode)
        for choice, label in [("light", "白天模式"), ("dark", "夜間模式")]:
            button = page.locator(f'[data-theme-choice="{choice}"]')
            expect(button).to_have_attribute("aria-label", label)
            expect(button).to_be_visible()
            expect(button).to_have_attribute("aria-pressed", str(choice == mode).lower())
        readable(page.locator('[data-theme-choice][aria-pressed="true"]'))
        readable(page.locator("#report-date"))
    assert page.locator("html").evaluate("el => getComputedStyle(el).colorScheme") == mode
    canvas = rendered_colors(page.locator("body"))[1]
    assert (luminance(canvas) < 0.35) == (mode == "dark"), (mode, canvas)
    for selector in (".masthead .brand", ".primary-nav [aria-current]", "#content h1", ".coverage-label"):
        readable(page.locator(selector).first)


def print_on_white(page):
    page.emulate_media(media="print")
    try:
        for selector in ("#content h1", "#activity .panel"):
            element = page.locator(selector).first
            readable(element)
            assert rendered_colors(element)[1] == [255, 255, 255], selector
    finally:
        page.emulate_media(media="screen")


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


def assert_report_shell(page, expected, date, *, interactive=True):
    report = page.locator("#content > article#daily-report")
    expect(report).to_have_attribute("data-report-date", date)
    expect(report.get_by_role("heading", level=1)).to_have_text("持股日報")
    expect(nav(page, "持股日報")).to_have_attribute("aria-current", "page")
    if interactive:
        expect(page.locator("#report-date")).to_have_value(date)
        expect(page.locator("#open-search")).to_be_visible()
    else:
        date_field = page.locator("main .date-field time")
        expect(date_field).to_be_visible()
        expect(date_field).to_have_attribute("datetime", date)
    expect(report.locator("#activity")).to_be_attached()
    expect(report.locator("#funds")).to_be_attached()
    styles = page.locator('link[rel="stylesheet"]').evaluate_all("(links) => links.map(link => new URL(link.href).pathname)")
    assert any(path.endswith("/assets/site.css") for path in styles), page.url
    assert any(path.endswith("/assets/report.css") for path in styles), page.url
    actual = site_chrome(page)
    for key in ("brand", "links", "canvas", "body", "header", "mark", "font"):
        assert actual[key] == expected[key], (date, key, actual[key], expected[key])
    for key, value in expected["bounds"].items():
        assert abs(actual["bounds"][key] - value) <= 1.5, (date, key, actual["bounds"][key], value)
    controls_fit(page)


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
        for direction in (".num.up", ".num.down"):
            readable(changes.locator(direction).first)
    else:
        for text in ("2026-11-10", "2026-11-18", "跨期"):
            expect(summary).to_contain_text(text)
        expect(changes.locator("tbody tr")).to_have_count(24)
    no_horizontal_overflow(page)


def read_global_fund(page):
    fund = page.locator("#funds #etf-00988A")
    if not fund.evaluate("el => el.open"):
        fund.locator("summary").click()
    changes = fund.get_by_role("table", name="兩次揭露間的持股異動")
    holdings = fund.get_by_role("table", name=re.compile("完整持股"))
    for code, delta, quantity in (("7532 JP", "+500 千股", "1,000 千股"), ("3665", "+200 張", "200 張")):
        changed = changes.get_by_role("row").filter(has_text=code)
        expect(changed.get_by_role("cell").last).to_have_text(delta)
        held = holdings.get_by_role("row").filter(has_text=code)
        expect(held.get_by_role("cell").last).to_have_text(quantity)
        target = parse_qs(urlparse(held.get_by_role("link").get_attribute("href")).query)
        assert target.get("code") == [code] and target.get("date") == ["2026-11-26"], target


@contextmanager
def same_document(page):
    """An inner iframe, a replaced masthead, and an ordinary full navigation each fail independently."""
    documents = []

    def requested(request):
        if request.resource_type == "document":
            documents.append(request.url)

    page.evaluate("() => { window.__initialMasthead = document.querySelector('.masthead'); }")
    page.on("request", requested)
    try:
        yield
        assert not documents, documents
        expect(page.locator("iframe")).to_have_count(0)
        assert page.evaluate("Boolean(window.__initialMasthead && window.__initialMasthead === document.querySelector('.masthead'))"), page.url
    finally:
        page.remove_listener("request", requested)


def accept_report_paths(page, device, chrome):
    current, older = "2026-11-26", "2026-11-18"
    picker = page.locator("#report-date")
    with same_document(page):
        multi = page.get_by_role("navigation", name="股票異動篩選").get_by_role("link", name="多檔調整")
        multi.click()
        expect(multi).to_have_attribute("aria-current", "true")
        nav(page, "持股日報").click()
        assert_report_shell(page, chrome, current)
        app_route(page, "report", current)
        page.screenshot(path=ARTIFACTS / f"{device[0]}-report.png", animations="disabled")
        read_static_fund(page, current)

        fund = page.locator("#etf-00981A")
        stock = fund.get_by_role("table", name="兩次揭露間的持股異動").get_by_role("link", name=re.compile("緯創"))
        stock.scroll_into_view_if_needed()
        before = page.evaluate("window.scrollY")
        stock.click()
        expect(page.locator(".detail-header h1")).to_contain_text("3231")
        assert app_route(page, "stock", current).get("code") == ["3231"]
        page.go_back()
        expect(stock).to_be_focused()
        expect(fund).to_have_js_property("open", True)
        page.wait_for_function("y => Math.abs(window.scrollY - y) <= 5", arg=before)
        app_route(page, "report", current)
        page.go_back()
        expect(multi).to_have_attribute("aria-current", "true")
        assert app_route(page, "overview", current).get("filter") == ["multi"]

        nav(page, "歷史報表").click()
        page.get_by_label("報表月份").select_option(older[:7])
        page.get_by_role("button", name="篩選", exact=True).click()
        entry = page.get_by_role("table", name="歷史報表").get_by_role("row").filter(has_text=older)
        entry.get_by_role("link", name="開啟日報").click()
        assert_report_shell(page, chrome, older)
        app_route(page, "report", older)
        read_static_fund(page, older)
        page.screenshot(path=ARTIFACTS / f"{device[0]}-open.png", animations="disabled")

        page.locator("#open-search").click()
        dialog = page.get_by_role("dialog", name="搜尋股票或 ETF")
        expect(dialog).to_be_visible()
        dialog.get_by_role("searchbox").fill("00404A")
        expect(dialog.get_by_role("link", name=re.compile("00404A"))).to_be_visible()
        dialog.get_by_role("button", name="關閉").click()
        app_route(page, "report", older)
        picker.select_option(current)
        assert_report_shell(page, chrome, current)
        app_route(page, "report", current)
        picker.select_option(older)
        assert_report_shell(page, chrome, older)
        nav(page, "市場總覽").click()
        ready(page)
        app_route(page, "overview", older)
        expect(page.locator("#edition")).to_contain_text("歷史報表")
        page.get_by_role("link", name="前往最新一期").click()
        ready(page)
        expect(page.locator("#edition")).to_contain_text("最新一期")
        assert picker.input_value() == picker.locator("option").first.get_attribute("value")


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


def accept_dark(page, base, device):
    date = "2026-11-26"
    page.goto(base + f"index.html?date={date}")
    ready(page)
    assert_theme(page, "dark")
    controls_fit(page)
    dark_chrome = site_chrome(page)
    page.screenshot(path=ARTIFACTS / f"{device[0]}-home-dark.png", animations="disabled")
    nav(page, "持股日報").click()
    assert_report_shell(page, dark_chrome, date)
    assert_theme(page, "dark")
    page.screenshot(path=ARTIFACTS / f"{device[0]}-report-dark.png", animations="disabled")
    read_static_fund(page, date)
    print_on_white(page)

    light = page.get_by_role("button", name="白天模式", exact=True)
    dark = page.get_by_role("button", name="夜間模式", exact=True)
    light.click()
    assert_theme(page, "light")
    page.reload()
    ready(page)
    assert_theme(page, "light")
    app_route(page, "report", date)
    with same_document(page):
        nav(page, "市場總覽").click()
        ready(page)
        assert_theme(page, "light")
        dark.click()
        page.emulate_media(color_scheme="light")
        nav(page, "持股日報").click()
        assert_report_shell(page, dark_chrome, date)
        assert_theme(page, "dark")

    page.goto(base + f"report_{date}.html#etf-00981A")
    ready(page)
    assert_report_shell(page, dark_chrome, date)
    assert_theme(page, "dark")
    expect(page.locator("#etf-00981A")).to_be_in_viewport()
    with same_document(page):
        read_static_fund(page, date)
        detail = page.locator("#etf-00981A .report-fund-body").get_by_role("link", name=re.compile("開啟 00981A"))
        detail.click()
        expect(page.locator(".detail-header h1")).to_contain_text("00981A")
        assert app_route(page, "etf", date).get("code") == ["00981A"]
        page.go_back()
        expect(detail).to_be_focused()
        expect(page.locator("#etf-00981A")).to_have_js_property("open", True)
        assert urlparse(page.url).fragment == "etf-00981A", page.url
        light.click()
        assert_theme(page, "light")


def accept_report_failures(page, base):
    date = "2026-11-18"
    pattern = f"**/report_{date}.html"
    page.route(pattern, lambda route: route.fulfill(status=503, body="temporary"))
    page.goto(base + f"index.html?date={date}&view=report")
    retry = page.get_by_role("button", name="重新載入")
    expect(retry).to_be_visible()
    direct = page.get_by_role("link", name="直接開啟日報")
    assert urlparse(direct.evaluate("el => el.href")).path.endswith(f"/report_{date}.html")
    page.unroute(pattern)
    retry.click()
    expect(page.locator("#daily-report")).to_have_attribute("data-report-date", date)

    # Hold the older response until the next edition has actually appeared.
    page.evaluate("""() => {
        const originalFetch = window.fetch.bind(window);
        let release;
        const gate = new Promise(resolve => { release = resolve; });
        window.__slowReport = {release, waiting: false};
        window.fetch = async (input, ...options) => {
            const response = await originalFetch(input, ...options);
            const url = new URL(input instanceof Request ? input.url : input, location.href);
            if (url.pathname.endsWith('/report_2026-11-17.html')) {
                await response.clone().text();
                window.__slowReport.waiting = true;
                await gate;
            }
            return response;
        };
    }""")
    picker = page.locator("#report-date")
    picker.select_option("2026-11-17")
    page.wait_for_function("window.__slowReport.waiting")
    picker.select_option("2026-11-26")
    expect(page.locator("#daily-report")).to_have_attribute("data-report-date", "2026-11-26")
    page.evaluate("""async () => {
        window.__slowReport.release();
        await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    }""")
    ready(page)
    expect(picker).to_have_value("2026-11-26")
    expect(page.locator("#daily-report")).to_have_attribute("data-report-date", "2026-11-26")
    app_route(page, "report", "2026-11-26")

    for date, blocked in (("2026-11-18", "**/reports_index.json"), ("2026-11-26", "**/data_2026-11-26.json")):
        failed = []

        def unavailable(route):
            failed.append(route.request.url)
            route.fulfill(status=503, body="temporary")

        page.route(blocked, unavailable)
        page.goto(base + f"report_{date}.html", wait_until="networkidle")
        expect(page.locator("#daily-report")).to_have_attribute("data-report-date", date)
        expect(page.get_by_role("heading", level=1)).to_have_text("持股日報")
        if blocked.endswith(f"data_{date}.json"):
            page.locator("#open-search").click()
            dialog = page.get_by_role("dialog", name="搜尋股票或 ETF")
            dialog.get_by_role("searchbox").fill("緯創")
            expect(dialog.get_by_role("button", name="重試搜尋")).to_be_visible()
            dialog.get_by_role("button", name="關閉").click()
        assert failed, blocked
        read_static_fund(page, date)
        page.unroute(blocked)


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
    assert_theme(page, "light")
    controls_fit(page)
    page.screenshot(path=ARTIFACTS / f"{device[0]}-home.png", animations="disabled")
    chrome = site_chrome(page)
    accept_report_paths(page, device, chrome)
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


def accept_without_js(page, base):
    page.goto(base + "index.html")
    chrome = site_chrome(page)
    for date in ("2026-11-18", "2026-11-26"):
        page.goto(base + f"report_{date}.html")
        assert_report_shell(page, chrome, date, interactive=False)
        assert_theme(page, "dark", interactive=False)
        read_static_fund(page, date)
        if date == "2026-11-26":
            read_global_fund(page)
            print_on_white(page)
        nav(page, "市場總覽").click()
        app_route(page, "overview", date)


if __name__ == "__main__":
    ARTIFACTS.mkdir(exist_ok=True)
    # The prefix matches a project Pages URL, including nested relative resource links.
    handler = partial(PagesHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, sync_playwright() as playwright:
        threading.Thread(target=server.serve_forever, daemon=True).start()
        browser = playwright.chromium.launch(executable_path=shutil.which("google-chrome"), headless=True)
        base = f"http://127.0.0.1:{server.server_port}/docs/"
        try:
            for device, size in [("mobile", {"width": 390, "height": 844}), ("desktop", {"width": 1440, "height": 960})]:
                options = dict(viewport=size, locale="zh-TW", reduced_motion="reduce",
                               is_mobile=device == "mobile", has_touch=device == "mobile")
                with browser.new_page(**options, color_scheme="light") as page:
                    accept(page, base, device)
                    if device == "desktop":
                        accept_report_failures(page, base)
                with browser.new_page(**options, color_scheme="dark") as page:
                    accept_dark(page, base, device)
                with browser.new_page(**options, color_scheme="dark", java_script_enabled=False) as page:
                    accept_without_js(page, base)
            with browser.new_page(viewport={"width": 320, "height": 720}, locale="zh-TW", reduced_motion="reduce",
                                  color_scheme="dark", is_mobile=True, has_touch=True) as narrow:
                narrow.goto(base + "index.html?date=2026-11-26&view=report")
                ready(narrow)
                controls_fit(narrow)
                assert_theme(narrow, "dark")
                narrow.get_by_role("button", name="白天模式").click()
                nav(narrow, "市場總覽").click()
                ready(narrow)
                controls_fit(narrow)
                assert_theme(narrow, "light")
        finally:
            browser.close()
            server.shutdown()
