import {getDay, getIndex, getMarket, getPeriod} from './market-data.js';
import {renderOverview, renderFunds, renderSources} from './overview.js';
import {renderResearch} from './research-views.js';
import {snapshotURL, rememberReport, reportHTML, readingState, restoreReading, showSection} from './report-view.js';

const $ = id => document.getElementById(id);
const names = {overview:'每日持股異動',report:'持股日報',funds:'ETF 清單',etf:'ETF 明細',stock:'個股明細',compare:'持股比較',history:'歷史報表',watch:'我的追蹤',sources:'資料來源與狀態'};
const escape = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const numbers = new Intl.NumberFormat('zh-TW',{maximumFractionDigits:3});
const format = (value, signed=false) => value == null || !Number.isFinite(Number(value)) ? '—' : (signed && value>0 ? '+' : '') + numbers.format(value);
const unit = value => value === 'TW' || /^\d{4,6}[A-Z]?$/.test(value || '') ? '張' : '千股';
const watchKey = 'tw-active-etf-watch-v1';
function readWatch(){
  try {
    const items=JSON.parse(localStorage.getItem(watchKey) || '[]');
    return Array.isArray(items) ? items.filter(x=>x && ['etf','stock'].includes(x.type) && typeof x.code==='string' && typeof x.name==='string') : [];
  } catch { return []; }
}
let watch=readWatch(), storageFailed=false, context=null, revision=0, searchIndex=[], historicalSearch=null;
let datesKey='', knownDates=[], searchDate='', pendingSearch=null;
const base = new URL('./index.html', location.href);
const cleanPath = url => url.pathname.replace(/\/index\.html$|\/$/, '') || '/';
const allowedRange = value => [5,20].includes(Number(value)) ? Number(value) : 1;

function link(baseParams, activeDate, patch) {
  const oldView=baseParams.get('view') || 'overview';
  const newView=Object.hasOwn(patch,'view') ? patch.view || 'overview' : oldView;
  if(newView==='report'){
    const day=patch.date || baseParams.get('date') || activeDate;
    if(location.protocol==='file:' && snapshotURL(day)) return snapshotURL(day).href;
    const query=new URLSearchParams();
    if(day) query.set('date',day);
    query.set('view','report');
    return base.pathname+'?'+query;
  }
  const params = new URLSearchParams(baseParams);
  if (newView !== oldView) {
    for (const key of [...params.keys()]) if (!['range','date'].includes(key)) params.delete(key);
  }
  if (!params.has('date') && activeDate) params.set('date',activeDate);
  for (const [key,val] of Object.entries(patch)) {
    if (val == null || val === '' || key==='range' && Number(val)===1 || key==='view' && val==='overview') params.delete(key);
    else params.set(key,String(val));
  }
  const query=params.toString();
  return base.pathname+(query ? '?'+query : '');
}

function prepareSearch(days) {
  const seen=new Map();
  const add=(type,item)=>{
    const key=type+'|'+item.code;
    if (!seen.has(key)) seen.set(key,{type,code:item.code,name:item.name,market:item.market});
  };
  for(const day of days) for(const fund of day.funds){
    add('etf', fund);
    for(const item of fund.holdings) add('stock',item);
    for(const item of fund.changes) add('stock',item);
  }
  return [...seen.values()];
}

