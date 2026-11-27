const sourceRoot = new URL('../', import.meta.url);
const datePattern = /^\d{4}-\d{2}-\d{2}$/;
const focusable = 'a[href],button,select,input,summary,[tabindex="0"]';
const requested = new Map();
let lastReport = null;

export function snapshotURL(date) {
  return datePattern.test(date || '') ? new URL('report_' + date + '.html', sourceRoot) : null;
}

export function rememberReport(date, html) {
  lastReport = {date, html};
}

export async function reportHTML(date) {
  const url = snapshotURL(date);
  if (!url) throw new Error('報表日期無效。');
  if (lastReport?.date === date) return lastReport.html;
  if (!requested.has(date)) {
    const request = fetch(url).then(async response => {
      if (!response.ok) throw new Error('無法讀取已發布的日報（HTTP ' + response.status + '）。');
      const published = new DOMParser().parseFromString(await response.text(), 'text/html');
      const article = published.querySelector('article#daily-report.report-page');
      if (article?.dataset.reportDate !== date) throw new Error('這份快照缺少可嵌入的同日日報。');
      return article.outerHTML;
    }).finally(() => requested.delete(date));
    requested.set(date, request);
  }
  return requested.get(date);
}

// A ticker can occur in several tables. Preserve the exact link in this edition.
export function readingState(article, active) {
  if (!article) return null;
  const open = [];
  article.querySelectorAll('details').forEach((details, index) => {
    if (details.open) open.push(index);
  });
  const focus = active && !active.id && article.contains(active)
    ? [...article.querySelectorAll(focusable)].indexOf(active) : -1;
  return {date:article.dataset.reportDate, open, focus};
}

export function restoreReading(article, saved) {
  const open = new Set(saved.open);
  article.querySelectorAll('details').forEach((details, index) => { details.open = open.has(index); });
  return saved.focus >= 0 ? article.querySelectorAll(focusable)[saved.focus] : null;
}

export function showSection(article, hash, takeFocus) {
  if (!article || !hash) return false;
  let id;
  try { id = decodeURIComponent(hash.slice(1)); } catch { return false; }
  const target = document.getElementById(id);
  if (!target || !article.contains(target)) return false;
  for (let details=target.closest('details'); details; details=details.parentElement.closest('details')) {
    details.open = true;
  }
  if (takeFocus) {
    const element = target.matches('details') ? target.querySelector(':scope > summary') : target;
    if (element) {
      if (!element.matches(focusable)) element.tabIndex = -1;
      element.focus({preventScroll:true});
    }
  }
  target.scrollIntoView({block:'start'});
  return true;
}
