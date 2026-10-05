import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base, Bar, get
from backend import ingest


@pytest.mark.parametrize('condition,reuse',[
    ('verified',True),('unverified',False),('new_older_price',False),('invalid_factor',False),
    ('missing_source',False),('short_start',False),('short_end',False),('infinite_factor',False)])
def test_deep_history_reuses_only_complete_valid_adjustment_evidence(tmp_path,monkeypatch,condition,reuse):
    from backend.db import put
    engine=create_engine('sqlite:///'+str(tmp_path/'action_cache.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    first='2017-01-03' if condition=='new_older_price' else '2016-10-04'
    with isolated.begin() as s:
        for day in (first,'2026-10-02'):
            s.add(Bar(stock_id='TEST',date=day,open=10,high=11,low=9,close=10,volume=1000,
                adjustment_verified=0 if condition=='unverified' else 1,
                factor=0 if condition=='invalid_factor' else float('inf') if condition=='infinite_factor' else 1))
        put(s,'ingest','TEST',{'start':'2025-09-27','end':'2026-10-02','status':'ok'})
        audit_start='2017-01-03' if condition=='short_start' else first
        audit_end='2026-09-30' if condition=='short_end' else '2026-10-02'
        put(s,'adjustment_audit','TEST',{'start':audit_start,'end':audit_end,'method':'free_reference_price'})
        if condition!='missing_source':
            put(s,'corporate_actions','TEST',{'rows':[],'reductions':[],'method':'reference_price_backward_factor'},audit_end)
    calls=[];rebuilt=[]
    def provider(dataset,sid,start,end):
        calls.append(dataset)
        assert dataset=='TaiwanStockPrice'
        return [{'date':day,'open':10,'max':11,'min':9,'close':10,'Trading_Volume':1000} for day in ('2016-10-04','2026-10-02')]
    monkeypatch.setattr(ingest,'fin',provider)
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:rebuilt.append(args))
    ingest.history('TEST','2016-10-04','2026-10-02',extras=False)
    assert calls==['TaiwanStockPrice']
    assert bool(rebuilt) is not reuse


def test_daily_extension_retains_ten_year_range_and_older_financials(tmp_path,monkeypatch):
    from backend.db import put
    engine=create_engine('sqlite:///'+str(tmp_path/'daily_extension.db'))
    Base.metadata.create_all(engine); isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    datasets=['TaiwanStockInstitutionalInvestorsBuySell','TaiwanStockMarginPurchaseShortSale','TaiwanStockMonthRevenue','TaiwanStockFinancialStatements']
    with isolated.begin() as s:
        for day in ('2016-10-04','2026-10-02'):
            s.add(Bar(stock_id='TEST',date=day,open=10,high=11,low=9,close=10,volume=1000))
        put(s,'ingest','TEST',{'start':'2016-10-04','end':'2026-10-02','rows':2,'status':'ok','extras_completed':True,'completed_datasets':datasets})
    calls=[]; rebuilt=[]
    def provider(dataset,sid,start,end):
        calls.append((dataset,start,end))
        if dataset=='TaiwanStockPrice':
            return [{'date':'2026-10-05','open':11,'max':12,'min':10,'close':11,'Trading_Volume':2000}]
        if dataset=='TaiwanStockFinancialStatements':
            return [{'date':'2026-06-30','type':'EPS','value':2.1}] if start<='2026-06-30' else []
        return []
    monkeypatch.setattr(ingest,'fin',provider)
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:rebuilt.append(args))
    ingest.history('TEST','2026-09-05','2026-10-05',extras=True)
    with isolated() as s:
        checkpoint=get(s,'ingest','TEST')
        assert (checkpoint['start'],checkpoint['end'],checkpoint['rows'])==('2016-10-04','2026-10-05',3)
        assert checkpoint['extras_completed']
        financials=get(s,'financials','TEST','2026-10-05')
        assert financials['rows'][0]['date']=='2026-06-30'
        assert (financials['start'],financials['end'])==('2016-10-04','2026-10-05')
    assert all(start=='2016-10-04' and end=='2026-10-05' for dataset,start,end in calls if dataset!='TaiwanStockPrice')
    assert rebuilt[-1][2]=='2026-10-05'


