import os
import pytest
import httpx
import sqlite3
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from backend import api, worker
from backend.db import Base, put


def test_database_lock_detection_preserves_non_lock_failures():
    locked=OperationalError('update',{},sqlite3.OperationalError('database is locked'))
    wrapped=RuntimeError('wrapped ingestion error');wrapped.__context__=locked
    assert worker.database_locked(wrapped)
    assert not worker.database_locked(OperationalError('update',{},sqlite3.OperationalError('disk is full')))
    assert not worker.database_locked(ValueError('database is locked'))
    wrapped.__context__=wrapped
    assert not worker.database_locked(wrapped)


def test_status_write_survives_real_concurrent_sqlite_writer(tmp_path,monkeypatch):
    from backend.db import get
    path=tmp_path/'status-contention.db'
    engine=create_engine('sqlite:///'+str(path),connect_args={'timeout':0.01})
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(worker,'ROOT',tmp_path);monkeypatch.setattr(worker,'Session',isolated)
    writer=sqlite3.connect(path)
    writer.execute('BEGIN IMMEDIATE')
    waits=[]
    def release(seconds):
        waits.append(seconds);writer.rollback();writer.close()
    monkeypatch.setattr(worker.time,'sleep',release)
    assert worker.save_status({'status':'running','done':1501})
    assert waits==[10]
    with isolated() as s:assert get(s,'bulk','latest')['done']==1501


def test_locked_status_write_honors_stop_without_crashing(tmp_path,monkeypatch):
    path=tmp_path/'status-stop.db'
    engine=create_engine('sqlite:///'+str(path),connect_args={'timeout':0.01})
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    (tmp_path/'data').mkdir();(tmp_path/'data'/'STOP_BACKFILL').touch()
    monkeypatch.setattr(worker,'ROOT',tmp_path);monkeypatch.setattr(worker,'Session',isolated)
    writer=sqlite3.connect(path);writer.execute('BEGIN IMMEDIATE')
    try:assert worker.save_status({'status':'stopped'}) is False
    finally:writer.rollback();writer.close()