function updateSearch(){
  const el=$('search-results');
  if(!context){ el.innerHTML='<p class="empty-state">請先選擇可讀取的報表。</p>';return; }
  const q=$('search-input').value.trim().replace(/\s+/g,' ').toLocaleUpperCase();
  if(!q){el.innerHTML='<p class="empty-state">可用股票名稱、ETF 代號或完整海外代號搜尋，例如 3308 HK。</p>';return;}
  if(context.view==='report' && searchDate!==context.day.date){
    el.innerHTML=pendingSearch?.failed
      ? '<p class="empty-state">本期搜尋資料無法讀取。<button class="plain-button" type="button" id="retry-search">重試搜尋</button></p>'
      : '<p class="empty-state" role="status">正在讀取本期可搜尋的標的…</p>';
    return;
  }
  const match=searchIndex.filter(x=>x.code.toUpperCase().includes(q)||x.name.toUpperCase().includes(q))
    .sort((a,b)=>Number(b.code===q)-Number(a.code===q)||Number(b.code.startsWith(q))-Number(a.code.startsWith(q))||a.code.localeCompare(b.code));
  const group=(type,label)=>{
    const all=match.filter(x=>x.type===type);
    if(!all.length) return '';
    return `<section><h3>${label} · ${all.length} 筆</h3>${all.slice(0,25).map(x=>`<a class="symbol" href="${context.href({view:type,code:x.code,...(type==='stock' && historicalSearch?.date === context.day.date ? {range:20} : {})})}">
      <span>${escape(x.name)}</span><span class="ticker">${escape(x.code)}</span>${x.market ? `<small class="badge">${escape(x.market)}</small>` : ''}</a>`).join('')}${all.length>25?'<p class="muted">請增加名稱或代號字數，以縮小結果。</p>':''}</section>`;
  };
  const complete=historicalSearch?.date === context.day.date && historicalSearch.complete;
  el.innerHTML=group('etf','ETF')+group('stock','股票')+(match.length?'':'<p class="empty-state">目前資料中找不到符合的標的。</p>')+
    (complete?'':`<button type="button" class="plain-button" id="search-history">${historicalSearch?.loading?'正在讀取歷史…':historicalSearch?.partial?'重試未載入的歷史':'搜尋近 20 期的歷史標的'}</button>`);
}

const staticDay=/\/report_(\d{4}-\d{2}-\d{2})\.html$/.exec(location.pathname)?.[1];
const startsAtReport=Boolean(staticDay && $('daily-report')?.dataset.reportDate===staticDay);
if(startsAtReport){
  rememberReport(staticDay,$('daily-report').outerHTML);
  if(/^https?:$/.test(location.protocol)){
    history.replaceState(history.state,'',link(new URLSearchParams(),staticDay,{view:'report'})+location.hash);
  }
} else if (!location.search && document.referrer) {
  // Earlier archive editions linked back to index.html without a date.
  const ref = new URL(document.referrer);
  const match = /\/report_(\d{4}-\d{2}-\d{2})\.html$/.exec(ref.pathname);
  if (ref.origin === location.origin && match && new URL('.', ref).pathname === new URL('.',base).pathname) {
    history.replaceState(history.state, '', link(new URLSearchParams(), match[1], {})+location.hash);
  }
}

async function extendSearch(){
  const ctx=context;
  if(!ctx || historicalSearch?.loading) return;
  historicalSearch={date:ctx.day.date,loading:true};
  updateSearch();
  try {
    const history=await getPeriod(ctx.day.date,20);
    if(context!==ctx) return;
    searchIndex=prepareSearch(history.days);
    historicalSearch={date:ctx.day.date,complete:!history.missing.length,partial:!!history.missing.length};
  } catch {
    if(context!==ctx) return;
    historicalSearch={date:ctx.day.date,partial:true};
  }
  updateSearch();
}

function useDaySearch(day){
  if(searchDate!==day.date || !searchIndex.length || historicalSearch?.loading){
    searchIndex=prepareSearch([day]);
    historicalSearch=null;
  }
  searchDate=day.date;
}

async function loadReportSearch(ctx){
  if(ctx?.view!=='report' || searchDate===ctx.day.date || pendingSearch?.ctx===ctx) return;
  const job={ctx};
  pendingSearch=job;
  try {
    const day=await getDay(ctx.day.date);
    if(context!==ctx || pendingSearch!==job) return;
    useDaySearch(day);
    pendingSearch=null;
  } catch {
    if(context!==ctx || pendingSearch!==job) return;
    job.failed=true;
  }
  if($('search-dialog').open) updateSearch();
}

function syncPicker(index,date) {
  const picker=$('report-date');
  const key=index.join('|');
  if(key!==datesKey){picker.replaceChildren(...index.map(day=>new Option(day,day)));datesKey=key;}
  picker.disabled=false;
  picker.value=date;
}

