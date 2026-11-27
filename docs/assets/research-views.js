import { snapshotChanges } from './market-data.js';

const changeLabels = new Map([
    ['added', '新增'], ['removed', '移除'], ['increased', '增持'], ['decreased', '減持'],
]);
const statusLabels = new Map([
    ['daily', '單日可比'], ['interval', '跨期比較'], ['late', '補揭露'],
    ['stale', '沿用持股'], ['first', '缺比較基準'], ['unknown', '比較期間未確認'],
]);
const byCode = (a, b) => a.code.localeCompare(b.code, 'en');

function route(ctx, view, values = {}) {
    return ctx.escape(ctx.href({
        view, code: null, tab: null, kind: null, first: null, second: null,
        from: null, scope: null, month: null, page: null, ...values,
    }));
}

function entity(ctx, type, item, values = {}) {
    return `<a class="research-entity" href="${route(ctx, type, { code: item.code, ...values })}">
        <strong>${ctx.escape(item.name || item.code)}</strong><span class="symbol">${ctx.escape(item.code)}</span></a>`;
}

function saved(ctx, type, code) {
    return ctx.watch.some(item => item.type === type && item.code === code);
}

function watchButton(ctx, type, item) {
    const active = saved(ctx, type, item.code);
    return `<button type="button" class="button research-watch" aria-pressed="${active}"
        aria-label="${active ? '取消追蹤' : '追蹤'} ${ctx.escape(item.name || item.code)}"
        data-watch-type="${type}" data-watch-code="${ctx.escape(item.code)}"
        data-watch-name="${ctx.escape(item.name || item.code)}">${active ? '已追蹤' : '＋ 追蹤'}</button>`;
}

function dateText(ctx, date) {
    return date ? `<time datetime="${ctx.escape(date)}">${ctx.escape(date)}</time>` : '未提供';
}

function dateSpan(ctx, before, after) {
    if (!before && !after) return '日期未提供';
    if (!before) return `起日未確認 → ${dateText(ctx, after)}`;
    return `${dateText(ctx, before)} → ${dateText(ctx, after)}`;
}

function quantity(ctx, number, item, signed = false) {
    if (!Number.isFinite(number)) return '—';
    const color = signed && number !== 0 ? (number > 0 ? 'up' : 'down') : '';
    return `<span class="research-number ${color}">${ctx.escape(ctx.format(number, signed))} ${ctx.escape(ctx.unit(item.market || item.code))}</span>`;
}

function weight(ctx, value) {
    return Number.isFinite(value) ? `${ctx.escape(ctx.format(value))}%` : '—';
}

function table(ctx, label, headers, rows, className = '') {
    return `<div class="table-wrap research-table-wrap"><table class="data-table research-table ${className}" aria-label="${ctx.escape(label)}">
        <thead><tr>${headers.map(header => `<th scope="col">${ctx.escape(header)}</th>`).join('')}</tr></thead>
        <tbody>${rows.map(cells => `<tr>${cells.map((cell, i) => i === 0
            ? `<th scope="row">${cell}</th>`
            : `<td data-field="${ctx.escape(headers[i])}">${cell}</td>`).join('')}</tr>`).join('')}</tbody>
    </table></div>`;
}

function empty(message) {
    return `<p class="empty-state">${message}</p>`;
}

function panel(title, content, action = '', id = '') {
    return `<section class="panel research-panel"${id ? ` id="${id}" tabindex="-1"` : ''}><div class="section-head"><h2>${title}</h2>${action}</div>${content}</section>`;
}

function header(title, description, action = '') {
    return `<header class="detail-header research-header"><div><h1>${title}</h1><p class="muted">${description}</p></div>${action}</header>`;
}

function segments(ctx, items, label) {
    return `<nav class="segmented research-segments" aria-label="${ctx.escape(label)}">${items.map(item =>
        `<a class="${item.active ? 'active' : ''}" ${item.active ? 'aria-current="true"' : ''} href="${item.url}">${ctx.escape(item.label)}</a>`
    ).join('')}</nav>`;
}