def test_worker_retries_same_stock_after_database_lock(tmp_path,monkeypatch):
    from backend.db import Stock,get
    engine=create_engine('sqlite:///'+str(tmp_path/'ingestion-lock.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    with isolated.begin() as s:s.add(Stock(id='1101',name='test',market='twse'))
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(worker,'ROOT',tmp_path);monkeypatch.setattr(worker,'Session',isolated)
    monkeypatch.setattr(worker,'audit',lambda:None);monkeypatch.setattr('backend.service.scan',lambda:{})
    calls=[];waits=[];monkeypatch.setattr(worker.time,'sleep',waits.append)
    def ingest(sid,start,**kwargs):
        calls.append((sid,kwargs['extras']))
        if len(calls)==1:raise OperationalError('update',{},sqlite3.OperationalError('database is locked'))
        return {}
    monkeypatch.setattr(worker,'history',ingest)
    worker.run(scan_every=0)
    assert calls==[('1101',False),('1101',False),('1101',True)]
    assert waits.count(10)==1
    with isolated() as s:assert get(s,'bulk','latest')['status']=='done'
    assert not worker.active()


def test_phase_refresh_waits_for_lock_and_propagates_other_failures(tmp_path,monkeypatch):
    (tmp_path/'data').mkdir();monkeypatch.setattr(worker,'ROOT',tmp_path)
    waits=[];calls=[];monkeypatch.setattr(worker.time,'sleep',waits.append)
    def refresh():
        calls.append(True)
        if len(calls)==1:raise OperationalError('update',{},sqlite3.OperationalError('database is locked'))
    assert worker.run_after_database_wait(refresh)
    assert len(calls)==2 and waits==[10]
    with pytest.raises(ValueError):worker.run_after_database_wait(lambda:(_ for _ in ()).throw(ValueError('invalid data')))


def test_scan_phase_accepts_verified_prices_without_waiting_for_fundamentals(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'phases.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    with isolated.begin() as s:
        put(s,'ingest','TEST',{'start':'2025-01-01','end':'2026-10-02','status':'partial','extras_completed':False})
        assert not worker.phase_complete(s,'TEST','2025-10-01','2026-10-02',False)
        put(s,'adjustment_audit','TEST',{'end':'2026-10-02'})
        assert worker.phase_complete(s,'TEST','2025-10-01','2026-10-02',False)
        assert not worker.phase_complete(s,'TEST','2016-01-01','2026-10-02',True)


@pytest.mark.parametrize('scan_every,expected_scans',[(1,4),(0,2)])
def test_worker_finishes_whole_market_price_pass_before_deep_history(tmp_path,monkeypatch,scan_every,expected_scans):
    from backend.db import Stock
    engine=create_engine('sqlite:///'+str(tmp_path/'ordering.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    with isolated.begin() as s:
        for sid in ('1101','2330'):s.add(Stock(id=sid,name=sid,market='twse'))
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    monkeypatch.setattr(worker,'Session',isolated)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    monkeypatch.setattr(worker,'audit',lambda:None)
    scans=[]
    monkeypatch.setattr('backend.service.scan',lambda:scans.append(len(calls)))
    calls=[]
    monkeypatch.setattr(worker,'history',lambda sid,start,**kwargs:calls.append((sid,start,kwargs['extras'])) or {})
    worker.run(scan_every=scan_every)
    assert [x[0] for x in calls]==['1101','2330','1101','2330']
    assert [x[2] for x in calls]==[False,False,True,True]
    assert calls[0][1]>calls[2][1]
    assert len(scans)==expected_scans
    assert scans[-1]==4  # The final refresh includes auxiliary-data completion.


def test_worker_activity_uses_live_lock_not_leftover_file(tmp_path, monkeypatch):
    monkeypatch.setattr(worker, 'ROOT', tmp_path)
    (tmp_path/'data').mkdir()
    assert worker.active() is False
    path=tmp_path/'data'/'bulk.lock'
    path.write_bytes(b'0')
    with path.open('r+b') as handle:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert worker.active() is True
    assert worker.active() is False


def test_status_does_not_claim_dead_worker_is_cooling_down(tmp_path, monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'worker.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(api,'Session',isolated)
    monkeypatch.setattr(worker,'active',lambda:False)
    with isolated.begin() as s:put(s,'bulk','latest',{'status':'cooldown','done':73,'total':2576})
    status=TestClient(api.app).get('/api/status').json()['bulk']
    assert status['status']=='interrupted' and status['active'] is False
    assert status['done']==73


def test_bulk_start_does_not_spawn_duplicate_worker(tmp_path, monkeypatch):
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(api,'ROOT',tmp_path)
    monkeypatch.setattr(worker,'active',lambda:True)
    def forbidden(*args,**kwargs):raise AssertionError('must not spawn')
    monkeypatch.setattr('subprocess.Popen',forbidden)
    response=TestClient(api.app).post('/api/bulk/start')
    assert response.status_code==200 and response.json()['status']=='already_running'


def test_quota_detection_follows_wrapped_errors_without_treating_bad_data_as_quota():
    response=httpx.Response(402,request=httpx.Request('GET','https://example.test/data'))
    error=httpx.HTTPStatusError('quota',request=response.request,response=response)
    wrapped=RuntimeError('action source unavailable');wrapped.__context__=error
    assert worker.quota_error(wrapped)
    assert not worker.quota_error(ValueError('invalid corporate action price'))
    wrapped.__context__=wrapped
    assert not worker.quota_error(wrapped)


def test_quota_probe_persists_only_usage_and_authenticates_in_header(tmp_path,monkeypatch):
    from backend.db import get
    engine=create_engine('sqlite:///'+str(tmp_path/'usage.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    monkeypatch.setattr(worker,'Session',isolated)
    monkeypatch.setenv('FINMIND_TOKEN','test-secret')
    payload={'user_count':580,'api_request_limit':600,'email':'private@example.test'}
    def provider(url,**kwargs):
        assert url=='https://api.web.finmindtrade.com/v2/user_info'
        assert kwargs['headers']['Authorization']=='Bearer test-secret'
        assert 'params' not in kwargs
        return httpx.Response(200,request=httpx.Request('GET',url),json=payload)
    monkeypatch.setattr(worker.httpx,'get',provider)
    assert worker.available_quota()==20
    with isolated() as s:
        saved=get(s,'finmind_usage','latest')
        assert saved['user_count']==580 and saved['api_request_limit']==600
        assert 'private@example.test' not in str(saved) and 'test-secret' not in str(saved)
    payload['user_count']='580'
    assert worker.available_quota() is None


@pytest.mark.parametrize('limited,expected_waits',[(True,18),(False,60)])
def test_worker_only_shortens_cooldown_when_quota_has_recovered(tmp_path,monkeypatch,limited,expected_waits):
    from backend.db import Stock
    engine=create_engine('sqlite:///'+str(tmp_path/'cooldown.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    with isolated.begin() as s:s.add(Stock(id='1101',name='test',market='twse'))
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(worker,'ROOT',tmp_path);monkeypatch.setattr(worker,'Session',isolated)
    monkeypatch.setattr(worker,'audit',lambda:None);monkeypatch.setattr('backend.service.scan',lambda:{})
    sleeps=[];calls=[];probes=iter([None,0,10])
    monkeypatch.setattr(worker.time,'sleep',sleeps.append)
    monkeypatch.setattr(worker,'available_quota',lambda:next(probes))
    def provider(sid,start,**kwargs):
        calls.append((sid,kwargs['extras']))
        if len(calls)==1:
            if limited:
                response=httpx.Response(402,request=httpx.Request('GET','https://example.test/data'))
                raise RuntimeError('wrapped quota') from httpx.HTTPStatusError('quota',request=response.request,response=response)
            raise ValueError('bad source data')
        return {}
    monkeypatch.setattr(worker,'history',provider)
    worker.run(scan_every=0)
    assert sleeps.count(10)==expected_waits
    assert calls==[('1101',False),('1101',False),('1101',True)]
    assert not worker.active()


def test_history_only_resumes_latest_market_date_and_skips_only_complete_ranges(tmp_path,monkeypatch):
    from backend.db import Stock,Bar,get
    engine=create_engine('sqlite:///'+str(tmp_path/'history-only.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    with isolated.begin() as s:
        for sid in ('1101','2330','2454'):s.add(Stock(id=sid,name=sid,market='twse'))
        s.add(Stock(id='TAIEX',name='Index',market='index'))
        s.add(Bar(stock_id='TAIEX',date='2026-10-05',open=100,high=101,low=99,close=100,volume=1000))
        put(s,'ingest','1101',{'start':'2000-01-01','end':'2026-10-02','status':'ok','extras_completed':True})
        put(s,'ingest','2330',{'start':'2000-01-01','end':'2026-10-05','status':'ok','extras_completed':True})
        put(s,'ingest','2454',{'start':'2000-01-01','end':'2026-10-05','status':'partial','extras_completed':False})
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(worker,'ROOT',tmp_path);monkeypatch.setattr(worker,'Session',isolated)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None);monkeypatch.setattr(worker,'audit',lambda:None)
    calls=[];scans=[]
    monkeypatch.setattr(worker,'history',lambda sid,start,**kwargs:calls.append((sid,start,kwargs)) or {})
    monkeypatch.setattr('backend.service.scan',lambda:scans.append(len(calls)))
    worker.run(scan_every=0,history_only=True)
    assert [x[0] for x in calls]==['TAIEX','1101','2454']
    assert all(x[2]=={'end':'2026-10-05','extras':True} for x in calls)
    assert all(x[1]<'2017-01-01' for x in calls)
    assert scans==[3]
    with isolated() as s:assert get(s,'bulk','latest')['status']=='done'
    assert not worker.active()
