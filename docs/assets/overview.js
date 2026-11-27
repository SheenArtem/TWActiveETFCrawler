const statusNames = {daily: '單日可比', interval: '跨期比較', late: '補揭露', stale: '沿用舊持股', first: '首份持股', unknown: '基準待確認'};
const collator = new Intl.Collator('en', {numeric: false});
const direction = number => number > 0 ? 'up' : number < 0 ? 'down' : '';
const belowPrecision = stock => stock.flows.some(flow => flow.rounded);

function symbol(item, type, ctx) {
  return `<a class="symbol" href="${ctx.href({view: type, code: item.code})}"><span>${ctx.escape(item.name)}</span><span class="ticker">${ctx.escape(item.code)}</span></a>`;
}

function periodSwitch(ctx) {
  const selected = String(ctx.range);
  return `<nav class="segmented" aria-label="統計期間">${[['1','單日'],['5','近 5 期'],['20','近 20 期']].map(([value,label]) =>
    `<a href="${ctx.href({range: value, page: null})}" ${value === selected ? 'aria-current="true"' : ''}>${label}</a>`).join('')}</nav>`;
}

function views(ctx) {
  return `<nav class="segmented" aria-label="異動檢視方式">${[['overview','按股票'],['funds','按 ETF']].map(([view,label]) =>
    `<a href="${ctx.href({view})}" ${ctx.view === view ? 'aria-current="page"' : ''}>${label}</a>`).join('')}</nav>`;
}

function coverage(ctx) {
  const total = ctx.day.funds.length;
  const current = ctx.day.funds.filter(f => f.date === ctx.day.date).length;
  return `<a class="coverage" href="${ctx.href({view: 'sources'})}"><span class="coverage-label">有當日持股的 ETF</span>
    <span class="coverage-number">${current} <small>/ ${total} 檔</small></span><span class="coverage-more">查看來源</span>
    <span class="coverage-meter" aria-hidden="true">${ctx.day.funds.map((_,i) => `<span${i < current ? ' class="on"' : ''}></span>`).join('')}</span></a>`;
}

const filters = {
  all: ['全部', () => true], single: ['僅一檔', s => s.count === 1], multi: ['多檔調整', s => s.count > 1],
  same: ['多檔同向', s => !belowPrecision(s) && (s.up >= 2 && !s.down || s.down >= 2 && !s.up)],
  mixed: ['方向分歧', s => s.up > 0 && s.down > 0],
  increase: ['僅增持', s => !belowPrecision(s) && s.up > 0 && !s.down], decrease: ['僅減持', s => !belowPrecision(s) && s.down > 0 && !s.up],
  flat: ['期間淨持平', s => !belowPrecision(s) && !s.up && !s.down],
  uncertain: ['方向待確認', s => belowPrecision(s) && !(s.up && s.down)],
  added: ['有新增持股', s => s.flows.some(f => f.hasAdded)],
  removed: ['有移除持股', s => s.flows.some(f => f.hasRemoved)]
};
const sorts = {
  count: ['參與 ETF 檔數', (a,b) => b.count - a.count],
  fundsUp: ['淨增持檔數優先', (a,b) => (b.up-b.down) - (a.up-a.down)],
  fundsDown: ['淨減持檔數優先', (a,b) => (b.down-b.up) - (a.down-a.up)],
  lotsUp: ['持股淨增量優先', (a,b) => b.net - a.net],
  lotsDown: ['持股淨減量優先', (a,b) => a.net - b.net],
  code: ['股票代號', () => 0]
};

function sortedOptions(options, current) {
  return Object.entries(options).map(([value,[label]]) =>
    `<option value="${value}" ${value === current ? 'selected' : ''}>${label}</option>`).join('');
}

function filterHref(filter,ctx) { return ctx.href({view: 'overview', filter, page: null}); }

function stockFilters(filter, ctx) {
  const groups = [
    ['參與檔數', ['all', 'single', 'multi']],
    ['持股方向', ['same', 'mixed', 'increase', 'decrease', 'flat', 'uncertain']],
    ['成分進出', ['added', 'removed']],
  ];
  return `<nav class="stock-filters" aria-label="股票異動篩選">${groups.map(([label, keys]) =>
    `<div class="stock-filter-group" role="group" aria-label="${label}">
      <span class="stock-filter-label" aria-hidden="true">${label}</span>
      <div class="chips">${keys.map(key =>
        `<a class="chip" href="${ctx.escape(filterHref(key,ctx))}"${key === filter ? ' aria-current="true"' : ''}>${filters[key][0]}</a>`
      ).join('')}</div>
    </div>`
  ).join('')}</nav>`;
}

