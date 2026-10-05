from datetime import date
import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import daily_job
from backend.db import Base, Stock, get, put


@pytest.mark.parametrize('limited',[True,False])
def test_daily_official_data_survives_catalog_failure_and_defers_quota_requests(tmp_path,monkeypatch,limited):
    engine=create_engine('sqlite:///'+str(tmp_path/'daily.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    with isolated.begin() as s:
        for sid in ('1101','2330'):
            s.add(Stock(id=sid,name=sid,market='twse'))
            put(s,'watchlist',sid,{'active':True})
    class TradingDay(date):
        @classmethod
        def today(cls):return cls(2026,10,5)
    monkeypatch.setattr(daily_job,'date',TradingDay)
    monkeypatch.setattr(daily_job,'Session',isolated)
    calls=[];history_ids=[]
    def catalog():
        raise RuntimeError('catalog unavailable')
    def official_universe():
        calls.append('universe');return {'twse':2,'tpex':0}
    def prices():
        assert calls==['universe']
        calls.append('prices');return {'twse':2}
    def history(sid,*args,**kwargs):
        history_ids.append(sid)
        if sid=='1101':
            if limited:
                response=httpx.Response(402,request=httpx.Request('GET','https://example.test/data'))
                raise RuntimeError('action unavailable') from httpx.HTTPStatusError('quota',request=response.request,response=response)
            raise ValueError('invalid source action')
        return {}
    monkeypatch.setattr(daily_job,'stock_list',catalog)
    monkeypatch.setattr(daily_job,'refresh_current_universe',official_universe)
    monkeypatch.setattr(daily_job,'official_index',lambda:{'last_date':'2026-10-05'})
    monkeypatch.setattr(daily_job,'daily',prices)
    monkeypatch.setattr(daily_job,'restrictions',lambda:{})
    monkeypatch.setattr(daily_job,'company_profiles',lambda:{})
    monkeypatch.setattr(daily_job,'history',history)
    monkeypatch.setattr(daily_job,'audit',lambda:[])
    monkeypatch.setattr(daily_job,'scan',lambda:{'coverage':{'universe_total':2}})
    monkeypatch.setattr(daily_job,'review_positions',lambda:{'rows':[]})
    monkeypatch.setattr(daily_job,'dispatch',lambda:{'sent':0})
    report=daily_job.run()
    assert report['daily']=={'twse':2} and report['stock_list_error']=='RuntimeError'
    assert report['official_index']['last_date']=='2026-10-05'
    assert history_ids==(['TAIEX','1101'] if limited else ['TAIEX','1101','2330'])
    if limited:assert report['deferred_history_ids']==['1101','2330']
    else:assert 'deferred_history_ids' not in report
    with isolated() as s:assert get(s,'daily_job','latest')['report']==report