function rangeCount(ctx) {
    const number = Number(ctx.params.get('range'));
    return number === 5 || number === 20 ? number : 1;
}

function rangeLinks(ctx, view, code) {
    return segments(ctx, [1, 5, 20].map(count => ({
        label: count === 1 ? '單期' : `近 ${count} 期`, active: rangeCount(ctx) === count,
        url: route(ctx, view, { code, range: count }),
    })), '異動紀錄期間');
}

function options(ctx, choices, selected) {
    return choices.map(([value, label]) =>
        `<option value="${ctx.escape(value)}"${value === selected ? ' selected' : ''}>${ctx.escape(label)}</option>`
    ).join('');
}

function fundOptions(ctx, selected) {
    const choices = ctx.day.funds.map(fund => [fund.code, `${fund.code} ${fund.name}`]);
    if (selected && !choices.some(([code]) => code === selected)) {
        choices.unshift([selected, `${selected}（本期未收錄）`]);
    }
    return options(ctx, choices, selected);
}

function compareDatesLink(ctx, fund) {
    return `<a class="button" href="${route(ctx, 'compare', { kind: 'dates', first: fund.code })}">比較兩期</a>`;
}

function changeLabel(kind) {
    return changeLabels.get(kind) || '持股調整';
}

function disclosureStatus(fund) {
    const status = statusLabels.get(fund.status) || '資料狀態未知';
    return fund.status === 'late' ? `${status} · ${statusLabels.get(fund.comparison) || '比較期間未確認'}` : status;
}

function pageOf(ctx, records, size, pageURL) {
    const pages = Math.max(1, Math.ceil(records.length / size));
    const requested = Number(ctx.params.get('page'));
    const page = Number.isInteger(requested) ? Math.max(1, Math.min(pages, requested)) : 1;
    const controls = pages > 1 ? `<nav class="research-pager" aria-label="清單分頁">
        ${page > 1 ? `<a class="button" href="${pageURL(page - 1)}">上一頁</a>` : ''}
        <span>第 ${page}／${pages} 頁，共 ${records.length} 筆</span>
        ${page < pages ? `<a class="button" href="${pageURL(page + 1)}">下一頁</a>` : ''}</nav>` : '';
    return { visible: records.slice((page - 1) * size, page * size), controls };
}

// A report may contain a late disclosure. Keep its source window visible and
// count the same disclosure only once even when older reports repeated it.
async function historyFor(ctx, type, code) {
    const count = rangeCount(ctx);
    let period = { days: [ctx.day], dates: [ctx.day.date], missing: [], stocks: ctx.day.stocks };
    if (count > 1) {
        period = ctx.period?.date === ctx.day.date && ctx.period.requested === count
            ? ctx.period : await ctx.getPeriod(ctx.day.date, count);
    }
    const seen = new Set();
    const events = [];
    const priorHolders = new Map();
    const baselineFailures = new Set();
    for (const day of period.days) {
        for (const failed of day.missing || []) baselineFailures.add(failed);
        for (const fund of day.funds) {
            if (type === 'etf' && fund.code !== code) continue;
            if (type === 'stock' && day.date !== ctx.day.date && fund.date) {
                const holding = fund.holdings.find(item => item.code === code);
                const recorded = priorHolders.get(fund.code);
                if (holding && (!recorded || recorded.fund.date < fund.date)) {
                    priorHolders.set(fund.code, { fund, holding, reportDate: day.date });
                }
            }
            if (fund.status === 'stale' || fund.status === 'first') continue;
            for (const change of fund.changes) {
                if (type === 'stock' && change.code !== code) continue;
                // Undated old records can be inspected in the selected report
                // without being presented as multiple dated historical events.
                if (!fund.date && day.date !== ctx.day.date) continue;
                const key = JSON.stringify([fund.code, fund.date || day.date, change.code]);
                if (seen.has(key)) continue;
                seen.add(key);
                events.push({ fund, change, reportDate: day.date });
            }
        }
    }
    return { dates: period.dates, missing: period.missing, baselineFailures: [...baselineFailures], events,
        aggregates: period.stocks, priorHolders: [...priorHolders.values()] };
}

