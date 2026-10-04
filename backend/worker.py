"""Restart-safe bulk backfill, throttle and quota cooldown. One provider request at a time."""
import argparse
import json
import time
from datetime import date, timedelta
from pathlib import Path
from .db import Session, Stock, Bar, ROOT, put, get, now
from .ingest import history
from .quality import audit

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

def run(years=10,limit=None):
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
        stocks=[x for x in s.query(Stock) if x.market in ('twse','tpex','index')]
        ids=[x.id for x in sorted(stocks,key=lambda x:(0 if x.id=='TAIEX' else 2 if x.id.startswith('00') else 1,x.id))]
        latest_market_day=s.query(Bar).filter_by(stock_id='TAIEX').order_by(Bar.date.desc()).first()
        required_end=latest_market_day.date if latest_market_day else date.today().isoformat()
    if limit: ids=ids[:limit]
    done=0
    for sid in ids:
        if (ROOT/'data'/'STOP_BACKFILL').exists():break
        with Session() as s:
            ck=get(s,'ingest',sid,default={})
            complete=ck.get('start','9999')<=start and ck.get('end','')>=required_end and ck.get('status')=='ok' and ck.get('extras_completed',False)
        if complete:done+=1;continue
        success=False
        while not success:
            try:
                result=history(sid,start,end=required_end,extras=True)
                success=True;done+=1
                print(json.dumps(result,ensure_ascii=False),flush=True)
                with Session.begin() as s:put(s,'bulk','latest',{'status':'running','stock_id':sid,'done':done,'total':len(ids),'updated_at':now()})
                time.sleep(2)
            except Exception as exc:
                # Provider quota and unavailable networks leave durable checkpoint.
                with Session.begin() as s:put(s,'bulk','latest',{'status':'cooldown','stock_id':sid,'done':done,'total':len(ids),'error':str(exc),'updated_at':now(),'retry_seconds':600})
                for _ in range(60):
                    if (ROOT/'data'/'STOP_BACKFILL').exists():
                        with Session.begin() as s:put(s,'bulk','latest',{'status':'stopped','done':done,'total':len(ids),'updated_at':now()})
                        handle.close();return
                    time.sleep(10)
    audit()
    with Session.begin() as s:put(s,'bulk','latest',{'status':'done' if done==len(ids) else 'stopped','done':done,'total':len(ids),'updated_at':now()})
    handle.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--years',type=int,default=10);p.add_argument('--limit',type=int)
    a=p.parse_args();run(a.years,a.limit)