function setChrome(ctx) {
  const current = ctx.view==='etf'?'funds':ctx.view==='stock'?'overview':ctx.view;
  document.querySelectorAll('a[data-view]').forEach(a=>{
    const view=a.dataset.view;
    a.setAttribute('href',ctx.href({view}));
    if (view===current) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current');
  });
  const latest=ctx.index[0];
  document.querySelector('[data-home]').href=ctx.href({view:'overview',date:latest || ctx.day.date,range:1,page:null,sort:null,filter:null});
  $('edition').innerHTML=!latest ? '' : ctx.day.date===latest ? '最新一期'
    : `歷史報表 <a href="${escape(ctx.href({date:latest,page:null}))}">前往最新一期</a>`;
  document.title=`${names[ctx.view]} · ${ctx.day.date} · 主動 ETF 觀測站`;
}

// A daily report can be read from its HTML even when its index or JSON is unavailable.
async function renderReport(params,ticket){
  const indexRequest=getIndex().then(dates=>{knownDates=dates;return dates;},()=>[]);
  const date=params.get('date') || (await indexRequest)[0];
  if(ticket!==revision) return;
  if(!snapshotURL(date)) throw new Error(date?'報表日期無效。':'尚無可讀取的報表日期。');
  const reportParams=new URLSearchParams({date,view:'report'});
  const href=patch=>link(reportParams,date,patch);
  const canonical=href({view:'report',date})+location.hash;
  if(/^https?:$/.test(location.protocol) && location.pathname+location.search+location.hash!==canonical){
    history.replaceState(history.state,'',canonical);
  }
  const ctx={view:'report',day:{date},index:knownDates,href};
  context=ctx;
  pendingSearch=null;
  function showDates(dates,unavailable=false){
    ctx.index=dates;
    const choices=dates.includes(date)?dates:[date,...dates].sort().reverse();
    syncPicker(choices,date);
    $('report-date').disabled=!dates.length;
    setChrome(ctx);
    if(unavailable) $('edition').innerHTML='報表日期索引暫時無法讀取。 <button id="retry-dates" type="button" class="plain-button" data-retry>重試日期</button>';
  }
  showDates(knownDates);
  indexRequest.then(dates=>{
    if(ticket===revision && context===ctx) showDates(dates,!dates.length);
  });
  const body=$('content');
  if(body.querySelector('article#daily-report')?.dataset.reportDate!==date){
    const html=await reportHTML(date);
    if(ticket!==revision) return;
    body.innerHTML=html;
    rememberReport(date,html);
  }
  if($('search-dialog').open){loadReportSearch(ctx);updateSearch();}
}

function returnPosition(position,takeFocus,ticket){
  requestAnimationFrame(()=>{
    if(ticket!==revision) return;
    const article=$('daily-report');
    const saved=article && position?.reading?.date===article.dataset.reportDate;
    if(!saved && showSection(article,location.hash,takeFocus || document.activeElement===document.body)) return;
    let el=saved ? restoreReading(article,position.reading) : null;
    if(!el && position?.focus){
      el=document.getElementById(position.focus) || [...document.querySelectorAll('a[href],button,select,summary')].find(item=>focusKey(item)===position.focus);
    }
    if(el) el.focus({preventScroll:true});
    else if(takeFocus) $('workspace').focus({preventScroll:true});
    if(position?.y!=null) window.scrollTo(0,position.y);
  });
}

function focusKey(el) {
  if(!el) return '';
  return el.id || (el.dataset?.view ? 'nav:'+el.dataset.view : el.getAttribute('href')) || (el.dataset?.watchCode ? 'watch:'+el.dataset.watchCode : el.dataset?.set || '');
}

