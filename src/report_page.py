"""由已發布的報表內容產生可直接閱讀的靜態日報。"""
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from .report_archive import archived_display_data
from .report_sections import render_report_sections


def render_report_page(data: dict, docs_dir: Path) -> str:
    if data.get('report_schema_version', 1) < 2:
        data = archived_display_data(data, docs_dir)
    report_date = data['date']

    def report_link(view='overview', code=None):
        params = {'date': report_date}
        if view != 'overview':
            params['view'] = view
        if code is not None:
            params['code'] = code
        return 'index.html?' + escape(urlencode(params))

    nav_items = [('overview', '市場總覽'), ('funds', 'ETF 清單'), ('compare', '比較'),
                 ('history', '歷史報表'), ('watch', '我的追蹤')]
    links = []
    for view, name in nav_items:
        current = ' aria-current="location"' if view == 'history' else ''
        links.append(f'<a href="{report_link(view)}"{current}>{name}</a>')

    day = escape(report_date)
    overview = report_link()
    updated = escape(data.get('update_time') or '')
    timestamp = f'<span>報表產生於 {updated}（台北時間）</span>' if updated else ''
    return f"""<!doctype html>
<html lang="zh-Hant-TW">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#0c5148">
  <title>{day} 持股日報 · 台灣主動 ETF 觀測站</title>
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="./assets/site.css">
  <link rel="stylesheet" href="./assets/report.css">
</head>
<body class="report-page">
  <a class="skip" href="#workspace">跳到主要內容</a>
  <header class="masthead">
    <div class="topbar frame">
      <a class="brand" href="{overview}"><span class="brand-mark" aria-hidden="true"><i></i><i></i><i></i></span><span>主動 ETF 觀測站</span></a>
      <nav class="primary-nav" aria-label="主要導覽">{''.join(links)}</nav>
      <a class="search-trigger" href="{overview}#search"><span class="search-icon" aria-hidden="true"></span><span>搜尋<span class="desktop-only">股票或 ETF</span></span></a>
    </div>
  </header>
  <main class="frame" id="workspace" tabindex="-1">
    <div class="date-line">
      <span class="date-field">報表日期 <time datetime="{day}">{day}</time></span>
      <a href="{report_link('history')}">選擇其他日期</a>
    </div>
    <div class="title-row"><h1>持股日報</h1><a class="button" href="{overview}">開啟同日互動總覽</a></div>
    {render_report_sections(data, report_link)}
  </main>
  <footer class="frame footer"><span>台灣主動式 ETF 持股資料</span>{timestamp}<a href="{report_link('sources')}">資料來源與計算方式</a></footer>
</body>
</html>
"""
