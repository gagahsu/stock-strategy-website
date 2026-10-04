import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Bar, get
from backend import ingest


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
