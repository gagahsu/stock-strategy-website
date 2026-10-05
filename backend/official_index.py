"""Official TAIEX OHLC and market share volume, independent of FinMind quota."""
import math
from datetime import date
from .db import Session, Bar, put, now
from .ingest import fetch, iso, num, bar_values, save_bar

OHLC_URL = 'https://www.twse.com.tw/indicesReport/MI_5MINS_HIST'
VOLUME_URL = 'https://www.twse.com.tw/exchangeReport/FMTQIK'


def parse_month(month, ohlc, volume):
    required = ('日期', '開盤指數', '最高指數', '最低指數', '收盤指數')
    volume_fields = ('日期', '成交股數', '發行量加權股價指數')
    tables = []
    for payload, fields in ((ohlc, required), (volume, volume_fields)):
        if str(payload.get('stat', '')).lower() != 'ok' or payload.get('date') != month.replace('-', '')+'01':
            raise ValueError('官方大盤回應狀態或月份不符')
        names = payload.get('fields', [])
        if not set(fields).issubset(names) or not isinstance(payload.get('data'), list) or not payload['data']:
            raise ValueError('官方大盤欄位或資料不完整')
        rows = {}
        for row in payload['data']:
            if len(row) < len(names):raise ValueError('官方大盤資料列不完整')
            values = dict(zip(names, row)); day = iso(values['日期'])
            date.fromisoformat(day)
            if not day.startswith(month+'-') or day in rows:raise ValueError('官方大盤日期不符或重複')
            rows[day] = values
        tables.append(rows)
    prices, shares = tables
    if set(prices) != set(shares):raise ValueError('官方大盤價格與成交股數日期不一致')
    result = []
    for day, values in sorted(prices.items()):
        row = {'date': day, 'open': values['開盤指數'], 'high': values['最高指數'],
            'low': values['最低指數'], 'close': values['收盤指數'],
            'volume': shares[day]['成交股數'], 'source': 'TWSE_INDEX_MONTHLY'}
        normalized = bar_values('TAIEX', row)
        other_close = num(shares[day]['發行量加權股價指數'])
        if normalized is None or other_close is None or not math.isfinite(other_close) or not math.isclose(normalized['close'], other_close, rel_tol=0, abs_tol=0.01):
            raise ValueError('官方大盤數值無效或兩表收盤指數不一致')
        result.append(row)
    return result


def refresh(day=None):
    requested = day or date.today()
    month = requested.isoformat()[:7]
    params = {'response': 'json', 'date': month.replace('-', '')+'01'}
    rows = parse_month(month, fetch(OHLC_URL, params), fetch(VOLUME_URL, params))
    rows = [row for row in rows if row['date'] <= requested.isoformat()]
    if not rows:raise ValueError('官方大盤沒有截至所需日期的資料')
    with Session.begin() as s:
        for row in rows:
            save_bar(s, 'TAIEX', row)
            bar = s.get(Bar, ('TAIEX', row['date']))
            # A market index has no per-stock dividend adjustment.
            bar.factor = 1.; bar.adjustment_verified = 1
        report = {'rows': len(rows), 'first_date': rows[0]['date'], 'last_date': rows[-1]['date'],
            'sources': [OHLC_URL, VOLUME_URL], 'updated_at': now()}
        put(s, 'official_index', 'latest', report)
    return report


if __name__ == '__main__':
    import json
    print(json.dumps(refresh(), ensure_ascii=False))
