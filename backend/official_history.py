"""Supplement missing raw bars by trading day from public TWSE/TPEX history.

This does not claim corporate actions or fundamentals are complete. FinMind's
per-stock checkpoints remain independent and must still pass their own audits.
"""
import argparse
import hashlib
import json
import os
import time
from contextlib import contextmanager
from datetime import date, timedelta

from .db import Session, Bar, ROOT, get, put, now, settings
from .ingest import fetch, iso, bar_values
from .universe import pool_stocks
from .backfill_scope import pin_scope

SOURCES = {
    'twse': 'https://www.twse.com.tw/exchangeReport/MI_INDEX',
    'tpex': 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes',
}
FIELDS = {
    'twse': {'id': '證券代號', 'open': '開盤價', 'high': '最高價', 'low': '最低價', 'close': '收盤價', 'volume': '成交股數'},
    'tpex': {'id': '代號', 'open': '開盤', 'high': '最高', 'low': '最低', 'close': '收盤', 'volume': '成交股數'},
}


def parse_day(market, day, response):
    fields = FIELDS[market]
    if str(response.get('stat', '')).lower() != 'ok' or iso(response.get('date', '')) != day:
        raise ValueError('官方行情未確認成功或日期不符，未標記完成')
    tables = list(response.get('tables', []))
    if market == 'twse' and response.get('fields9'):
        tables.append({'fields': response['fields9'], 'data': response.get('data9')})
    matching = [t for t in tables if set(fields.values()).issubset(t.get('fields') or [])]
    if not matching:
        raise ValueError('官方行情欄位不完整，未標記完成')
    rows = []
    for table in matching:
        names = table['fields']
        if not isinstance(table.get('data'), list):
            raise ValueError('官方行情資料表不完整')
        for values in table['data']:
            if len(values) < len(names):
                raise ValueError('官方行情列欄位不完整')
            raw = dict(zip(names, values))
            rows.append({'id': str(raw[fields['id']]).strip(), 'date': day,
                         'source': market.upper() + '_HISTORY',
                         **{key: raw[name] for key, name in fields.items() if key != 'id'}})
    # Both exchanges have hundreds of ordinary equities; reject empty/partial responses.
    if len(rows) < 100:
        raise ValueError('官方全市場行情筆數不足，未標記完成')
    return rows


def ingest_day(market, day, known_ids, universe_hash):
    with Session() as s:
        checkpoint = get(s, 'official_history_day', market, day, default={})
    if checkpoint.get('universe_hash') == universe_hash and checkpoint.get('status') == 'ok':
        return {**checkpoint, 'cached': True}
    params = {'response': 'json', 'date': day.replace('-', '')}
    if market == 'twse':
        params['type'] = 'ALLBUT0999'
    else:
        params['date'] = day.replace('-', '/')
    rows = parse_day(market, day, fetch(SOURCES[market], params))
    inserted = preserved = no_prices = rejected = 0
    with Session.begin() as s:
        existing = {x[0] for x in s.query(Bar.stock_id).filter(Bar.date == day)}
        for row in rows:
            sid = row['id']
            # Use current equity IDs across both markets, retaining history before board transfers.
            if sid not in known_ids:
                continue
            if sid in existing:
                preserved += 1
                continue
            try:
                values = bar_values(sid, row)
                if values is not None:
                    # Another backfill can insert this key after our initial query.
                    # The database arbitrates the conflict without replacing its factors.
                    if s.get_bind().dialect.name == 'sqlite':
                        from sqlalchemy.dialects.sqlite import insert
                    else:
                        from sqlalchemy.dialects.postgresql import insert
                    statement = insert(Bar).values(stock_id=sid, date=day, **values,
                        source=row['source'], factor=1., adjustment_verified=0)
                    statement = statement.on_conflict_do_nothing(index_elements=['stock_id', 'date'])
                    added = s.execute(statement).rowcount
                    inserted += added
                    preserved += 1 - added
                    existing.add(sid)
                else:
                    no_prices += 1
            except ValueError as exc:
                rejected += 1
                put(s, 'official_rejected_bar', sid, {'row': row, 'reason': str(exc), 'updated_at': now()}, day)
        result = {'market': market, 'date': day, 'status': 'ok', 'source': SOURCES[market],
                  'provider_rows': len(rows), 'inserted': inserted, 'preserved': preserved,
                  'no_valid_price': no_prices, 'rejected': rejected,
                  'universe_hash': universe_hash, 'updated_at': now()}
        put(s, 'official_history_day', market, result, day)
    return result


@contextmanager
def lock():
    with (ROOT / 'data' / 'official-history.lock').open('a+') as handle:
        if os.name == 'nt':
            import msvcrt
            handle.seek(0); handle.write('0'); handle.flush(); handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def run(years=10, recent_days=370):
    with lock():
        with Session() as s:
            known = {x.id for x in pool_stocks(s, settings(s))}
            calendar = [x[0] for x in s.query(Bar.date).filter(Bar.stock_id == 'TAIEX').order_by(Bar.date.desc())]
        if not calendar or not known:
            raise ValueError('缺少大盤交易日期或股票池，無法回補')
        fingerprint = hashlib.sha256('\n'.join(sorted(known)).encode()).hexdigest()
        end = date.fromisoformat(calendar[0])
        with Session.begin() as s:
            start = pin_scope(s, years)
        recent_start = (end - timedelta(days=recent_days)).isoformat()
        days = [d for d in calendar if d >= start]
        phases = [('recent', [d for d in days if d >= recent_start]),
                  ('history', [d for d in days if d < recent_start])]
        total = len(days) * 2
        done = 0
        for phase, phase_days in phases:
            for day in phase_days:
                for market in SOURCES:
                    while True:
                        if (ROOT / 'data' / 'STOP_OFFICIAL_HISTORY').exists():
                            with Session.begin() as s:
                                put(s, 'official_bulk', 'latest', {'status': 'stopped', 'done': done, 'total': total, 'updated_at': now()})
                            return
                        try:
                            result = ingest_day(market, day, known, fingerprint)
                            done += 1
                            with Session.begin() as s:
                                put(s, 'official_bulk', 'latest', {'status': 'running', 'phase': phase, 'market': market,
                                    'date': day, 'done': done, 'total': total, 'updated_at': now(), 'result': result})
                            if not result.get('cached'):
                                print(json.dumps(result, ensure_ascii=True), flush=True)
                                time.sleep(1)
                            break
                        except Exception as exc:
                            with Session.begin() as s:
                                put(s, 'official_bulk', 'latest', {'status': 'cooldown', 'phase': phase, 'market': market,
                                    'date': day, 'done': done, 'total': total, 'error': type(exc).__name__ + ': ' + str(exc), 'updated_at': now()})
                            time.sleep(30)
        with Session.begin() as s:
            put(s, 'official_bulk', 'latest', {'status': 'done', 'done': done, 'total': total, 'start': start, 'end': end.isoformat(), 'updated_at': now()})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--years', type=int, default=10)
    args = parser.parse_args()
    run(args.years)