async function render({position=null,takeFocus=false}={}) {
  const ticket=++revision, params=new URLSearchParams(location.search);
  if(startsAtReport && location.protocol==='file:'){
    params.set('view','report');params.set('date',staticDay);
  }
  const before=context;
  context=null;
  const view=Object.hasOwn(names,params.get('view'))?params.get('view'):'overview';
  const body=$('content');
  body.setAttribute('aria-busy','true');
  const keepArticle=view==='report' && body.querySelector('article#daily-report')?.dataset.reportDate===params.get('date');
  if (!keepArticle && (!before || before.day.date!==params.get('date') || before.view!==view)) body.innerHTML='<div class="loading" role="status">正在讀取持股報表…</div>';
  let index=[];
  try {
    if(view==='report'){await renderReport(params,ticket);return;}
    index=await getIndex();
    if(ticket!==revision) return;
    knownDates=index;
    if(!index.length) throw new Error('尚無可讀取的報表。');
    const date=params.get('date') || index[0];
    syncPicker(index,date);
    if(!before || before.day.date!==date) $('edition').textContent='';
    if(!index.includes(date)) throw new Error('查無這個日期的報表。');
    const range=allowedRange(params.get('range')), href=patch=>link(params,date,patch);
    setChrome({view,day:{date},index,href});
    const day=await getDay(date);
    const periodNeeded=range>1 && ['overview','funds','stock','etf'].includes(view);
    const [period,marketResult]=await Promise.all([
      periodNeeded?getPeriod(date,range):{date,dates:[date],missing:[],requested:1,days:[day],stocks:day.stocks},
      view==='funds'?getMarket().then(value=>({value}),()=>({error:true})):{}
    ]);
    if(ticket!==revision) return;
    const ctx={view,range,day,period,index,params,watch,href,escape,format,unit,getDay,getPeriod,market:marketResult.value,marketError:marketResult.error};
    let html;
    if(view==='overview') html=renderOverview(ctx);
    else if(view==='funds') html=renderFunds(ctx);
    else if(view==='sources') html=renderSources(ctx);
    else html=await renderResearch(view,ctx);
    if(ticket!==revision) return;
    useDaySearch(day);
    context=ctx;
    const shortcut=view==='overview' && watch.length?`<p class="watch-shortcut"><a href="${href({view:'watch'})}">我的追蹤 · ${watch.length} 個標的</a></p>`:'';
    const warning=storageFailed?'<p class="note">目前瀏覽器無法儲存追蹤清單，本次開頁仍可使用。</p>':'';
    body.innerHTML=warning+shortcut+html;
    const detail=body.querySelector('.detail-header h1');
    if(detail && ['stock','etf'].includes(view)) document.title=`${detail.textContent.trim()} · ${date} · 主動 ETF 觀測站`;
    if($('search-dialog').open) updateSearch();
  } catch(err) {
    if(ticket!==revision) return;
    if(keepArticle) return;
    const latest=index[0] || knownDates[0];
    const rescue=view==='report' && snapshotURL(params.get('date') || context?.day.date);
    const invalid=params.has('date') && index.length && !index.includes(params.get('date'));
    if(invalid){$('report-date').value='';$('edition').textContent='日期未收錄';}
    body.innerHTML=`<section class="panel"><h1>報表暫時無法顯示</h1><p class="empty-state">${escape(err.message || '載入失敗')}</p><button type="button" class="button" data-retry>重新載入</button>
      ${rescue?`<a class="button" data-report-direct href="${escape(rescue.href+location.hash)}">直接開啟日報</a>`:''}
      ${latest?`<a class="button" href="${link(params,latest,{view:'overview',date:latest})}">回到最新一期</a>`:''}</section>`;
  } finally {
    if(ticket===revision){body.setAttribute('aria-busy','false');returnPosition(position,takeFocus,ticket);}
  }
}

const positions=new Map();
const visit=Date.now().toString(36);
let sequence=0;
const newEntry=()=>visit+'-'+(++sequence);
let entry=history.state?.entry || newEntry();
history.replaceState({...history.state,entry},'');

function capturePosition(trigger){
  const active=$('search-dialog').open ? $('open-search') : trigger || document.activeElement;
  return {y:window.scrollY,focus:focusKey(active),reading:readingState($('daily-report'),active)};
}

function navigate(url,trigger){
  const dest=new URL(url,location.href);
  const old=new URL(location.href);
  // Local archives have no shared HTTP origin. A date selection opens its actual file.
  if(location.protocol==='file:'){
    if(dest.href!==old.href) location.assign(dest);
    return;
  }
  if(dest.href===old.href){
    if(dest.hash) showSection($('daily-report'),dest.hash,true);
    return;
  }
  const sameDate=(old.searchParams.get('date')||context?.day.date)===(dest.searchParams.get('date')||context?.day.date);
  const sameView=(old.searchParams.get('view')||'overview')===(dest.searchParams.get('view')||'overview') && old.searchParams.get('code')===dest.searchParams.get('code');
  const previous=capturePosition(trigger);
  positions.set(entry,previous);
  history.replaceState({entry,...previous},'');
  entry=newEntry();
  history.pushState({entry},'',dest);
  if($('search-dialog').open) $('search-dialog').close();
  const stay=sameView && sameDate && old.hash===dest.hash;
  render({position:stay?previous:{y:0},takeFocus:true});
}

