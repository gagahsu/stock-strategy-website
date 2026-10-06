from datetime import date, timedelta
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Record
from backend.backfill_scope import pin_scope, scope_start


def test_scope_survives_cross_day_resume_and_independent_year_settings(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'scope.db'))
    Base.metadata.create_all(engine)
    database=sessionmaker(engine)
    with database.begin() as s:
        assert pin_scope(s,10,date(2026,10,5))=='2016-10-04'
    with database.begin() as s:
        assert scope_start(s,10,date(2026,10,6))=='2016-10-04'
        assert pin_scope(s,10,date(2026,10,20))=='2016-10-04'
        assert pin_scope(s,5,date(2026,10,20))==(date(2026,10,20)-timedelta(days=1828)).isoformat()
    with database() as s:
        assert s.query(Record).filter_by(kind='backfill_scope_start',key='10').count()==1


def test_scope_can_expand_earlier_and_rejects_corrupt_saved_dates(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'earlier.db'))
    Base.metadata.create_all(engine)
    database=sessionmaker(engine)
    with database.begin() as s:
        pin_scope(s,10,date(2026,10,5))
        earlier=pin_scope(s,10,date(2026,10,4))
        assert scope_start(s,10,date(2026,11,1))==earlier
    with database.begin() as s:
        s.add(Record(kind='backfill_scope_start',key='1',date='bad',payload='{}'))
    with database() as s:
        with pytest.raises(ValueError):scope_start(s,1,date(2026,10,5))


def test_worker_uses_pinned_scope_instead_of_recalculating_start(tmp_path,monkeypatch):
    from backend import worker, backfill_scope
    from backend.db import Stock,Bar
    engine=create_engine('sqlite:///'+str(tmp_path/'worker-scope.db'))
    Base.metadata.create_all(engine)
    database=sessionmaker(engine)
    with database.begin() as s:
        pin_scope(s,10,date(2026,10,4))
        s.add(Stock(id='1101',name='test',market='twse'))
        s.add(Bar(stock_id='TAIEX',date='2026-10-05',open=100,high=101,low=99,close=100,volume=100))
    (tmp_path/'data').mkdir()
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    monkeypatch.setattr(worker,'Session',database)
    monkeypatch.setattr(worker.time,'sleep',lambda _:None)
    monkeypatch.setattr(worker,'audit',lambda:None)
    monkeypatch.setattr('backend.service.scan',lambda:None)
    class LaterDay(date):
        @classmethod
        def today(cls):return cls(2026,10,6)
    monkeypatch.setattr(backfill_scope,'date',LaterDay)
    calls=[]
    monkeypatch.setattr(worker,'history',lambda sid,start,**kwargs:calls.append((sid,start,kwargs)) or {})
    worker.run(history_only=True,scan_every=0)
    assert len(calls)==1 and calls[0][1]=='2016-10-03'
    assert calls[0][2]=={'end':'2026-10-05','extras':True}