function historyNote(ctx, history) {
    const { dates, missing, baselineFailures } = history;
    const span = dates.length > 1 ? dateSpan(ctx, dates.at(-1), dates[0]) : dateText(ctx, dates[0]);
    const notes = [`報表範圍 ${span}，已取得 ${dates.length - missing.length}／${dates.length} 期。`];
    if (missing.length) notes.push(`未能讀取 ${ctx.escape(missing.join('、'))}。`);
    if (baselineFailures.length) notes.push(`部分比較基準未能讀取（${ctx.escape(baselineFailures.join('、'))}）。`);
    if (dates.length < rangeCount(ctx)) notes.push(`索引內可回溯 ${dates.length} 期。`);
    const retry = missing.length || baselineFailures.length ? ' <button type="button" class="button" data-retry>重新載入</button>' : '';
    return `<p class="research-note muted">${notes.join(' ')}${retry}</p>`;
}

function eventsTable(ctx, events, type) {
    const isFund = type === 'etf';
    const code = ctx.params.get('code');
    const { visible, controls } = pageOf(ctx, events, 20, page => route(ctx, type, { code, page }));
    const rows = visible.map(({ fund, change, reportDate }) => {
        const window = dateSpan(ctx, fund.previousDate, fund.date);
        const note = fund.status === 'daily' ? '' : `<small class="research-sub">${disclosureStatus(fund)} · 收錄 ${dateText(ctx, reportDate)}</small>`;
        const atEvent = { date: reportDate, range: 1 };
        return [
            isFund ? entity(ctx, 'stock', change, atEvent) : entity(ctx, 'etf', fund, atEvent),
            changeLabel(change.kind), change.rounded ? '低於報表精度' : quantity(ctx, change.delta, change, true),
            quantity(ctx, change.old, change), quantity(ctx, change.new, change),
            `${window}${note}`,
        ];
    });
    return table(ctx, '持股異動紀錄', [isFund ? '股票' : 'ETF', '異動', '持股增減', '前次持股', '本次持股', '持股資料日'], rows, 'research-events') + controls;
}

function fundEmptyChanges(fund) {
    if (fund.status === 'stale') return '本期沿用既有持股，沒有新揭露可供比較。';
    if (fund.status === 'first' || fund.comparison === 'first') return '這是首份可得持股，缺少較早的快照作為比較基準。';
    if (fund.comparison === 'unknown' || !fund.hasHoldings) return '缺少可核對的持股或比較期間，無法判定持股是否調整。';
    return '兩次可比較的揭露之間，持股數量沒有異動。';
}