function summary(ctx) {
  const stocks = ctx.period.stocks;
  const single = stocks.filter(filters.single[1]).length;
  const metrics = [['all','全部異動',stocks.length,'檔股票'],['single','僅一檔 ETF',single,'檔股票'],['multi','多檔 ETF',stocks.length-single,'檔股票']];
  return `<div class="summary-grid">${coverage(ctx)}<div class="metrics">${metrics.map(([key,label,num,unit]) =>
    `<a class="metric" href="${filterHref(key,ctx)}" aria-label="${label} ${num} ${unit}"><span>${label}</span><div class="metric-value"><strong>${num}</strong><small>${unit}</small></div></a>`).join('')}</div></div>`;
}

function periodNotice(ctx) {
  const missing = [...new Set([...ctx.period.days.flatMap(day => day.missing), ...ctx.period.missing])];
  const dates = ctx.period.dates;
  const window = ctx.range > 1 && dates.length ? `<p class="muted period-note">${ctx.escape(dates.at(-1))} 至 ${ctx.escape(dates[0])}，已取得 ${ctx.period.days.length}／${ctx.range} 期。僅彙總可確認為單日的持股變動。</p>` : '';
  const warning = missing.length ? `<p class="note">部分資料讀取失敗（${missing.map(ctx.escape).join('、')}），目前顯示已核對的資料。 <button type="button" class="plain-button" data-retry>重試</button></p>` : '';
  return window + warning;
}

function sidebar(ctx) {
  const stocks = ctx.period.stocks;
  const directions = [['increase','只有增持','up'],['mixed','有增有減','both'],['decrease','只有減持','down'],['flat','期間淨持平','flat'],['uncertain','方向待確認','unknown']]
    .map(([key,label,color]) => ({key,label,color,n: stocks.filter(filters[key][1]).length}));
  const active = directions.filter(x => !['flat','uncertain'].includes(x.key) || x.n > 0);
  const late = ctx.day.late;
  return `<aside class="rail" aria-label="異動摘要"><section class="panel"><h2>異動方向分布</h2>
    <div class="direction-plot" aria-hidden="true">${active.filter(x=>x.n).map(x => `<i class="dir-${x.color}" style="flex:${x.n}"></i>`).join('')}</div>
    <ul class="legend">${active.map(x=>`<li><a href="${filterHref(x.key,ctx)}"><i class="swatch dir-${x.color}" aria-hidden="true"></i>${x.label}<strong>${x.n} 檔</strong></a></li>`).join('')}</ul></section>
    <section class="panel"><div class="card-head"><h2>近期補揭露</h2><a href="${ctx.href({view:'sources'})}">查看全部</a></div>
    ${late.length ? `<ul class="aside-list">${late.slice(0,4).map(f=>`<li><a href="${ctx.href({view:'etf',code:f.code,range:null})}"><b>${ctx.escape(f.code)}</b> ${ctx.escape(f.name)}<small>${ctx.escape(f.previousDate || '基準待確認')} → ${ctx.escape(f.date || '日期未提供')}</small></a></li>`).join('')}</ul>` : '<p class="muted">本期無已確認的補揭露紀錄。</p>'}</section></aside>`;
}

function pager(items, ctx, perPage = 20) {
  const pages = Math.max(1, Math.ceil(items.length / perPage));
  const page = Math.min(pages, Math.max(1, Number.parseInt(ctx.params.get('page'),10) || 1));
  const start = (page-1)*perPage;
  const paging = pages > 1 ? `<nav class="pager" aria-label="結果分頁"><span>${start+1}–${Math.min(start+perPage,items.length)}／${items.length} 筆</span><span>
    ${page > 1 ? `<a class="button" href="${ctx.href({page:page-1})}">上一頁</a>` : ''}
    ${page < pages ? `<a class="button" href="${ctx.href({page:page+1})}">下一頁</a>` : ''}</span></nav>` : '';
  return {rows: items.slice(start,start+perPage), paging};
}

