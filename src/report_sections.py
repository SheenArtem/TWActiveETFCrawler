"""Render the printable, script-free body of a published holdings report."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from html import escape
from math import isfinite

from .stock_markets import is_foreign, lot_unit


def _value(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value) else None


def _number(value, signed=False, digits=3):
    if _value(value) is None:
        return '—'
    prefix = '+' if signed and value > 0 else ''
    return prefix + f'{value:,.{digits}f}'.rstrip('0').rstrip('.')


def _weight(value):
    # Source weights can carry six decimal places, even where lots are rounded.
    return _number(value, digits=6) + '%' if _value(value) is not None else '—'


def _quantity(value, unit, signed=False):
    if _value(value) is None:
        return '—'
    return f'{_number(value, signed)} {unit}'


def _date(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (ValueError, TypeError):
        return None


def _symbol(report_link, view, code, name):
    label = escape(str(name or code or '未提供'))
    if not code:
        return label
    ticker = escape(str(code))
    text = f'<span class="ticker">{ticker}</span>'
    if name and name != code:
        text = f'<span>{label}</span>{text}'
    return f'<a class="symbol" href="{report_link(view, code)}">{text}</a>'


def _direction(value):
    if value is None or value == 0:
        return ''
    return 'up' if value > 0 else 'down'


def _table(caption, columns, rows):
    head = ''.join(f'<th scope="col" class="{style}">{label}</th>' if style else f'<th scope="col">{label}</th>'
                   for label, style in columns)
    body = '\n'.join(rows)
    return (f'<div class="report-table-wrap" role="region" aria-label="{caption}" tabindex="0">'
            f'<table class="data-table"><caption>{caption}</caption>\n'
            f'<thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table></div>')


@dataclass
class _Change:
    stock: dict
    action: str
    before: float | None
    after: float | None
    delta: float | None


def _lots(stock, shares_field, lots_field):
    shares = _value(stock.get(shares_field))
    return shares / 1000 if shares is not None else _value(stock.get(lots_field))


def _fund_changes(entry):
    changes = []
    for group in ('added', 'removed', 'modified'):
        for stock in entry.get(group) or []:
            if group == 'added':
                before, after = 0, _lots(stock, 'new_shares', 'lots')
                action, delta = '新增', after
            elif group == 'removed':
                before, after = _lots(stock, 'old_shares', 'lots'), 0
                action, delta = '移除', -before if before is not None else None
            else:
                before = _lots(stock, 'old_shares', 'old_lots')
                after = _lots(stock, 'new_shares', 'new_lots')
                raw_delta = _value(stock.get('shares_diff'))
                if raw_delta is not None:
                    delta = raw_delta / 1000
                elif _value(stock.get('old_shares')) is not None and _value(stock.get('new_shares')) is not None:
                    delta = round(after - before, 3)
                else:
                    delta = _value(stock.get('diff'))
                    if (delta is None or delta == 0) and before is not None and after is not None:
                        delta = round(after - before, 3)
                # Legacy reports labelled a rounded zero as "down" even for a one-share increase.
                action = {'up': '增持', 'down': '減持', '': '方向未確認'}[_direction(delta)]
            changes.append(_Change(stock, action, before, after, delta))
    return changes


def _period(fund, stale, report_date, previous_report_date):
    end = _date(fund.get('data_date')) or _date(stale.get('data_date'))
    end = end if end and report_date and end <= report_date else None
    start = _date(fund.get('previous_data_date'))
    observed = _date(fund.get('previous_report_data_date'))
    kind = fund.get('comparison_kind')
    if kind == 'first' and end:
        label = f'{end} · 首份持股，缺比較基準'
    elif start and end and start < end:
        interval = {'daily': '相鄰交易日', 'interval': '跨期比較'}.get(kind, '交易日間隔未確認')
        label = f'{start} → {end} · {interval}'
    else:
        kind = 'unknown'
        label = f'持股日 {end or "未提供"} · 比較期間未確認'
    if stale or (end and end < report_date and end == observed):
        behind = _value(stale.get('trading_days_behind'))
        note = f'今日未更新 · 落後 {_number(behind)} 個交易日' if behind is not None else '今日未更新'
        return kind, label, note
    if end and end < report_date:
        newly_recorded = (observed and observed < end) or (
            previous_report_date and 'previous_report_data_date' in fund and fund['previous_report_data_date'] is None
        )
        return kind, label, '補揭露' if newly_recorded else '較早的持股日'
    return kind, label, ''


def _change_table(changes, report_link, legacy):
    rows = []
    for event in changes:
        code = event.stock.get('stock_code')
        unit = lot_unit(code)
        difference = _quantity(event.delta, unit, signed=True)
        if legacy and event.delta == 0:
            difference += ' <small class="muted">原報表精度</small>'
        rows.append(f'<tr><th scope="row">{_symbol(report_link, "stock", code, event.stock.get("stock_name"))}</th>'
                    f'<td>{event.action}</td><td class="num">{_quantity(event.before, unit)}</td>'
                    f'<td class="num">{_quantity(event.after, unit)}</td>'
                    f'<td class="num {_direction(event.delta)}">{difference}</td></tr>')
    return _table('兩次揭露間的持股異動', [('股票', ''), ('異動', ''), ('前期', 'num'), ('本期', 'num'), ('差額', 'num')], rows)


def _holdings_table(holdings, report_link):
    rows = []
    for stock in holdings:
        code = stock.get('stock_code')
        lots = _lots(stock, 'shares', 'lots')
        rows.append(f'<tr><th scope="row">{_symbol(report_link, "stock", code, stock.get("stock_name"))}</th>'
                    f'<td class="num">{_weight(stock.get("weight"))}</td>'
                    f'<td class="num">{_quantity(lots, lot_unit(code))}</td></tr>')
    return _table(f'完整持股 · {len(holdings)} 檔', [('成分股', ''), ('權重', 'num'), ('持有數量', 'num')], rows)


def _fund_section(fund, stale, events, report_link, data):
    code = fund['etf_code']
    kind, period, status = _period(fund, stale, _date(data.get('date')), data.get('previous_report_date'))
    legacy = (data.get('report_schema_version') or 1) < 2
    holdings = fund.get('holdings')
    foreign = sum(is_foreign(stock.get('stock_code')) for stock in holdings or [])
    info = [f'{len(holdings)} 檔成分股' if holdings is not None else '持股清單未提供']
    if foreign:
        info.append(f'含 {foreign} 檔海外成分股（單位千股）')
    if events is not None:
        info.append(f'{len(events)} 筆異動')
    tag = f'<span class="badge warn">{status}</span>' if status else ''
    if events:
        changes = _change_table(events, report_link, legacy)
    elif status.startswith('今日未更新'):
        changes = '<p class="muted">持股沿用上次揭露。</p>'
    elif kind in ('daily', 'interval') and not legacy and events is not None:
        changes = '<p class="muted">兩期持股數量相同。</p>'
    elif kind in ('first', 'unknown'):
        changes = '<p class="muted">比較基準不足，可查閱本期持股。</p>'
    else:
        changes = '<p class="muted">這份報表未列持股異動。</p>'
    holdings_html = _holdings_table(holdings, report_link) if holdings else '<p class="muted">本期無可列出的持股明細。</p>'
    return (f'<details class="fund report-fund" id="etf-{escape(code)}"><summary>'
            f'<strong>{escape(str(fund.get("etf_name") or code))} <span class="ticker">{escape(code)}</span></strong>'
            f'<span class="report-status">{period}</span>{tag}<span class="muted">{" · ".join(info)}</span></summary>'
            f'<div class="report-fund-body"><p><a href="{report_link("etf", code)}">開啟 {escape(code)} 互動明細</a></p>'
            f'{changes}{holdings_html}</div></details>')


def _distribution(rows):
    if not rows:
        return '<p class="muted">本期無可列出的基金異動分布。</p>'
    ranked = sorted(rows, key=lambda row: (-(_value(row.get('count')) or 0), str(row.get('etf_code') or '')))
    maximum = _value(ranked[0].get('count')) or 0
    bars = []
    for row in ranked:
        code = str(row.get('etf_code') or '')
        count = _value(row.get('count'))
        meter = (f'<meter aria-hidden="true" min="0" max="{maximum}" value="{count}"></meter>'
                 if count is not None and maximum > 0 else '')
        bars.append(f'<li><a href="#etf-{escape(code)}"><span class="ticker">{escape(code)}</span> '
                    f'{escape(str(row.get("etf_name") or ""))}</a>{meter}<strong>{_number(count)} 筆</strong></li>')
    first = f'<ul class="report-distribution">{"".join(bars[:5])}</ul>'
    if len(bars) > 5:
        first += (f'<details class="report-more"><summary>其餘 {len(bars) - 5} 檔 ETF</summary>'
                  f'<ul class="report-distribution">{"".join(bars[5:])}</ul></details>')
    return first


def _hot_stocks(stocks, report_link, by_stock):
    if not stocks:
        return '<p class="muted">本期無可列出的熱門調整股票。</p>'
    result = []
    for stock in stocks:
        code = str(stock.get('stock_code') or '')
        unit = lot_unit(code)
        fund_rows = []
        deltas = []
        for flow in stock.get('etf_details') or []:
            fund_code = str(flow.get('etf_code') or '')
            event = by_stock.get((fund_code, code))
            delta = event.delta if event is not None and event.delta is not None else _value(flow.get('adjustment'))
            deltas.append(delta)
            change = _quantity(delta, unit, signed=True)
            if delta == 0:
                change += ' <small class="muted">方向未確認</small>'
            current = _value(flow.get('lots'))
            if current is None:
                current = _value(flow.get('new_lots'))
            fund_rows.append(f'<tr><th scope="row">{_symbol(report_link, "etf", fund_code, flow.get("etf_name"))}</th>'
                             f'<td class="num {_direction(delta)}">{change}</td><td class="num">{_quantity(current, unit)}</td>'
                             f'<td class="num">{_weight(flow.get("weight"))}</td></tr>')
        table = (_table(f'{escape(code)} 的基金調整', [('基金', ''), ('持股增減', 'num'), ('本期持股', 'num'), ('權重', 'num')], fund_rows)
                 if fund_rows else '<p class="muted">本期未提供基金調整明細。</p>')
        count = _value(stock.get('total_adjustments'))
        net = _value(stock.get('net_change'))
        net_label = '淨增減'
        annotation = ''
        if deltas:
            up = sum(value is not None and value > 0 for value in deltas)
            down = sum(value is not None and value < 0 for value in deltas)
            directions = f'增持 {up} 檔 · 減持 {down} 檔'
            if len(deltas) > up + down:
                directions += f' · 方向未確認 {len(deltas) - up - down} 檔'
                net_label = '原報表淨增減'
            annotation = f'<p class="muted">{directions}</p>'
            if up + down == count == len(deltas):
                confirmed = round(sum(deltas), 3)
                if net is not None and round(net, 3) != confirmed:
                    annotation += f'<p class="muted">原報表彙總的淨增減為 {_quantity(net, unit, signed=True)}。</p>'
                    net = confirmed
        result.append(f'<details class="report-hot"><summary><strong>{escape(str(stock.get("stock_name") or code))} '
                      f'<span class="ticker">{escape(code)}</span></strong><span>{_number(count)} 次調整</span>'
                      f'<span class="report-quantity {_direction(net)}">{net_label} {_quantity(net, unit, signed=True)}</span></summary>'
                      f'{annotation}<p><a href="{report_link("stock", code)}">開啟 {escape(code)} 個股明細</a></p>{table}</details>')
    shown = ''.join(result[:5])
    if len(result) > 5:
        shown += (f'<details class="report-more"><summary>其餘 {len(result) - 5} 檔股票</summary>'
                  f'{"".join(result[5:])}</details>')
    return shown


def render_report_sections(data, report_link):
    """Return body sections using the supplied HTML-escaped, date-preserving link builder."""
    date_value = _date(data.get('date'))
    holdings = {row['etf_code']: row for row in data.get('etf_holdings') or []}
    details = {row['etf_code']: row for row in data.get('detailed_changes') or []}
    stale = {row['etf_code']: row for row in data.get('stale_etfs') or []}
    events = {code: _fund_changes(entry) for code, entry in details.items()}
    all_events = [event for rows in events.values() for event in rows]
    by_stock = {(code, event.stock.get('stock_code')): event for code, rows in events.items() for event in rows}
    funds = dict(holdings)
    for row in [*details.values(), *stale.values(), *(data.get('change_distribution') or [])]:
        code = row['etf_code']
        funds.setdefault(code, {'etf_code': code, 'etf_name': row.get('etf_name')})
    source_known = data.get('etf_holdings') is not None
    current = sum(bool(date_value) and _date(fund.get('data_date')) == date_value for fund in holdings.values())
    segments = ''.join('<span class="on"></span>' if i < current else '<span></span>' for i in range(len(holdings)))
    coverage = (f'<a class="coverage" href="{report_link("sources")}"><span class="coverage-label">有當日持股的 ETF</span>'
                f'<span class="coverage-number">{_number(current if source_known else None)} '
                f'<small>/ {_number(len(holdings) if source_known else None)} 檔</small></span>'
                f'<span class="coverage-more">查看來源</span><span class="coverage-meter" aria-hidden="true">{segments}</span></a>')
    summary = data.get('summary') or {}
    known_events = data.get('detailed_changes') is not None
    codes = {event.stock.get('stock_code') for event in all_events}
    published_funds = _value(summary.get('total_etfs'))
    active_count = (sum((_value(entry.get('total_changes')) or len(events[code])) > 0 for code, entry in details.items())
                    if known_events else published_funds)
    summary_note = ''
    if published_funds is not None and known_events and published_funds != active_count:
        summary_note = f'<p class="muted">原報表的基金統計為 {_number(published_funds)} 檔，當中有異動的為 {_number(active_count)} 檔。</p>'
    metrics = [
        ('有異動的 ETF', active_count, '檔基金', '#distribution'),
        ('本期持股異動', summary.get('total_changes', len(all_events) if known_events else None), '筆紀錄', '#activity'),
        ('涉及股票', len(codes - {None, ''}) if known_events else None, '檔股票', '#funds'),
    ]
    metric_html = ''.join(f'<a class="metric" href="{target}"><span>{name}</span><div class="metric-value">'
                          f'<strong>{_number(count)}</strong><small>{unit}</small></div></a>' for name, count, unit, target in metrics)
    counts = Counter(event.action for event in all_events)
    categories = [name for name in ('新增', '移除', '增持', '減持', '方向未確認') if name != '方向未確認' or counts[name]]
    groups = ''.join(f'<li><span>{name}</span><strong>{_number(counts[name] if known_events else None)} 筆</strong></li>'
                     for name in categories)
    distribution = _distribution(data.get('change_distribution') or [])
    hot = _hot_stocks(data.get('hot_stocks') or [], report_link, by_stock)
    fund_html = '\n'.join(_fund_section(fund, stale.get(code, {}), events.get(code, [] if known_events else None),
                                       report_link, data) for code, fund in funds.items())
    if not fund_html:
        fund_html = '<p class="muted">本期未提供逐檔基金資料。</p>'
    stale_note = f'<p class="note">{len(stale)} 檔 ETF 今日沒有新資料，實際持股日見各基金明細。</p>' if stale else ''
    return (f'<div class="summary-grid">{coverage}<div class="metrics">{metric_html}</div></div>'
            '<section id="activity"><div class="section-head"><h2>本期持股異動</h2><a href="#funds">查看各 ETF 持股</a></div>'
            '<p class="muted">統計依本報表收錄的異動，基金的比較起訖可能不同。</p>'
            f'{summary_note}<ul class="report-group">{groups}</ul><div class="report-analysis">'
            f'<section class="panel" id="distribution"><div class="section-head"><h3>各 ETF 異動筆數</h3></div>{distribution}</section>'
            '<section class="panel"><div class="section-head"><h3>熱門調整股票</h3></div>'
            f'<p class="muted">按既有持股的調整次數排列，最多顯示十檔。</p>{hot}</section></div></section>'
            '<section class="panel" id="funds"><div class="section-head"><h2>各 ETF 揭露與持股</h2></div>'
            f'{stale_note}{fund_html}</section>')
