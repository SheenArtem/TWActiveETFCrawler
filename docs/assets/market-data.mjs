// The report date selects a saved publication. A fund's two source dates determine its change.
const dataRoot = new URL('../', import.meta.url);
const requests = new Map();
const datePattern = /^\d{4}-\d{2}-\d{2}$/;

function dateValue(value) {
    return typeof value === 'string' && datePattern.test(value) ? value : null;
}

function numeric(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function amount(value) {
    // Holdings can retain individual shares (0.001 thousand), even when a report's
    // published change is rounded to two decimals.
    return Math.round(value * 1000) / 1000 || 0;
}

function readFile(filename) {
    if (!requests.has(filename)) {
        const request = fetch(new URL(filename, dataRoot).href).then(response => {
            if (!response.ok) throw new Error('無法讀取 ' + filename + '（HTTP ' + response.status + '）');
            return response.json();
        }).catch(error => {
            requests.delete(filename);
            throw error;
        });
        requests.set(filename, request);
    }
    return requests.get(filename);
}

export async function getIndex() {
    const index = await readFile('reports_index.json');
    return [...new Set(index.map(row => dateValue(row.date)).filter(Boolean))].sort().reverse();
}

function reportFile(date) {
    return readFile('data_' + date + '.json');
}

function stockIdentity(row) {
    const code = String(row.stock_code ?? '').trim().replace(/\s+/g, ' ').toUpperCase();
    const market = /^\d{4,6}[A-Z]?$/.test(code) ? 'TW'
        : code.match(/^[0-9A-Z][0-9A-Z./-]* ([A-Z]{2})$/)?.[1];
    if (!market) return null;
    return {code, name: row.stock_name || code, market};
}

function holdingsOf(rows) {
    const result = [];
    for (const row of rows || []) {
        const stock = stockIdentity(row);
        const lots = numeric(row.lots);
        if (stock && lots !== null) result.push({...stock, lots, weight: numeric(row.weight)});
    }
    return result;
}

function changesOf(entry) {
    const result = [];
    for (const group of ['added', 'removed', 'modified']) {
        for (const row of entry?.[group] || []) {
            const stock = stockIdentity(row);
            const oldLots = group === 'added' ? 0 : numeric(group === 'modified' ? row.old_lots : row.lots);
            const newLots = group === 'removed' ? 0 : numeric(group === 'modified' ? row.new_lots : row.lots);
            if (!stock || oldLots === null || newLots === null) continue;
            const delta = group === 'modified' && numeric(row.diff) !== null
                ? row.diff : amount(newLots - oldLots);
            const kind = group === 'modified' ? (delta === 0 ? 'adjusted' : delta > 0 ? 'increased' : 'decreased') : group;
            result.push({...stock, old: oldLots, new: newLots, delta, kind});
        }
    }
    return result;
}

// When a legacy report was regenerated and its saved basis no longer matches, compare
// the two actual published holdings. The old delta could have used another DB snapshot.
export function snapshotChanges(before, after) {
    const previous = new Map(before.map(row => [row.code, row]));
    const current = new Map(after.map(row => [row.code, row]));
    const result = [];
    for (const code of new Set([...previous.keys(), ...current.keys()])) {
        const a = previous.get(code);
        const b = current.get(code);
        if (a && b && a.lots === b.lots) continue;
        const {name, market} = b || a;
        const oldLots = a?.lots ?? 0;
        const newLots = b?.lots ?? 0;
        const delta = amount(newLots - oldLots);
        const kind = !a ? 'added' : !b ? 'removed' : newLots > oldLots ? 'increased' : 'decreased';
        result.push({code, name, market, old: oldLots, new: newLots, delta, kind});
    }
    return result;
}

function weekdayBefore(date) {
    // A weekend alone cannot contain a trading session. A longer gap needs the real
    // trading calendar; a missing report is never proof of a public holiday.
    const day = new Date(date + 'T12:00:00Z');
    if (!Number.isFinite(day.getTime()) || day.getUTCDay() === 0 || day.getUTCDay() === 6) return null;
    do {
        day.setUTCDate(day.getUTCDate() - 1);
    } while (day.getUTCDay() === 0 || day.getUTCDay() === 6);
    return day.toISOString().slice(0, 10);
}

function classify(previous, date, expected, index) {
    if (!previous || !date || previous >= date) return 'unknown';
    if (expected) return previous === expected ? 'daily' : previous < expected ? 'interval' : 'unknown';
    if (previous === weekdayBefore(date)) return 'daily';
    return index.some(day => previous < day && day < date) ? 'interval' : 'unknown';
}

function byFund(rows) {
    return new Map((rows || []).map(row => [row.etf_code, row]));
}

async function readContext(report, index) {
    const modern = Number(report.report_schema_version) >= 2;
    let ledger = {};
    if (!modern) {
        try { ledger = await readFile('assets/report-baselines.json'); }
        catch { /* Snapshots still allow a conservative comparison. */ }
    }
    const entry = ledger[report.date];
    const basis = entry && entry.updateTime === report.update_time ? entry : null;
    const previousReportDate = modern ? dateValue(report.previous_report_date)
        : dateValue(basis?.previousReportDate) || index.find(date => date < report.date) || null;
    const previousTradingDate = dateValue(report.previous_trading_date) || dateValue(basis?.previousTradingDate);
    let prior = new Map();
    let priorAvailable = false;
    let missing = [];
    if (!modern && !basis && previousReportDate) {
        try {
            const previous = await reportFile(previousReportDate);
            priorAvailable = Array.isArray(previous.etf_holdings);
            prior = byFund(previous.etf_holdings);
        }
        catch { missing = [previousReportDate]; }
    }
    return {modern, ledger, basis, previousReportDate, previousTradingDate, prior, priorAvailable, missing, index};
}

function normalizeFund(code, row, detail, stale, reportDate, ctx) {
    const pair = ctx.basis?.funds?.[code];
    const date = dateValue(row?.data_date) || dateValue(stale?.data_date) || dateValue(pair?.[0]);
    const usableDate = date && date <= reportDate ? date : null;
    const holdings = holdingsOf(row?.holdings);
    const previousRow = ctx.prior.get(code);
    const olderFunds = ctx.ledger[ctx.previousReportDate]?.funds;
    const olderPair = olderFunds?.[code];
    let previousObserved = null;
    let newToReport = false;
    let previousDate = null;
    let comparison = 'unknown';
    let changes = changesOf(detail);
    if (ctx.modern && row) {
        previousObserved = dateValue(row.previous_report_data_date);
        newToReport = Boolean(ctx.previousReportDate) && row.previous_report_data_date === null;
        previousDate = dateValue(row.previous_data_date);
        if (['daily', 'interval', 'first'].includes(row.comparison_kind)) comparison = row.comparison_kind;
    } else {
        let expected = usableDate === reportDate ? ctx.previousTradingDate : null;
        if (usableDate !== reportDate) expected = dateValue(ctx.ledger[usableDate]?.previousTradingDate);
        if (Array.isArray(pair) && dateValue(pair[0]) === usableDate && usableDate) {
            previousObserved = dateValue(olderPair?.[0]);
            newToReport = Boolean(olderFunds) && !Object.hasOwn(olderFunds, code);
            previousDate = dateValue(pair[1]);
            comparison = pair.length > 1 && pair[1] === null ? 'first'
                : classify(previousDate, usableDate, expected, ctx.index);
        } else if (ctx.priorAvailable) {
            newToReport = !previousRow;
            previousObserved = dateValue(previousRow?.data_date);
            const priorHoldings = holdingsOf(previousRow?.holdings);
            if (previousObserved && previousObserved < usableDate && priorHoldings.length && holdings.length) {
                previousDate = previousObserved;
                comparison = classify(previousDate, usableDate, expected, ctx.index);
                changes = snapshotChanges(priorHoldings, holdings);
            }
        }
    }
    if (!usableDate || (comparison !== 'first' && (!previousDate || previousDate >= usableDate))) {
        comparison = 'unknown';
        previousDate = null;
    }
    let status = comparison;
    if (usableDate && usableDate < reportDate) {
        if (stale || (previousObserved && previousObserved === usableDate)) status = 'stale';
        else if (comparison === 'first') status = 'first';
        else if (newToReport || (previousObserved && previousObserved < usableDate)) status = 'late';
        else status = 'unknown';
    }
    if (status === 'stale' || comparison === 'first') changes = [];
    return {
        code, name: row?.etf_name || detail?.etf_name || stale?.etf_name || code, date: usableDate, previousDate, status, comparison,
        holdings, hasHoldings: holdings.length > 0, changes, tradingDaysBehind: numeric(stale?.trading_days_behind),
    };
}

// Early reports rounded lots to two decimals. A modified row with zero reported delta
// can represent a single share in either direction. Recover it only from dated endpoints.
async function resolveRoundedChanges(fund, ctx) {
    const rounded = fund.changes.filter(change => change.delta === 0);
    if (!rounded.length) return;
    const current = new Map(fund.holdings.map(row => [row.code, row.lots]));
    let prior = ctx.prior.get(fund.code);
    if (fund.previousDate && prior?.data_date !== fund.previousDate && rounded.some(row => row.kind !== 'added')) {
        const seenPreviously = ctx.ledger[ctx.previousReportDate]?.funds?.[fund.code]?.[0];
        const date = seenPreviously === fund.previousDate ? ctx.previousReportDate : fund.previousDate;
        if (ctx.index.includes(date)) {
            try { prior = byFund((await reportFile(date)).etf_holdings).get(fund.code); }
            catch { /* Display the original edition's rounding limit. */ }
        }
    }
    const earlier = prior?.data_date === fund.previousDate ? holdingsOf(prior.holdings) : [];
    const before = new Map(earlier.map(row => [row.code, row.lots]));
    for (const change of rounded) {
        const old = change.kind === 'added' ? 0 : before.get(change.code);
        const next = change.kind === 'removed' ? 0 : current.get(change.code);
        if (old === undefined || next === undefined || next === old) {
            change.rounded = true;
            continue;
        }
        change.old = old;
        change.new = next;
        change.delta = amount(next - old);
        if (change.kind === 'adjusted') change.kind = next > old ? 'increased' : 'decreased';
    }
}

function aggregateFunds(funds) {
    const stocks = new Map();
    const seen = new Set();
    for (const fund of funds) {
        const key = [fund.code, fund.previousDate, fund.date].join('|');
        if (seen.has(key)) continue;
        seen.add(key);
        for (const event of fund.changes) {
            let stock = stocks.get(event.code);
            if (!stock) {
                stock = {code: event.code, name: event.name, market: event.market, flows: new Map()};
                stocks.set(event.code, stock);
            }
            const previous = stock.flows.get(fund.code);
            if (previous) {
                // Funds arrive latest first. Only the sum of the observed daily changes
                // is known across a window, especially when one of its days is missing.
                previous.delta = amount(previous.delta + event.delta);
                previous.previousDate = fund.previousDate;
                previous.old = null;
                previous.new = null;
                previous.kind = 'net';
                previous.hasAdded ||= event.kind === 'added';
                previous.hasRemoved ||= event.kind === 'removed';
                previous.rounded ||= Boolean(event.rounded);
            } else {
                stock.flows.set(fund.code, {
                    fundCode: fund.code, fundName: fund.name, previousDate: fund.previousDate, date: fund.date,
                    old: event.old, new: event.new, delta: event.delta, kind: event.kind,
                    hasAdded: event.kind === 'added', hasRemoved: event.kind === 'removed', rounded: Boolean(event.rounded),
                });
            }
        }
    }
    const result = [...stocks.values()].map(stock => {
        const flows = [...stock.flows.values()].sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta)
            || a.fundCode.localeCompare(b.fundCode));
        return {...stock, flows, count: flows.length, up: flows.filter(f => f.delta > 0).length,
            down: flows.filter(f => f.delta < 0).length, net: amount(flows.reduce((sum, f) => sum + f.delta, 0))};
    });
    return result.sort((a, b) => b.count - a.count || a.code.localeCompare(b.code));
}

