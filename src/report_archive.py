"""Resolve display-only dates and share precision for legacy published reports."""
from copy import deepcopy
from datetime import date
from functools import cache
import json
from math import isfinite
from pathlib import Path

from .stock_markets import market_of, normalize_code
from .trading_calendar import confirmed_previous_trading_day


def _read_object(path):
    try:
        with path.open(encoding='utf-8') as stream:
            data = json.load(stream)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso(value):
    if isinstance(value, str):
        try:
            if date.fromisoformat(value).isoformat() == value:
                return value
        except ValueError:
            pass
    return None


def _same_edition(report, entry):
    return (isinstance(entry, dict) and isinstance(entry.get('funds'), dict)
            and bool(report.get('update_time')) and report['update_time'] == entry.get('updateTime'))


def _comparison(previous, source, entry):
    if previous is None:
        return 'first'
    expected = _iso(entry.get('previousTradingDate')) if isinstance(entry, dict) else None
    if not expected or expected >= source:
        session = confirmed_previous_trading_day(date.fromisoformat(source))
        expected = session.isoformat() if session else None
    if expected and previous == expected:
        return 'daily'
    return 'interval' if expected and previous < expected else 'unknown'


def _quantity(value):
    return value if type(value) in (int, float) and isfinite(value) and value >= 0 else None


def _holdings(rows):
    amounts = {}
    if not isinstance(rows, list):
        return amounts
    for row in rows:
        if not isinstance(row, dict):
            return {}
        code = normalize_code(row.get('stock_code'))
        if market_of(code):
            # A duplicate or unreadable position cannot establish a precise endpoint.
            amount = _quantity(row.get('lots'))
            amounts[code] = amount if code not in amounts else None
    return amounts


def _restore_rows(zero_rows, earlier, current):
    before, after = _holdings(earlier), _holdings(current)
    if not before or not after:
        return
    for group, row in zero_rows:
        code = normalize_code(row.get('stock_code'))
        old, new = before.get(code), after.get(code)
        if group == 'modified':
            if old is None or new is None or old == new:
                continue
            # The legacy analyzer rounded each holding before subtracting. Both
            # endpoints must reproduce the published row, including across a rerun.
            reported = _quantity(row.get('old_lots'))
            if not (reported == _quantity(row.get('new_lots')) == round(old, 2) == round(new, 2)):
                continue
            delta = round(new - old, 3)
            if delta:
                row.update(old_lots=old, new_lots=new, diff=delta, direction='up' if delta > 0 else 'down')
        elif group == 'added' and code not in before and new and round(new, 2) == 0:
            row['lots'] = new
        elif group == 'removed' and code not in after and old and round(old, 2) == 0:
            row['lots'] = old


def archived_display_data(data: dict, docs_dir: Path) -> dict:
    """Enrich a legacy rendering copy only from the matching edition and dated snapshots."""
    report_date = _iso(data.get('date'))
    if not report_date or data.get('report_schema_version', 1) not in (1, '1'):
        return data
    ledger = _read_object(docs_dir / 'assets' / 'report-baselines.json')
    entry = ledger.get(report_date)
    if not _same_edition(data, entry):
        return data

    @cache
    def published_funds(day):
        # All callers pass a validated, earlier ISO date. A missing snapshot differs
        # from a published list that genuinely had no position for a given fund.
        report = _read_object(docs_dir / f'data_{day}.json')
        baseline = ledger.get(day)
        if report.get('date') != day or not isinstance(report.get('etf_holdings'), list):
            return None
        if baseline is not None and not _same_edition(report, baseline):
            return None
        pairs = baseline['funds'] if baseline else {}
        funds = dict.fromkeys(pairs)
        for row in report['etf_holdings']:
            if not isinstance(row, dict) or not isinstance(row.get('etf_code'), str):
                return None
            code = row['etf_code']
            source = _iso(row.get('data_date'))
            pair = pairs.get(code)
            same_source = isinstance(pair, list) and pair and pair[0] == source
            if source and source <= day and (code not in pairs or same_source):
                funds[code] = row
            else:
                funds[code] = None
        return funds

    previous_report = _iso(entry.get('previousReportDate'))
    previous_report = previous_report if previous_report and previous_report < report_date else None
    prior_funds = published_funds(previous_report) if previous_report else None
    display = deepcopy(data)
    details = {row['etf_code']: row for row in display.get('detailed_changes') or []}
    for fund in display.get('etf_holdings') or []:
        code = fund['etf_code']
        source = _iso(fund.get('data_date'))
        pair = entry['funds'].get(code)
        if not source or source > report_date or not isinstance(pair, list) or len(pair) != 2 or pair[0] != source:
            continue
        previous = _iso(pair[1])
        if pair[1] is not None and (not previous or previous >= source):
            continue
        fund['previous_data_date'] = previous
        fund['comparison_kind'] = _comparison(previous, source, ledger.get(source))
        prior = prior_funds.get(code) if prior_funds is not None else None
        if prior:
            fund['previous_report_data_date'] = prior['data_date']
        elif ('previousReportDate' in entry and entry['previousReportDate'] is None
              or prior_funds is not None and code not in prior_funds):
            fund['previous_report_data_date'] = None
        if previous_report:
            display['previous_report_date'] = previous_report

        detail = details.get(code)
        if not previous or not detail or detail.get('data_date', source) != source:
            continue
        zero_rows = [(group, row) for group in ('added', 'removed', 'modified')
                     for row in detail.get(group) or []
                     if _quantity(row.get('diff' if group == 'modified' else 'lots')) == 0]
        if not zero_rows:
            continue
        if not prior or prior['data_date'] != previous:
            prior = (published_funds(previous) or {}).get(code)
        if prior and prior['data_date'] == previous:
            _restore_rows(zero_rows, prior.get('holdings'), fund.get('holdings'))
    return display