def test_disjoint_append_fetches_intervening_dates_and_old_request_keeps_latest_baseline(tmp_path,monkeypatch):
    from backend.db import put
    engine=create_engine('sqlite:///'+str(tmp_path/'bridged.db'))
    Base.metadata.create_all(engine); isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    with isolated.begin() as s:
        s.add(Bar(stock_id='TEST',date='2026-10-02',open=10,high=11,low=9,close=10,volume=1000))
        put(s,'ingest','TEST',{'start':'2016-10-04','end':'2026-10-02','rows':1,'status':'ok','extras_completed':True,'completed_datasets':['TaiwanStockMonthRevenue']})
    calls=[]; rebuilt=[]
    def provider(dataset,sid,start,end):
        calls.append((dataset,start,end))
        assert dataset=='TaiwanStockPrice'
        return [{'date':day,'open':10,'max':11,'min':9,'close':10,'Trading_Volume':1000} for day in ('2026-10-05','2026-10-21') if start<=day<=end]
    monkeypatch.setattr(ingest,'fin',provider)
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:rebuilt.append(args))
    ingest.history('TEST','2026-10-20','2026-10-21',extras=False)
    assert calls==[('TaiwanStockPrice','2026-10-02','2026-10-21')]
    with isolated() as s:
        assert s.get(Bar,('TEST','2026-10-05')) is not None
        checkpoint=get(s,'ingest','TEST')
        assert (checkpoint['start'],checkpoint['end'])==('2016-10-04','2026-10-21')
        assert not checkpoint['extras_completed']
    ingest.history('TEST','2025-09-01','2026-10-02',extras=False)
    assert len(calls)==1
    assert rebuilt[-1][2]=='2026-10-21'
    with isolated() as s:assert get(s,'ingest','TEST')['end']=='2026-10-21'


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
    import traceback
    token='mock-secret'
    calls=[]
    def provider(url,**kwargs):
        calls.append(url)
        return httpx.Response(402,request=httpx.Request('GET',url,params=kwargs['params']),json={'status':402})
    monkeypatch.setattr(ingest.httpx,'get',provider)
    with pytest.raises(RuntimeError,match='HTTP 402') as error:
        ingest.fetch(ingest.FIN,{'token':token})
    assert len(calls)==1 and token not in str(error.value)
    assert token not in ''.join(traceback.format_exception(error.value))


def test_auxiliary_quota_remains_detectable_and_retry_keeps_completed_datasets(tmp_path,monkeypatch):
    import traceback
    from backend.worker import quota_error
    engine=create_engine('sqlite:///'+str(tmp_path/'auxiliary-quota.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    monkeypatch.setenv('FINMIND_TOKEN','private-test-token')
    monkeypatch.setattr('backend.adjustments.rebuild',lambda *args:None)
    calls=[];limited=[True]
    def provider(url,**kwargs):
        params=kwargs['params'];dataset=params['dataset'];calls.append(dataset)
        if dataset=='TaiwanStockMonthRevenue' and limited[0]:
            return httpx.Response(402,request=httpx.Request('GET',url,params=params),json={'status':402})
        return httpx.Response(200,request=httpx.Request('GET',url,params=params),json={'data':[]})
    monkeypatch.setattr(ingest.httpx,'get',provider)
    with pytest.raises(RuntimeError,match='輔助資料') as error:
        ingest.history('TEST','2016-10-04','2026-10-05')
    assert quota_error(error.value)
    assert 'private-test-token' not in ''.join(traceback.format_exception(error.value))
    assert calls==['TaiwanStockPrice','TaiwanStockInstitutionalInvestorsBuySell','TaiwanStockMarginPurchaseShortSale','TaiwanStockMonthRevenue']
    with isolated() as s:
        ck=get(s,'ingest','TEST')
        assert ck['status']=='partial' and not ck['extras_completed']
        assert len(ck['completed_datasets'])==2
    limited[0]=False
    ingest.history('TEST','2016-10-04','2026-10-05')
    assert calls[-2:]==['TaiwanStockMonthRevenue','TaiwanStockFinancialStatements']
    assert calls.count('TaiwanStockPrice')==1
    with isolated() as s:assert get(s,'ingest','TEST')['extras_completed']