async function etfView(ctx) {
    const code = ctx.params.get('code') || '';
    const fund = ctx.day.funds.find(item => item.code === code);
    if (!fund) {
        return header('ETF 明細', `報表日 ${dateText(ctx, ctx.day.date)}`) +
            panel('選擇 ETF', (code ? empty(`這份報表未收錄 ${ctx.escape(code)}。`) : '') +
                `<a class="button" href="${route(ctx, 'funds')}">查看本期 ETF 清單</a>`);
    }
    const showHoldings = ctx.params.get('tab') === 'holdings';
    const navigation = segments(ctx, [
        { label: '持股異動', active: !showHoldings, url: route(ctx, 'etf', { code }) },
        { label: '完整持股', active: showHoldings, url: route(ctx, 'etf', { code, tab: 'holdings' }) },
    ], 'ETF 明細');
    const actions = `<div class="research-actions">${compareDatesLink(ctx, fund)}
        <a class="button" href="${route(ctx, 'compare', { kind: 'funds', first: code })}">與其他 ETF 比較</a></div>`;
    const title = `${ctx.escape(fund.name)} <span class="symbol">${ctx.escape(code)}</span>`;
    const source = fund.previousDate && fund.status !== 'stale'
        ? `持股比較 ${dateSpan(ctx, fund.previousDate, fund.date)}` : `持股資料日 ${dateText(ctx, fund.date)}`;
    const metadata = `報表日 ${dateText(ctx, ctx.day.date)} · ${source} · ${disclosureStatus(fund)}`;
    const top = header(title, metadata, watchButton(ctx, 'etf', fund)) + navigation;
    if (showHoldings) {
        const holdings = [...fund.holdings].sort((a, b) => (b.weight ?? -1) - (a.weight ?? -1) || byCode(a, b));
        const { visible, controls } = pageOf(ctx, holdings, 20, page => route(ctx, 'etf', { code, tab: 'holdings', page }));
        const rows = visible.map(item => [entity(ctx, 'stock', item), quantity(ctx, item.lots, item), weight(ctx, item.weight)]);
        return top + panel('完整持股', fund.hasHoldings
            ? `<p class="research-note muted">來源日 ${dateText(ctx, fund.date)} · ${holdings.length} 檔，依權重排列。</p>` +
                table(ctx, '完整持股', ['股票', '持股數量', '權重'], rows) + controls
            : empty('這份報表沒有可供查詢的完整持股清單。'), actions);
    }
    const history = await historyFor(ctx, 'etf', code);
    const counts = new Map();
    for (const { change } of history.events) counts.set(change.kind, (counts.get(change.kind) || 0) + 1);
    const kinds = ['added', 'removed', 'increased', 'decreased'];
    if (counts.has('adjusted')) kinds.push('adjusted');
    const countsText = history.events.length
        ? `<p class="research-note">${kinds.map(kind => `${changeLabel(kind)} ${counts.get(kind) || 0} 筆`).join('　')}</p>` : '';
    const message = rangeCount(ctx) === 1 ? fundEmptyChanges(fund) : '已讀取的這段期間沒有可列出的持股異動紀錄。';
    const periodNets = rangeCount(ctx) > 1 ? netByStock(ctx, history, code) : '';
    return top + panel('持股異動', rangeLinks(ctx, 'etf', code) + historyNote(ctx, history) + countsText + periodNets +
        (history.events.length ? eventsTable(ctx, history.events, 'etf') : empty(message)), actions);
}

function holdersOf(day, code) {
    return day.funds.flatMap(fund => {
        const holding = fund.holdings.find(item => item.code === code);
        return holding ? [{ fund, holding }] : [];
    }).sort((a, b) => (b.holding.weight ?? -1) - (a.holding.weight ?? -1) || byCode(a.fund, b.fund));
}

function netByStock(ctx, history, fundCode) {
    const rows = [];
    for (const stock of history.aggregates) {
        const flow = stock.flows.find(item => item.fundCode === fundCode);
        if (flow) rows.push([entity(ctx, 'stock', stock), periodQuantity(ctx, flow.delta, stock, flow.rounded)]);
    }
    if (!rows.length) return '';
    return `<details class="research-disclosure"><summary>依股票查看可核對的單日淨增減（${rows.length} 檔）</summary>
        ${table(ctx, '期間逐股持股淨增減', ['股票', '持股淨增減'], rows)}</details>`;
}

function periodQuantity(ctx, value, stock, rounded) {
    const approximation = rounded ? '<small class="research-sub">含低於報表精度的異動</small>' : '';
    return quantity(ctx, value, stock, true) + approximation;
}

