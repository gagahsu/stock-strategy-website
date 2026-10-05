"""Restart-safe bulk backfill, throttle and quota cooldown. One provider request at a time."""
import argparse
import json
import os
import sqlite3
import time
import httpx
from sqlalchemy.exc import SQLAlchemyError, OperationalError
from datetime import date, timedelta
from pathlib import Path
from .db import Session, Stock, Bar, ROOT, put, get, now, settings
from .universe import pool_stocks
from .ingest import history
from .quality import audit


def quota_error(exc):
    """Recognize wrapped 402 errors without serializing authenticated requests."""
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code==402:return True
        exc=exc.__cause__ or exc.__context__
    return False


def database_locked(exc):
    """Only retry SQLite busy/locked errors, including wrapped ingestion failures."""
    seen=set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc,OperationalError):
            original=exc.orig
            code=getattr(original,'sqlite_errorcode',None)
            if isinstance(original,sqlite3.OperationalError):
                if isinstance(code,int) and (code & 255) in (5,6):return True
                if str(original).lower() in ('database is locked','database table is locked','database schema is locked'):return True
        exc=exc.__cause__ or exc.__context__
    return False


def save_status(value):
    """Status persistence must survive the same writer contention as ingestion."""
    while True:
        try:
            with Session.begin() as s:put(s,'bulk','latest',value)
            return True
        except OperationalError as exc:
            if not database_locked(exc):raise
            if (ROOT/'data'/'STOP_BACKFILL').exists():return False
            time.sleep(10)


def run_after_database_wait(operation):
    while True:
        try:
            operation()
            return True
        except Exception as exc:
            if not database_locked(exc):raise
            if (ROOT/'data'/'STOP_BACKFILL').exists():return False
            time.sleep(10)


def available_quota():
    token=os.getenv('FINMIND_TOKEN')
    if not token:return None
    try:
        response=httpx.get('https://api.web.finmindtrade.com/v2/user_info',
            headers={'Authorization':'Bearer '+token},timeout=15)
        response.raise_for_status()
        payload=response.json()
        used,limit=payload.get('user_count'),payload.get('api_request_limit')
        if type(used) is not int or type(limit) is not int or used<0 or limit<=0:return None
        with Session.begin() as s:
            put(s,'finmind_usage','latest',{'user_count':used,'api_request_limit':limit,'checked_at':now(),
                'source':'https://api.web.finmindtrade.com/v2/user_info'})
        return max(0,limit-used)
    except (httpx.HTTPError,ValueError,TypeError,AttributeError,SQLAlchemyError):
        # Never emit account details or request headers; failed probes retain normal cooldown.
        return None

def active():
    """Probe the OS lock, not stale database status or a reused process id."""
    lock=ROOT/'data'/'bulk.lock'
    if not lock.exists():return False
    with lock.open('r+b') as handle:
        try:
            if __import__('os').name=='nt':
                import msvcrt
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            return False
        except (OSError,BlockingIOError):return True

def phase_complete(s,sid,start,end,extras):
    ck=get(s,'ingest',sid,default={})
    covers=ck.get('start','9999')<=start and ck.get('end','')>=end
    if extras:return covers and ck.get('status')=='ok' and ck.get('extras_completed',False)
    adjustment=get(s,'adjustment_audit',sid,default={})
    return covers and ck.get('status') in ('partial','ok') and adjustment.get('end','')>=end


def run(years=10,limit=None,scan_every=50,history_only=False):
    if scan_every<0:raise ValueError('scan_every 必須為非負整數')
    lock=ROOT/'data'/'bulk.lock'
    # OS advisory file lock is released after process termination.
    handle=lock.open('a+')
    try:
        if __import__('os').name=='nt':
            import msvcrt
            handle.seek(0);handle.write('0');handle.flush();handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except (OSError,BlockingIOError):
        handle.close();raise RuntimeError('已有批次回補執行中')
    start=(date.today()-timedelta(days=365*years+3)).isoformat()
    with Session() as s:
        stocks=pool_stocks(s,settings(s),include_index=True)
        ids=[x.id for x in sorted(stocks,key=lambda x:(0 if x.id=='TAIEX' else 2 if x.id.startswith('00') else 1,x.id))]
        latest_market_day=s.query(Bar).filter_by(stock_id='TAIEX').order_by(Bar.date.desc()).first()
        required_end=latest_market_day.date if latest_market_day else date.today().isoformat()
    if limit: ids=ids[:limit]
    recent_start=(date.fromisoformat(required_end)-timedelta(days=370)).isoformat()
    phases=[('history',start,True)] if history_only else [('scan',recent_start,False),('history',start,True)]
    for phase,phase_start,extras in phases:
        done=0
        for sid in ids:
            if (ROOT/'data'/'STOP_BACKFILL').exists():break
            with Session() as s:
                complete=phase_complete(s,sid,phase_start,required_end,extras)
            if complete:done+=1;continue
            success=False
            while not success:
                try:
                    result=history(sid,phase_start,end=required_end,extras=extras)
                    success=True;done+=1
                    print(json.dumps(result,ensure_ascii=False),flush=True)
                    if not save_status({'status':'running','phase':phase,'stock_id':sid,'done':done,'total':len(ids),'updated_at':now()}):
                        handle.close();return
                    if phase=='scan' and scan_every and done%scan_every==0:
                        from .service import scan
                        if not run_after_database_wait(scan):handle.close();return
                    time.sleep(2)
                except Exception as exc:
                    if database_locked(exc):
                        # The transaction was rolled back; resume the same stock from durable checkpoints.
                        if (ROOT/'data'/'STOP_BACKFILL').exists():handle.close();return
                        time.sleep(10)
                        continue
                    if not save_status({'status':'cooldown','phase':phase,'stock_id':sid,'done':done,'total':len(ids),'error':str(exc),'updated_at':now(),'retry_seconds':600}):
                        handle.close();return
                    limited=quota_error(exc)
                    for tick in range(60):
                        if (ROOT/'data'/'STOP_BACKFILL').exists():
                            save_status({'status':'stopped','phase':phase,'done':done,'total':len(ids),'updated_at':now()})
                            handle.close();return
                        time.sleep(10)
                        if limited and (tick+1)%6==0:
                            remaining=available_quota()
                            if remaining is not None and remaining>=10:break
        if (ROOT/'data'/'STOP_BACKFILL').exists():break
        # Refresh at both phase boundaries, including newly downloaded fundamentals.
        from .service import scan
        if not run_after_database_wait(scan):handle.close();return
    run_after_database_wait(audit)
    save_status({'status':'done' if done==len(ids) else 'stopped','phase':phase,'done':done,'total':len(ids),'updated_at':now()})
    handle.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--years',type=int,default=10);p.add_argument('--limit',type=int)
    p.add_argument('--scan-every',type=int,default=50,help='每幾檔重算掃描；0 表示只在階段完成時重算')
    p.add_argument('--history-only',action='store_true',help='已有全市場原始行情時直接補完整歷史、還原價與輔助資料')
    a=p.parse_args();run(a.years,a.limit,a.scan_every,a.history_only)
