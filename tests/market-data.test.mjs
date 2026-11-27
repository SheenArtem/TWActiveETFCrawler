import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const docs = new URL('../docs/', import.meta.url);
let instance = 0;

// Each scenario has a fresh module cache. The production entry points still fetch
// the ordinary Pages URLs; the test supplies JSON or reads the checked-in edition.
async function model(t, files) {
    const requests = [];
    t.mock.method(globalThis, 'fetch', async input => {
        const url = new URL(input);
        const key = decodeURIComponent(url.pathname.slice(docs.pathname.length));
        requests.push(key);
        if (files && !files.has(key)) return {ok: false, status: 404};
        const payload = files ? files.get(key) : JSON.parse(await readFile(url, 'utf8'));
        return {ok: true, status: 200, json: async () => payload};
    });
    const module = new URL('../docs/assets/market-data.mjs', import.meta.url);
    module.searchParams.set('case', String(++instance));
    return {api: await import(module.href), requests};
}

function snapshot(code, date, previous, observed, comparison = 'daily', holdings) {
    return {etf_code: code, etf_name: code, data_date: date, previous_data_date: previous,
        previous_report_data_date: observed, comparison_kind: comparison,
        holdings: holdings ?? [{stock_code: '2330', stock_name: '台積電', lots: 105, weight: 8}]};
}

function changes(code, date, delta = 0, stock = '2330') {
    return {etf_code: code, etf_name: code, data_date: date, added: [], removed: [],
        modified: delta ? [{stock_code: stock, old_lots: 100, new_lots: 100 + delta, diff: delta,
            direction: delta > 0 ? 'up' : 'down'}] : []};
}

function report(date, previous, holdings, details, stale = []) {
    return {date, report_schema_version: 2, previous_trading_date: previous, previous_report_date: previous,
        etf_holdings: holdings, detailed_changes: details, stale_etfs: stale};
}

function publications(rows) {
    const files = new Map([['reports_index.json', rows.map(row => ({date: row.date}))]]);
    for (const row of rows) files.set('data_' + row.date + '.json', row);
    return files;
}

test('a stalled fund retains its last holdings and its prior-day adjustment is counted once', async t => {
    const [jul, aug3, aug4, aug5, aug6] = ['2026-07-31', '2026-08-03', '2026-08-04', '2026-08-05', '2026-08-06'];
    const dates = [aug4, aug5, aug6];
    const previous = [aug3, aug4, aug5];
    const stored = changes('00995A', aug4, 5);
    stored.removed = [{stock_code: '2454', lots: 2}];
    const outside = changes('00994A', jul);
    outside.added = [{stock_code: '2383', lots: 4}];
    const rows = dates.map((date, i) => report(date, previous[i], [
        snapshot('00995A', aug4, aug3, i ? aug4 : aug3),
        snapshot('00981A', date, previous[i], previous[i]),
        snapshot('00994A', jul, '2026-07-30', jul),
    ], [stored, changes('00981A', date, i + 1), outside],
    i ? [{etf_code: '00995A', data_date: aug4, trading_days_behind: i}] : []));
    const {api} = await model(t, publications(rows));
    const today = await api.getDay(aug6);
    const carried = today.funds.find(fund => fund.code === '00995A');
    assert.equal(carried.status, 'stale');
    assert.equal(carried.date, aug4);
    assert.equal(carried.tradingDaysBehind, 2);
    assert.equal(carried.hasHoldings, true);
    assert.deepEqual(carried.changes, []);
    const original = (await api.getDay(aug4)).funds.find(fund => fund.code === carried.code);
    assert.equal(original.status, 'daily');
    assert.deepEqual(original.changes.map(row => row.delta).sort((a, b) => a - b), [-2, 5]);
    const period = await api.getPeriod(aug6, 5);
    const stock = period.stocks.find(row => row.code === '2330');
    assert.equal(stock.count, 2);
    assert.deepEqual(Object.fromEntries(stock.flows.map(flow => [flow.fundCode, flow.delta])),
        {'00995A': 5, '00981A': 6});
    assert.equal(period.stocks.find(row => row.code === '2454').net, -2);
    assert.ok(!period.stocks.some(row => row.code === '2383'));
});