function renderOverview(ctx) {
  const filter = Object.hasOwn(filters,ctx.params.get('filter')) ? ctx.params.get('filter') : 'all';
  const sort = Object.hasOwn(sorts,ctx.params.get('sort')) ? ctx.params.get('sort') : 'count';
  const selected = ctx.period.stocks.filter(filters[filter][1]).sort((a,b) => sorts[sort][1](a,b) || collator.compare(a.code,b.code));
  const {rows,paging} = pager(selected,ctx);
  const table = `<div class="table-wrap"><table class="data-table stock-table"><thead><tr><th scope="col">股票</th><th scope="col" class="participants num">參與 ETF</th><th scope="col">增持／減持 ETF</th><th scope="col" class="num">持股淨增減</th></tr></thead><tbody>${rows.map(s=>`<tr>
    <td>${symbol(s,'stock',ctx)}</td><td class="num participants">${s.count} 檔</td>
    <td class="directions"><span class="up">增 ${s.up}</span><span class="muted"> ／ </span><span class="down">減 ${s.down}</span><span class="mobile-only"> 檔 ETF</span></td>
    <td class="num quantity ${direction(s.net)}"><strong>${ctx.format(s.net,true)}</strong> <small>${ctx.unit(s.market)}</small>${belowPrecision(s) ? '<small class="precision-note">含低於報表精度的異動</small>' : ''}</td></tr>`).join('')}</tbody></table></div>`;
  return `<div class="title-row"><h1>每日持股異動</h1>${periodSwitch(ctx)}</div>${summary(ctx)}${periodNotice(ctx)}
    <div class="board"><section class="panel"><div class="section-head"><h2>股票異動 <small>${selected.length} 檔</small></h2>${views(ctx)}</div>
    <div class="filter-bar"><span class="stock-filter-title">篩選條件（擇一）</span><label class="sort-field">排序<select data-set="sort">${sortedOptions(sorts,sort)}</select></label></div>
    ${stockFilters(filter,ctx)}
    ${rows.length ? table : '<p class="empty-state">此期間與條件下沒有可比較的股票異動。</p>'}${paging}</section>${sidebar(ctx)}</div>`;
}

function issuerLink(fund) {
  const c = encodeURIComponent(fund.code);
  const issuers = [
    ['群益','https://www.capitalfund.com.tw/etf'], ['統一','https://www.ezmoney.com.tw/ETF/Transaction/PCF'],
    ['富邦',`https://websys.fsit.com.tw/FubonETF/Fund/Assets.aspx?stkId=${c}`], ['台新',`https://www.tsit.com.tw/ETF/Home/Pcf/${c}`],
    ['中信','https://www.ctbcinvestments.com.tw/Etf'], ['凱基','https://www.kgifund.com.tw'], ['安聯','https://etf.allianzgi.com.tw'],
    ['野村','https://www.nomurafunds.com.tw/ETFWEB/product-description'], ['第一金','https://www.fsitc.com.tw'], ['國泰','https://www.cathaysite.com.tw/'],
    ['復華','https://www.fhtrust.com.tw'], ['永豐','https://sitc.sinopac.com'], ['兆豐','https://www.megafunds.com.tw/MEGA/etf/trade_pcf.aspx'],
    ['摩根','https://am.jpmorgan.com/tw/zh/asset-management/twetf/products/'], ['聯博',fund.code==='00404A'?'https://www.abfunds.com.tw/zh-tw/etfs/pcf.TW00000404A5.html':'https://www.abfunds.com.tw/']
  ];
  return issuers.find(([name])=>fund.name.includes(name))?.[1];
}