async function stockView(ctx) {
    const code = (ctx.params.get('code') || '').trim().replace(/\s+/g, ' ').toUpperCase();
    if (!code) return header('個股反查', '從搜尋輸入股票名稱或完整代號，即可查詢持有它的 ETF。');
    const holders = holdersOf(ctx.day, code);
    const history = await historyFor(ctx, 'stock', code);
    const stock = holders[0]?.holding || history.events[0]?.change || history.priorHolders[0]?.holding ||
        ctx.watch.find(item => item.type === 'stock' && item.code === code);
    const title = stock?.name && stock.name !== code
        ? `${ctx.escape(stock.name)} <span class="symbol">${ctx.escape(code)}</span>` : ctx.escape(code);
    const actions = `<div class="research-actions"><a class="button" href="#stock-changes">查看異動紀錄</a>
        ${stock ? watchButton(ctx, 'stock', stock) : ''}</div>`;
    const top = header(title, `報表日 ${dateText(ctx, ctx.day.date)} · 依各 ETF 最近一次揭露分別列示。`, actions);
    const rows = holders.map(({ fund, holding }) => [
        entity(ctx, 'etf', fund), weight(ctx, holding.weight), quantity(ctx, holding.lots, holding),
        dateText(ctx, fund.date) + (fund.date && fund.date < ctx.day.date ? '<small class="research-sub">早於報表日</small>' : ''),
    ]);
    const currentCodes = new Set(holders.map(({ fund }) => fund.code));
    const previousRows = history.priorHolders.filter(({ fund }) => !currentCodes.has(fund.code)).map(({ fund, holding, reportDate }) => [
        entity(ctx, 'etf', fund, { date: reportDate, tab: 'holdings' }), dateText(ctx, fund.date),
        quantity(ctx, holding.lots, holding), weight(ctx, holding.weight),
    ]);
    const previous = previousRows.length ? `<details class="research-disclosure"><summary>曾揭露持有、本期未見（${previousRows.length} 檔）</summary>
        ${table(ctx, '期間內較早的持有紀錄', ['ETF', '最後見於持股日', '當時數量', '當時權重'], previousRows)}</details>` : '';
    const aggregate = history.aggregates.find(item => item.code === code);
    const summary = aggregate ? `<p class="research-note">可核對的單日變動合計
        <strong>${quantity(ctx, aggregate.net, aggregate, true)}</strong> · 淨增 ${aggregate.up} 檔 ETF、淨減 ${aggregate.down} 檔 ETF。
        ${aggregate.flows.some(flow => flow.rounded) ? '含低於報表精度的異動。' : ''}</p>` : '';
    const fundNets = aggregate && rangeCount(ctx) > 1 ? `<details class="research-disclosure"><summary>依 ETF 查看期間淨增減</summary>
        ${table(ctx, '期間各 ETF 持股淨增減', ['ETF', '持股淨增減'], aggregate.flows.map(flow => [
            entity(ctx, 'etf', { code: flow.fundCode, name: flow.fundName }), periodQuantity(ctx, flow.delta, aggregate, flow.rounded),
        ]))}</details>` : '';
    const holderColumns = ['ETF', '權重', '持股數量', '持股資料日'];
    const rest = rows.length > 5 ? `<details class="research-disclosure"><summary>展開其餘 ${rows.length - 5} 檔持有者</summary>
        ${table(ctx, '其他 ETF 最近揭露的持股', holderColumns, rows.slice(5))}</details>` : '';
    return top + panel(`揭露持有的 ETF（${rows.length}）`, rows.length
        ? table(ctx, '各 ETF 最近揭露的持股', holderColumns, rows.slice(0, 5)) + rest
        : empty('本期收錄的 ETF 持股中沒有這個代號。可在下方查較早的持股異動，包括移除紀錄。')) +
        panel('個股持股異動', rangeLinks(ctx, 'stock', code) + historyNote(ctx, history) + summary + fundNets + previous +
            (history.events.length ? eventsTable(ctx, history.events, 'stock') : empty('已讀取的報表中查無此股的異動紀錄。')), '', 'stock-changes');
}