function toggleWatch(button){
  const {watchType:type,watchCode:code,watchName:name}=button.dataset;
  const old=watch.find(item=>item.code===code && item.type===type);
  watch=old ? watch.filter(item=>item!==old) : [...watch,{type,code,name}];
  try { localStorage.setItem(watchKey,JSON.stringify(watch));storageFailed=false; } catch { storageFailed=true; }
  render({position:{y:window.scrollY,focus:focusKey(button)}});
}

function openSearch(){
  const d=$('search-dialog');
  if(!d.open) d.showModal();
  loadReportSearch(context);
  $('search-input').value='';updateSearch();$('search-input').focus();
}
$('open-search').addEventListener('click',openSearch);
$('close-search').addEventListener('click',()=>$('search-dialog').close());
$('search-dialog').addEventListener('click',e=>{if(e.target===$('search-dialog')) $('search-dialog').close();});
$('search-input').addEventListener('input',updateSearch);
document.addEventListener('keydown',e=>{
  if(e.key==='/' && !e.metaKey && !e.ctrlKey && !e.altKey && !/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)){
    e.preventDefault();openSearch();
  }
  if(!$('search-dialog').open) return;
  const items=[...$('search-results').querySelectorAll('a')];
  const n=items.indexOf(document.activeElement);
  if(e.key==='Enter' && document.activeElement===$('search-input') && items[0]) {e.preventDefault();items[0].click();}
  if(['ArrowDown','ArrowUp'].includes(e.key) && items.length){e.preventDefault();items[(n+(e.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();}
});
document.addEventListener('click',e=>{
  if(e.defaultPrevented || e.button!==0 || e.altKey || e.ctrlKey || e.shiftKey || e.metaKey) return;
  const button=e.target.closest('button');
  if(button?.hasAttribute('data-watch-code')){toggleWatch(button);return;}
  if(button?.hasAttribute('data-retry')){render({position:capturePosition(button)});return;}
  if(button?.id==='retry-search'){pendingSearch=null;loadReportSearch(context);updateSearch();return;}
  if(button?.id==='search-history'){extendSearch();return;}
  const a=e.target.closest('a[href]');
  if(!a || a.target || a.hasAttribute('download') || a.hasAttribute('data-report-direct')) return;
  if(location.protocol==='file:') return;
  const dest=new URL(a.href);
  if(a.getAttribute('href').startsWith('#')){
    if(!a.closest('#daily-report') || !dest.hash) return;
  }
  if(dest.origin===location.origin && cleanPath(dest)===cleanPath(base)){e.preventDefault();navigate(dest,a);}
});
document.addEventListener('change',e=>{
  const select=e.target;
  if(select.id==='report-date') navigate(context?context.href({date:select.value,page:null}):link(new URLSearchParams(location.search),select.value,{date:select.value,page:null}),select);
  if(select.dataset.set && context) navigate(context.href({[select.dataset.set]:select.value,page:null}),select);
});
document.addEventListener('submit',e=>{
  if(!e.target.matches('form[data-route]') || !context) return;
  e.preventDefault();navigate(context.href({...Object.fromEntries(new FormData(e.target)),page:null}));
});
window.addEventListener('popstate',e=>{
  if($('content').getAttribute('aria-busy')==='false') positions.set(entry,capturePosition());
  entry=e.state?.entry || newEntry();
  if(!e.state?.entry) history.replaceState({...e.state,entry},'');
  if($('search-dialog').open) $('search-dialog').close();
  render({position:positions.get(entry) || e.state || {y:0},takeFocus:true});
});
window.addEventListener('storage',e=>{if(e.key===watchKey || e.key===null){watch=readWatch();render({position:capturePosition()});}});
if('scrollRestoration' in history) history.scrollRestoration='manual';
render({position:history.state?.y!=null?history.state:null}).then(() => {
  if (context && location.hash === '#search') {
    $('open-search').focus();
    openSearch();
  }
});