test('late disclosures remain on their actual source dates, and a round trip nets to zero', async t => {
    const [jul, d3, d4, d5, d6] = ['2026-07-31', '2026-08-03', '2026-08-04', '2026-08-05', '2026-08-06'];
    const rows = [[d4, d3, jul, 40], [d5, d4, d3, 20], [d6, d5, d4, 10]].map(([date, source, prior, value]) => {
        const holdings = [snapshot('00408A', source, prior, prior)];
        const details = [changes('00408A', source, value)];
        if (date === d6) {
            holdings.push(snapshot('00981A', date, source, source));
            details.push(changes('00981A', date, 1));
        }
        if (date !== d4) {
            holdings.push(snapshot('00982A', date, source, source));
            const roundTrip = changes('00982A', date, date === d5 ? 4 : -4, '3008');
            roundTrip[date === d5 ? 'added' : 'removed'] = [{stock_code: '2317', lots: 3}];
            details.push(roundTrip);
        }
        return report(date, source, holdings, details);
    });
    const {api} = await model(t, publications(rows));
    const latest = await api.getDay(d6);
    assert.equal(latest.late[0].date, d5);
    assert.equal(latest.stocks.find(row => row.code === '2330').net, 1);
    const period = await api.getPeriod(d6, 5);
    assert.deepEqual(period.days.map(day => [day.date, day.late[0].date]), [[d6, d5], [d5, d4], [d4, d3]]);
    const stock = period.stocks.find(row => row.code === '2330');
    assert.equal(stock.net, 31); // 8/3 (+40) is outside this report window.
    const lateFlow = stock.flows.find(flow => flow.fundCode === '00408A');
    assert.deepEqual([lateFlow.previousDate, lateFlow.date, lateFlow.delta], [d3, d5, 30]);
    const roundTrip = period.stocks.find(row => row.code === '3008');
    assert.deepEqual([roundTrip.count, roundTrip.net, roundTrip.up, roundTrip.down], [1, 0, 0, 0]);
    const enteredAndLeft = period.stocks.find(stock => stock.code === '2317').flows[0];
    assert.deepEqual([enteredAndLeft.delta, enteredAndLeft.hasAdded, enteredAndLeft.hasRemoved], [0, true, true]);
});

test('source coverage distinguishes an unchanged daily snapshot, a first snapshot, a gap, and an unknown date', async t => {
    const date = '2026-10-27';
    const previous = '2026-10-22'; // Typhoon closure, weekend, then a public holiday.
    const row = report(date, previous, [
        snapshot('00981A', date, previous, previous),
        snapshot('00982A', date, null, null, 'first'),
        snapshot('00983A', date, '2026-10-20', previous, 'interval'),
        snapshot('00984A', null, null, null, 'unknown'),
    ], [changes('00983A', date, 19), changes('00984A', date, 2)]);
    const {api, requests} = await model(t, publications([row]));
    const [day, sameDay] = await Promise.all([api.getDay(date), api.getDay(date)]);
    assert.equal(day.previousTradingDate, previous);
    assert.deepEqual(day.funds.map(fund => fund.status), ['daily', 'first', 'interval', 'unknown']);
    assert.equal(day.funds.filter(fund => fund.date === date).length, 3);
    assert.equal(day.funds[0].changes.length, 0);
    assert.equal(day.funds[3].date, null);
    assert.deepEqual(day.stocks, []);
    assert.deepEqual(day.late.map(fund => [fund.code, fund.previousDate, fund.changes.length]),
        [['00983A', '2026-10-20', 1]]);
    assert.deepEqual(sameDay, day);
    assert.deepEqual(requests.sort(), ['data_2026-10-27.json', 'reports_index.json']);
});