function compareForm(ctx, kind, first, second, from) {
    const twoDates = kind === 'dates';
    const dates = ctx.index.map(date => [date, date]);
    const fromOptions = from && !ctx.index.includes(from) ? [[from, `${from}（未收錄）`], ...dates] : dates;
    const pickFund = (name, label, selected) =>
        `<label>${label}<select name="${name}" required>${fundOptions(ctx, selected)}</select></label>`;
    return `<form data-route class="inline-form research-form" aria-label="${twoDates ? '比較同一檔 ETF 的兩期持股' : '比較兩檔 ETF 的持股'}">
        <input type="hidden" name="view" value="compare"><input type="hidden" name="kind" value="${kind}">
        ${pickFund('first', twoDates ? 'ETF' : '第一檔 ETF', first)}
        ${twoDates
        ? `<label>起始報表<select name="from" required>${options(ctx, fromOptions, from)}</select></label>
           <label>結束報表<select name="date" required>${options(ctx, dates, ctx.day.date)}</select></label>`
        : pickFund('second', '第二檔 ETF', second)}
        <button type="submit" class="button button-primary">比較</button></form>`;
}

function holdingCell(ctx, holding) {
    return holding
        ? `${quantity(ctx, holding.lots, holding)}<small class="research-sub">權重 ${weight(ctx, holding.weight)}</small>`
        : '未列入';
}

function compareFunds(ctx, first, second) {
    if (!first || !second) return empty('所選 ETF 的持股資料未收錄在這份報表，請重新選擇。');
    if (first.code === second.code) return empty('請選擇兩檔不同的 ETF。');
    const heading = `<p class="research-note">${entity(ctx, 'etf', first)} 持股日 ${dateText(ctx, first.date)}　
        ${entity(ctx, 'etf', second)} 持股日 ${dateText(ctx, second.date)}</p>`;
    if (!first.hasHoldings || !second.hasHoldings) return heading + empty('其中一檔缺少完整持股清單，無法核對共同或獨有成分。');
    const firstStocks = new Map(first.holdings.map(stock => [stock.code, stock]));
    const secondStocks = new Map(second.holdings.map(stock => [stock.code, stock]));
    const groups = {
        common: first.holdings.filter(stock => secondStocks.has(stock.code)),
        first: first.holdings.filter(stock => !secondStocks.has(stock.code)),
        second: second.holdings.filter(stock => !firstStocks.has(stock.code)),
    };
    const scope = Object.hasOwn(groups, ctx.params.get('scope')) ? ctx.params.get('scope') : 'common';
    const tabs = segments(ctx, [
        ['common', '共同持股'], ['first', `僅 ${first.code}`], ['second', `僅 ${second.code}`],
    ].map(([key, label]) => ({
        label: `${label}（${groups[key].length}）`, active: scope === key,
        url: route(ctx, 'compare', { kind: 'funds', first: first.code, second: second.code, scope: key }),
    })), '持股範圍');
    const rows = groups[scope].sort(byCode).map(stock => [
        entity(ctx, 'stock', stock), holdingCell(ctx, firstStocks.get(stock.code)), holdingCell(ctx, secondStocks.get(stock.code)),
    ]);
    let note = '';
    if (!first.date || !second.date) note = '部分持股日未提供，以下按所選報表保存的清單比對。';
    else if (first.date !== second.date) note = '兩檔 ETF 的持股日不同，以下依各自列出的日期比較。';
    return heading + (note ? `<p class="research-note muted">${note}</p>` : '') + tabs +
        (rows.length ? table(ctx, '兩檔 ETF 的持股比較', ['股票', first.code, second.code], rows)
            : empty(scope === 'common' ? '這兩份清單沒有共同持股。' : '這個範圍沒有獨有持股。'));
}