function renderFunds(ctx) {
  const sort = ctx.params.get('sort') || 'code';
  const periodEvents = new Map();
  if (ctx.range > 1) {
    for (const stock of ctx.period.stocks) for (const flow of stock.flows) {
      periodEvents.set(flow.fundCode, (periodEvents.get(flow.fundCode) || 0)+1);
    }
  }
  const changes = f => ctx.range > 1 ? periodEvents.get(f.code) || 0 : f.changes.length;
  const market = new Map((ctx.market?.funds || []).filter(f => f.aumDate && (ctx.day.date === ctx.index[0] ? f.aumDate <= ctx.day.date : f.aumDate === ctx.day.date)).map(f=>[f.code,f]));
  const rows = [...ctx.day.funds].sort((a,b) => (sort === 'aum' ? (market.get(b.code)?.aum ?? -1) - (market.get(a.code)?.aum ?? -1) :
    sort === 'changes' ? changes(b)-changes(a) : sort === 'date' ? (b.date || '').localeCompare(a.date || '') : 0) || collator.compare(a.code,b.code));
  return `<div class="title-row"><h1>ETF 清單</h1>${periodSwitch(ctx)}</div>${periodNotice(ctx)}<section class="panel"><div class="section-head">
    <h2>收錄的基金 <small>${rows.length} 檔</small></h2>${views(ctx)}</div><div class="filter-bar">
    <a href="${ctx.href({view:'compare',kind:'funds'})}">比較兩檔 ETF</a><label class="sort-field">排序<select data-set="sort">${sortedOptions({code:['ETF 代號'],changes:['異動檔數'],date:['來源日期'],aum:['基金規模']},sort)}</select></label></div>
    ${ctx.marketError ? '<p class="note">規模資料讀取失敗。<button class="plain-button" data-retry>重試</button></p>' : ''}
    <div class="table-wrap"><table class="data-table fund-table fund-directory ${sort==='aum'?'by-size':''}"><thead><tr><th>基金</th><th>持股日／狀態</th><th class="num">異動股票</th><th>新增／移除</th><th class="num">規模（億元）／日期</th></tr></thead>
    <tbody>${rows.map(f=>{const asset=market.get(f.code); const counted=['daily','interval','late'].includes(f.status) && ['daily','interval'].includes(f.comparison); return `<tr><td class="fund-name">${symbol(f,'etf',ctx)}</td><td class="fund-date"><span class="mobile-only">持股日 </span>${ctx.escape(f.date || '未提供')} <small class="badge ${f.status==='daily'?'good':'warn'}">${statusNames[f.status]}</small></td>
      <td class="num fund-activity">${ctx.range>1 ? changes(f) : (counted ? changes(f) : '—')}<span class="mobile-only"> 檔異動</span></td><td class="fund-actions"><span class="mobile-only">新增／移除 </span>${ctx.range===1 && counted ? f.changes.filter(x=>x.kind==='added').length+'／'+f.changes.filter(x=>x.kind==='removed').length : '—'}</td>
      <td class="num fund-size"><span class="mobile-only">規模 </span>${asset?.aum!=null ? ctx.format(asset.aum)+'<span class="mobile-only"> 億元</span> <small>'+ctx.escape(asset.aumDate)+'</small>' : '—'}</td></tr>`;}).join('')}</tbody></table></div></section>`;
}

function renderSources(ctx) {
  const groups = [...ctx.day.funds].sort((a,b)=>Number(a.status==='daily')-Number(b.status==='daily') || collator.compare(a.code,b.code));
  return `<div class="title-row"><h1>資料來源與狀態</h1></div><div class="board"><section class="panel"><div class="section-head"><h2>逐檔揭露日期</h2><small class="muted">${ctx.escape(ctx.day.date)} 報表</small></div>
    <div class="table-wrap"><table class="data-table fund-table"><thead><tr><th>基金</th><th>持股比較期間</th><th>狀態</th></tr></thead><tbody>${groups.map(f=>{
      const issuer=issuerLink(f);
      return `<tr><td>${symbol(f,'etf',ctx)}${issuer ? `<br><a class="muted" href="${ctx.escape(issuer)}" target="_blank" rel="noopener">投信官網</a>` : ''}</td><td>${ctx.escape(f.previousDate || '—')}<br>${ctx.escape(f.date || '日期未提供')}</td>
        <td><span class="badge ${f.status==='daily'?'good':'warn'}">${statusNames[f.status]}</span>${f.tradingDaysBehind>0 ? `<br><small>落後 ${f.tradingDaysBehind} 個交易日</small>` : ''}</td></tr>`;}).join('')}</tbody></table></div></section><aside class="rail">
    <section class="panel"><h2>如何讀這份報表</h2><p>日期取自投信標示的持股日。相鄰交易日的兩份持股才歸入單日異動。中間缺期會列出完整起訖。</p><p>「沿用舊持股」代表該基金的來源日沒有前進。頁首涵蓋數是本期收錄基金中，有當日持股的檔數。</p>${ctx.day.updateTime ? `<p class="muted">報表產生時間<br>${ctx.escape(ctx.day.updateTime)}（台北）</p>` : ''}</section>
    <section class="panel"><h2>數量與單位</h2><p>持股淨增減為兩次快照間的數量差。台股以張、海外股票以千股計。各基金的增持、減持檔數分開計算。</p>
    <a href="data_${ctx.day.date}.json">本期原始 JSON</a> · <a href="${ctx.escape(ctx.href({view:'report'}))}">本期持股日報</a></section></aside></div>`;
}

export {renderOverview, renderFunds, renderSources};
