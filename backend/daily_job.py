"""Durable daily job for a local scheduler or hosted runner with persistent DB."""
import json
from datetime import date, timedelta
from .db import Session, Stock, Bar, Record, records, get, put, now, settings
from .ingest import stock_list, restrictions, daily, history, company_profiles
from .service import scan, review_positions
from .notifications import dispatch
from .quality import audit
from .universe import refresh_current_universe,is_etf
from .worker import quota_error

def run():
    if date.today().weekday()>=5: return {'status':'weekend'}
    report={}
    try:report['stock_list']=stock_list()
    except Exception as exc:report['stock_list_error']=type(exc).__name__
    try:report['current_universe']=refresh_current_universe()
    except Exception as exc:report['current_universe_error']=type(exc).__name__
    # Public whole-market updates must still run when FinMind's catalog is quota-limited.
    report.update({'restrictions':restrictions(),'daily':daily(),'company_profiles':company_profiles()})
    with Session() as s:
        ids=['TAIEX']+sorted(({x['stock_id'] for x in records(s,'position')} | {x['key'] for x in records(s,'watchlist')})-{'TAIEX'})
        if settings(s)['stock_pool'].get('exclude_etf'):
            ids=[sid for sid in ids if sid=='TAIEX' or (st:=s.get(Stock,sid)) and not is_etf(st)]
    # Focus expensive history/action repair on index and actively followed stocks.
    # Official daily endpoints supply whole-market raw bars; do not re-download 10y daily.
    for index,sid in enumerate(ids):
        with Session() as s:
            first=s.query(Bar).filter_by(stock_id=sid).order_by(Bar.date).first()
        start=(date.today()-timedelta(days=30)).isoformat() if first else (date.today()-timedelta(days=370)).isoformat()
        try: history(sid,start,extras=True)
        except Exception as exc:
            report.setdefault('errors',[]).append({'stock_id':sid,'error':str(exc)})
            if quota_error(exc):
                report['deferred_history_ids']=ids[index:]
                break
    report.update({'quality':audit(),'scan':scan()['coverage'],'positions':len(review_positions()['rows']),'notifications':dispatch()})
    with Session.begin() as s: put(s,'daily_job','latest',{'report':report,'updated_at':now()})
    return report

if __name__=='__main__':
    print(json.dumps(run(),ensure_ascii=False))
