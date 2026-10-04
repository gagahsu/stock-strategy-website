import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Bar, get
from backend import ingest


def test_provider_upsert_handles_concurrent_insert_without_resetting_factors(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'concurrent.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    with isolated.begin() as s:
        original_get=s.get
        def racing_lookup(entity,key,*args,**kwargs):
            result=original_get(entity,key,*args,**kwargs)
            if entity is Bar and result is None:
                with isolated.begin() as other:
                    other.add(Bar(stock_id=key[0],date=key[1],open=10,high=12,low=9,close=11,
                                  volume=1000,factor=.75,adjustment_verified=1))
            return result
        monkeypatch.setattr(s,'get',racing_lookup)
        assert ingest.save_bar(s,'2330',{'date':'2026-10-02','open':20,'high':22,'low':19,'close':21,'volume':2000})
        bar=original_get(Bar,('2330','2026-10-02'))
        assert (bar.close,bar.volume,bar.factor,bar.adjustment_verified)==(21,2000,.75,1)


def test_recent_pass_preserves_completed_ten_year_checkpoint(tmp_path,monkeypatch):
    from backend.db import put
    engine=create_engine('sqlite:///'+str(tmp_path/'resume.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    def forbidden(*args):raise AssertionError('completed price dataset must not be downloaded again')
    monkeypatch.setattr(ingest,'fin',forbidden)
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:None)
    with isolated.begin() as s:put(s,'ingest','TEST',{'start':'2016-01-01','end':'2026-10-02','rows':2400,'status':'ok','extras_completed':True,'completed_datasets':['TaiwanStockMonthRevenue']})
    ingest.history('TEST','2025-10-01','2026-10-02',extras=False)
    with isolated() as s:
        ck=get(s,'ingest','TEST')
        assert ck['start']=='2016-01-01' and ck['rows']==2400
        assert ck['extras_completed'] is True
        assert ck['completed_datasets']==['TaiwanStockMonthRevenue']


def test_partial_backfill_resumes_without_repeating_completed_datasets(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'ingest.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:None)
    calls=[];fail=[True]
    def provider(dataset,*args):
        calls.append(dataset)
        if dataset=='TaiwanStockPrice':return [{'date':'2024-01-02','open':10,'max':11,'min':9,'close':10,'Trading_Volume':1000000}]
        if dataset=='TaiwanStockMonthRevenue' and fail[0]:raise RuntimeError('mock quota')
        return []
    monkeypatch.setattr(ingest,'fin',provider)
    with pytest.raises(RuntimeError,match='輔助資料'):ingest.history('TEST','2024-01-01','2024-01-03')
    with isolated() as s:
        checkpoint=get(s,'ingest','TEST')
        assert checkpoint['status']=='partial' and len(checkpoint['completed_datasets'])==2
        assert s.query(Bar).count()==1
    fail[0]=False
    ingest.history('TEST','2024-01-01','2024-01-03')
    assert calls.count('TaiwanStockPrice')==calls.count('TaiwanStockInstitutionalInvestorsBuySell')==calls.count('TaiwanStockMarginPurchaseShortSale')==1
    with isolated() as s:
        assert get(s,'ingest','TEST')['extras_completed'] is True
        assert get(s,'ingest','TEST')['rows']==1


def test_price_only_backfill_does_not_claim_auxiliary_completion(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'price.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    monkeypatch.setattr(ingest,'fin',lambda *args:[])
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:None)
    ingest.history('TEST','2024-01-01','2024-01-03',extras=False)
    with isolated() as s:assert get(s,'ingest','TEST')['extras_completed'] is False


def test_invalid_price_is_quarantined_without_rolling_back_valid_history(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'invalid.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:None)
    rows=[{'date':'2024-01-02','open':10,'max':11,'min':9,'close':10,'Trading_Volume':1000000},
          {'date':'2024-01-03','open':10,'max':9,'min':8,'close':10,'Trading_Volume':1000000},
          {'date':'2024-01-04','open':10,'max':11,'min':9,'close':10,'Trading_Volume':1000000}]
    monkeypatch.setattr(ingest,'fin',lambda dataset,*args:rows if dataset=='TaiwanStockPrice' else [])
    ingest.history('TEST','2024-01-01','2024-01-05')
    with isolated() as s:
        assert s.query(Bar).count()==2
        checkpoint=get(s,'ingest','TEST')
        assert checkpoint['rows']==2 and checkpoint['extras_completed']
        assert checkpoint['rejected_dates']==['2024-01-03']
        assert get(s,'rejected_bar','TEST','2024-01-03')['row']==rows[1]


def test_quota_failure_does_not_burst_retry_or_leak_token(monkeypatch):
    calls=[]
    def provider(url,**kwargs):
        calls.append(url)
        return httpx.Response(402,request=httpx.Request('GET',url),json={'status':402})
    monkeypatch.setattr(ingest.httpx,'get',provider)
    with pytest.raises(RuntimeError,match='HTTP 402') as error:
        ingest.fetch(ingest.FIN,{'token':'mock-secret'})
    assert len(calls)==1 and 'mock-secret' not in str(error.value)