test('saved reports reproduce the mobile prototype cases, including offshore stock identities', async t => {
    const {api} = await model(t);
    const index = await api.getIndex();
    assert.ok(index.includes('2026-02-04')); // The previous 90-report cap excluded this date.
    const day = await api.getDay('2026-11-26');
    assert.equal(day.funds.length, 23);
    assert.equal(day.funds.filter(fund => fund.date === day.date).length, 20);
    assert.equal(day.stocks.length, 66);
    assert.equal(day.stocks.filter(stock => stock.count === 1).length, 45);
    const wistron = day.stocks.find(stock => stock.code === '3231');
    assert.deepEqual(wistron.flows.map(flow => [flow.fundCode, flow.old, flow.new, flow.delta]),
        [['00981A', 11967, 14258, 2291]]);
    const nanya = day.stocks.find(stock => stock.code === '2408');
    assert.deepEqual([nanya.up, nanya.down, nanya.net], [1, 1, 935]);
    const foreign = day.funds.find(fund => fund.code === '00988A').holdings.filter(row => row.market !== 'TW');
    assert.ok(foreign.length > 0);
    assert.ok(foreign.every(row => row.code.endsWith(' ' + row.market)));
    const earlier = await api.getDay('2026-11-18');
    const ab = earlier.funds.find(fund => fund.code === '00404A');
    assert.deepEqual([ab.previousDate, ab.date, ab.comparison, ab.changes.length],
        ['2026-11-10', '2026-11-18', 'interval', 24]);
    assert.ok(earlier.stocks.every(stock => stock.flows.every(flow => flow.fundCode !== '00404A')));
    // The old report rounded both 1,002 and 1,003 shares to 1.00 lots and labelled the difference down.
    const february = await api.getDay('2026-02-06');
    const small = february.funds.find(fund => fund.code === '00994A').changes.find(row => row.code === '4904');
    assert.deepEqual([small.old, small.new, small.delta, small.kind], [1.002, 1.003, 0.001, 'increased']);
});

test('a regenerated legacy edition uses the two saved snapshots instead of stale baseline metadata', async t => {
    const date = '2026-11-26', previous = '2026-11-25';
    const older = {date: previous, etf_holdings: [snapshot('00981A', previous, null, null, 'unknown',
        [{stock_code: '2330', lots: 90}])]};
    const current = {date, update_time: date + ' 20:00:00',
        etf_holdings: [{etf_code: '00981A', data_date: date, holdings: [{stock_code: '2330', lots: 102}]},
            {etf_code: '00982A', holdings: [{stock_code: '2330', lots: 5}]}],
        detailed_changes: [changes('00981A', date, 1), changes('00982A', date, 3)]};
    const files = publications([current, older]);
    files.set('assets/report-baselines.json', {
        [date]: {updateTime: date + ' 18:20:00', funds: {'00981A': [date, '2026-11-19']}},
    });
    const {api} = await model(t, files);
    const result = await api.getDay(date);
    const fund = result.funds.find(row => row.code === '00981A');
    assert.deepEqual([fund.previousDate, fund.date, fund.status, fund.changes[0].delta],
        [previous, date, 'daily', 12]);
    const undated = result.funds.find(row => row.code === '00982A');
    assert.deepEqual([undated.date, undated.status], [null, 'unknown']);
    assert.equal(result.stocks[0].count, 1);
});

test('published snapshots with the same numeric prefix keep distinct markets and individual shares', async t => {
    const a = '2026-08-05', b = '2026-08-06';
    const holding = (stock_code, lots) => ({stock_code, lots, stock_name: stock_code, weight: 0.1});
    const older = report(a, '2026-08-04', [snapshot('00988A', a, null, null, 'first',
        [holding('3308', 10), holding('3308 HK', 20)])], []);
    const newer = report(b, a, [snapshot('00988A', b, a, a, 'daily',
        [holding('3308', 11), holding('3308 HK', 19.999)])], []);
    const {api} = await model(t, publications([older, newer]));
    const changes = api.snapshotChanges((await api.getDay(a)).funds[0].holdings,
        (await api.getDay(b)).funds[0].holdings);
    assert.deepEqual(changes.map(stock => [stock.code, stock.market, stock.delta, stock.kind]),
        [['3308', 'TW', 1, 'increased'], ['3308 HK', 'HK', -0.001, 'decreased']]);
});

test('an unreadable edition is disclosed and can be retried without reloading the good edition', async t => {
    const date = '2026-08-06', previous = '2026-08-05';
    const early = report(previous, '2026-08-04', [], []);
    const current = report(date, previous, [], []);
    const files = publications([current, early]);
    const filename = 'data_' + previous + '.json';
    files.delete(filename);
    const {api, requests} = await model(t, files);
    const incomplete = await api.getPeriod(date, 5);
    assert.deepEqual(incomplete.missing, [previous]);
    assert.deepEqual(incomplete.days.map(day => day.date), [date]);
    files.set(filename, early);
    const retried = await api.getPeriod(date, 5);
    assert.deepEqual(retried.missing, []);
    assert.deepEqual(retried.dates, [date, previous]);
    assert.equal(requests.filter(file => file === filename).length, 2);
    assert.equal(requests.filter(file => file === 'data_' + date + '.json').length, 1);
});