async function compareDates(ctx, fund, from) {
    if (!fund) return empty('結束報表沒有收錄這檔 ETF，請選擇其他標的或日期。');
    if (!from || !ctx.index.includes(from) || from >= ctx.day.date) return empty('請選擇索引內的兩份報表，起始日期須早於結束日期。');
    let earlier;
    try {
        earlier = await ctx.getDay(from);
    } catch {
        return empty(`無法讀取 ${dateText(ctx, from)} 的報表。 <button type="button" class="button" data-retry>重新載入</button>`);
    }
    const previous = earlier.funds.find(item => item.code === fund.code);
    if (!previous) return empty(`起始報表 ${dateText(ctx, from)} 未收錄 ${ctx.escape(fund.code)}，請改選起點。`);
    const heading = `<p class="research-note">${entity(ctx, 'etf', fund)} · 報表日 ${dateSpan(ctx, from, ctx.day.date)}<br>
        實際持股日 <strong>${dateSpan(ctx, previous.date, fund.date)}</strong></p>`;
    if (!previous.hasHoldings || !fund.hasHoldings || !previous.date || !fund.date) {
        return heading + empty('其中一端缺少完整持股或來源日，無法計算這段期間的增減。');
    }
    if (previous.date === fund.date) return heading + empty('兩份報表沿用同一個持股日，沒有新的持股期間可以比較。');
    if (previous.date > fund.date) return heading + empty('起始持股日晚於結束持股日，請重新選擇報表。');
    const before = new Map(previous.holdings.map(stock => [stock.code, stock]));
    const after = new Map(fund.holdings.map(stock => [stock.code, stock]));
    const changes = snapshotChanges(previous.holdings, fund.holdings);
    const rows = changes.sort(byCode).map(change => [
        entity(ctx, 'stock', change), changeLabel(change.kind), quantity(ctx, change.delta, change, true),
        holdingCell(ctx, before.get(change.code)), holdingCell(ctx, after.get(change.code)),
    ]);
    const summary = `<p class="research-note muted">起點 ${before.size} 檔、終點 ${after.size} 檔，共 ${rows.length} 檔成分或股數改變。權重依各端點揭露。</p>`;
    return heading + summary + (rows.length
        ? table(ctx, '同一檔 ETF 兩期持股', ['股票', '異動', '期間增減', '起點持股', '終點持股'], rows)
        : empty('兩個持股日的成分與股數均相同。'));
}

async function compareView(ctx) {
    const kind = ctx.params.get('kind') === 'dates' ? 'dates' : 'funds';
    const first = ctx.params.get('first') || ctx.params.get('code') || ctx.day.funds[0]?.code || '';
    const second = ctx.params.get('second') || ctx.day.funds.find(fund => fund.code !== first)?.code || '';
    const from = ctx.params.get('from') || ctx.index.find(date => date < ctx.day.date) || '';
    const tabs = segments(ctx, [
        { label: '兩檔 ETF', active: kind === 'funds', url: route(ctx, 'compare', { kind: 'funds', first, second }) },
        { label: '同檔兩期', active: kind === 'dates', url: route(ctx, 'compare', { kind: 'dates', first, from }) },
    ], '比較方式');
    const firstFund = ctx.day.funds.find(fund => fund.code === first);
    const content = kind === 'dates'
        ? await compareDates(ctx, firstFund, from)
        : compareFunds(ctx, firstFund, ctx.day.funds.find(fund => fund.code === second));
    return header('持股比較', `報表日 ${dateText(ctx, ctx.day.date)}`) + tabs +
        panel(kind === 'dates' ? '比較同一檔 ETF 的兩期持股' : '比較兩檔 ETF 的成分股',
            compareForm(ctx, kind, first, second, from) + content);
}