export async function getDay(date) {
    if (!dateValue(date)) throw new Error('報表日期無效');
    const [report, index] = await Promise.all([reportFile(date), getIndex()]);
    if (report.date !== date) throw new Error('報表內容與所選日期不符');
    const ctx = await readContext(report, index);
    const holdings = byFund(report.etf_holdings);
    const details = byFund(report.detailed_changes);
    const stale = byFund(report.stale_etfs);
    const codes = new Set([...holdings.keys(), ...details.keys(), ...stale.keys()]);
    const funds = [...codes].map(code => normalizeFund(code, holdings.get(code), details.get(code),
        stale.get(code), date, ctx)).sort((a, b) => a.code.localeCompare(b.code));
    if (!ctx.modern) await Promise.all(funds.map(fund => resolveRoundedChanges(fund, ctx)));
    const daily = funds.filter(fund => fund.status === 'daily');
    const late = funds.filter(fund => fund.status === 'late' || fund.status === 'interval');
    return {date, updateTime: report.update_time || null, previousTradingDate: ctx.previousTradingDate,
        previousReportDate: ctx.previousReportDate, dates: [date], missing: ctx.missing,
        funds, stocks: aggregateFunds(daily), late};
}

export async function getPeriod(date, count = 1) {
    if (![1, 5, 20].includes(count)) throw new RangeError('期間須為 1、5 或 20 期');
    const index = await getIndex();
    const dates = index.filter(day => day <= date).slice(0, count);
    if (!dates.length || dates[0] !== date) throw new Error('查無所選日期的報表');
    const results = await Promise.allSettled(dates.map(getDay));
    const missing = dates.filter((day, i) => results[i].status === 'rejected');
    const days = results.filter(item => item.status === 'fulfilled').map(item => item.value);
    const since = dates[dates.length - 1];
    const comparable = [];
    for (const day of days) {
        for (const fund of day.funds) {
            if (fund.comparison !== 'daily' || fund.date < since) continue;
            if (fund.status === 'daily' || (count > 1 && fund.status === 'late')) comparable.push(fund);
        }
    }
    return {date, dates, missing, requested: count, days, stocks: aggregateFunds(comparable)};
}

export async function getMarket() {
    const data = await readFile('etf_market_data.json');
    const funds = (data.data || []).map(row => {
        const aumDate = dateValue(row.aum_date?.replaceAll('/', '-'));
        return {code: row.etf_code, name: row.etf_name, aumDate,
            aum: aumDate ? numeric(row.aum_billion) : null};
    });
    return {updateTime: data.update_time || null, funds};
}
