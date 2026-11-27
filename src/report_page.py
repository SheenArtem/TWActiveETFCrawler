"""Render the site's shared shell and the dated, independently readable report pages."""
from html import escape
from pathlib import Path
from string import Template
from urllib.parse import urlencode

from .report_archive import archived_display_data
from .report_sections import render_report_sections


SHELL = Template((Path(__file__).parent / 'templates' / 'site.html').read_text(encoding='utf-8'))
NAVIGATION = (
    ('overview', '市場總覽'), ('report', '持股日報'), ('funds', 'ETF 清單'),
    ('compare', '比較'), ('history', '歷史報表'), ('watch', '我的追蹤'),
)


def _link(date, view='overview', code=None):
    params = {'date': date} if date else {}
    if view != 'overview':
        params['view'] = view
    if code is not None:
        params['code'] = code
    return 'index.html' + ('?' + escape(urlencode(params)) if params else '')


def _shell(*, date, title, description, content):
    links = []
    active_view = 'report' if date else 'overview'
    for view, label in NAVIGATION:
        current = ' aria-current="page"' if view == active_view else ''
        href = f'report_{escape(date)}.html' if date and view == 'report' else _link(date, view)
        links.append(f'<a href="{href}" data-view="{view}"{current}>{label}</a>')
    if date:
        day = escape(date)
        date_option = f'<option value="{day}">{day}</option>'
        static_date = f'      <noscript><span class="date-field">報表日期 <time datetime="{day}">{day}</time></span></noscript>'
        no_script = ''
    else:
        date_option = '<option>載入中</option>'
        static_date = ''
        no_script = ('    <noscript>互動查詢需要 JavaScript。可從<a href="reports_index.json">報表日期索引</a>'
                     '查閱日期，再直接開啟同目錄的 report_日期.html 日報。</noscript>')
    return SHELL.substitute(
        title=title, description=description, overview=_link(date), sources=_link(date, 'sources'),
        navigation='\n        '.join(links), date_option=date_option, static_date=static_date,
        busy='false' if date else 'true', content=content, no_script=no_script,
    )


def render_home_page():
    return _shell(
        date=None, title='每日持股異動 · 台灣主動 ETF 觀測站',
        description='逐日查詢台灣主動式 ETF 持股異動、比較基金，並核對投信揭露的持股日期。',
        content='<div class="loading requires-js" role="status">正在讀取持股報表…</div>',
    )


def render_report_page(data: dict, docs_dir: Path) -> str:
    if data.get('report_schema_version', 1) < 2:
        data = archived_display_data(data, docs_dir)
    date = data['date']
    day = escape(date)

    def report_link(view='overview', code=None):
        return _link(date, view, code)

    updated = escape(data.get('update_time') or '')
    timestamp = f'<p class="muted report-issued">報表產生於 {updated}（台北時間）</p>' if updated else ''
    report = (f'<article id="daily-report" class="report-page" data-report-date="{day}">\n'
              f'<div class="title-row"><h1>持股日報</h1></div>\n'
              f'{render_report_sections(data, report_link)}\n{timestamp}\n</article>')
    return _shell(date=date, title=f'{day} 持股日報 · 台灣主動 ETF 觀測站',
                  description=f'查閱 {day} 主動式 ETF 的持股日報、基金異動及完整持股。', content=report)