function historyView(ctx) {
    const month = ctx.params.get('month') || '';
    const months = [...new Set(ctx.index.map(date => date.slice(0, 7)))];
    const choices = [['', '全部月份'], ...months.map(value => [value, value.replace('-', ' / ')])];
    if (month && !months.includes(month)) choices.push([month, `${month}（無報表）`]);
    const dates = ctx.index.filter(date => !month || date.slice(0, 7) === month);
    const { visible, controls } = pageOf(ctx, dates, 12, page => route(ctx, 'history', { month: month || null, page }));
    const filter = `<form data-route class="inline-form research-form">
        <input type="hidden" name="view" value="history"><input type="hidden" name="page" value="1">
        <label>報表月份<select name="month">${options(ctx, choices, month)}</select></label>
        <button class="button" type="submit">篩選</button></form>`;
    const rows = visible.map(date => [
        dateText(ctx, date),
        `<a href="${route(ctx, 'overview', { date, range: 1 })}">同日總覽</a>`,
        `<a href="${route(ctx, 'report', { date })}">開啟日報</a>`,
    ]);
    return header('歷史報表', `索引收錄 ${ctx.index.length} 期，可開啟當期總覽或保存的完整日報。`) +
        panel('已發布報表', filter + (rows.length
            ? table(ctx, '歷史報表', ['報表日期', '異動總覽', '完整日報'], rows) + controls
            : empty('選定月份沒有已發布的報表。')));
}

function watchView(ctx) {
    const head = header('我的追蹤', `這個瀏覽器共追蹤 ${ctx.watch.length} 個標的。以下依選定報表 ${dateText(ctx, ctx.day.date)} 顯示。`);
    if (!ctx.watch.length) {
        return head + panel('追蹤清單', empty('打開 ETF 或股票明細，選擇「＋ 追蹤」，下次就能在這裡直接查看。') +
            `<div class="research-actions"><a class="button" href="${route(ctx, 'funds')}">查看 ETF 清單</a>
            <a class="button" href="${route(ctx, 'overview')}">查看股票異動</a></div>`);
    }
    const funds = [];
    const stocks = [];
    for (const item of ctx.watch) {
        if (item.type === 'etf') {
            const fund = ctx.day.funds.find(fund => fund.code === item.code);
            const state = fund ? disclosureStatus(fund) : '本期未收錄';
            funds.push([
                entity(ctx, 'etf', fund || item), state, dateText(ctx, fund?.date),
                fund && (fund.changes.length || ['daily', 'interval'].includes(fund.comparison) && fund.status !== 'stale')
                    ? `${fund.changes.length} 筆` : '—',
                watchButton(ctx, 'etf', item),
            ]);
        } else if (item.type === 'stock') {
            const holders = holdersOf(ctx.day, item.code);
            const current = holders.filter(({ fund }) => fund.date === ctx.day.date).length;
            const stock = ctx.day.stocks.find(row => row.code === item.code);
            const dates = [...new Set(holders.map(({ fund }) => fund.date).filter(Boolean))].sort();
            const holderDates = dates.length > 1 ? dateSpan(ctx, dates[0], dates.at(-1)) : dateText(ctx, dates[0]);
            stocks.push([
                entity(ctx, 'stock', holders[0]?.holding || stock || item),
                `${holders.length} 檔<small class="research-sub">${current} 檔為當日資料</small>`,
                holderDates, stock ? periodQuantity(ctx, stock.net, stock, stock.flows.some(flow => flow.rounded)) : '無可核對的單日異動',
                watchButton(ctx, 'stock', item),
            ]);
        }
    }
    return head +
        (funds.length ? panel(`追蹤的 ETF（${funds.length}）`, table(ctx, '追蹤的 ETF', ['ETF', '本期狀態', '持股資料日', '持股異動', '追蹤'], funds)) : '') +
        (stocks.length ? panel(`追蹤的股票（${stocks.length}）`, table(ctx, '追蹤的股票', ['股票', '揭露持有的 ETF', '各基金持股日', '當日持股淨增減', '追蹤'], stocks)) : '');
}

export async function renderResearch(view, ctx) {
    switch (view) {
        case 'etf': return etfView(ctx);
        case 'stock': return stockView(ctx);
        case 'compare': return compareView(ctx);
        case 'history': return historyView(ctx);
        case 'watch': return watchView(ctx);
        default: return '';
    }
}
