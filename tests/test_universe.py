import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.db import Base,Stock,put,get
from backend import universe


def test_current_equities_include_innovation_and_exclude_funds_warrants_future():
    rows=[['1101　台泥','TW0001101004','1962/02/09','上市','水泥','ESVUFR'],
          ['7750　創新公司','TW0007750000','2025/01/01','上市臺灣創新板','科技','ESVUFR'],
          ['0050　ETF','TW0000050000','2000/01/01','上市','ETF','CEOGEU'],
          ['123456　權證','TW0001234567','2020/01/01','上市','','RWSCCA'],
          ['9999　未上市','TW0009999999','2027/01/01','上市','','ESVUFR'],
          ['9110　存託憑證','TW0009110000','2000/01/01','上市','','EDxxxx']]
    assert [x['id'] for x in universe.equities_from_isin(rows,'twse','2026-10-04')]==['1101','7750','9110']


def test_pool_excludes_etf_and_delisted_but_keeps_index_when_required(tmp_path):
    engine=create_engine('sqlite:///'+str(tmp_path/'pool.db'));Base.metadata.create_all(engine)
    with sessionmaker(engine).begin() as s:
        for sid,market in [('1101','twse'),('7750','twse'),('9999','twse'),('0050','twse'),('TAIEX','index')]:s.add(Stock(id=sid,name=sid,market=market,payload='{}'))
        s.flush()
        put(s,'current_universe','twse',{'rows':[{'id':'1101'},{'id':'7750'}]})
        put(s,'current_universe','tpex',{'rows':[]})
        cfg={'stock_pool':{'exclude_etf':True}}
        assert {x.id for x in universe.pool_stocks(s,cfg)}=={'1101','7750'}
        assert {x.id for x in universe.pool_stocks(s,cfg,True)}=={'1101','7750','TAIEX'}


def test_partial_official_response_preserves_existing_universe(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'official.db'));Base.metadata.create_all(engine)
    isolated=sessionmaker(engine);monkeypatch.setattr(universe,'Session',isolated)
    with isolated.begin() as s:put(s,'current_universe','twse',{'rows':[{'id':'1101'}]})
    with pytest.raises(ValueError,match='不完整'):universe.save_current_universe({'twse':[],'tpex':[]})
    with isolated() as s:assert get(s,'current_universe','twse')['rows']==[{'id':'1101'}]


def test_official_daily_ingest_does_not_save_excluded_etf(tmp_path,monkeypatch):
    from backend import ingest
    from backend.db import Bar
    engine=create_engine('sqlite:///'+str(tmp_path/'daily.db'));Base.metadata.create_all(engine)
    isolated=sessionmaker(engine);monkeypatch.setattr(ingest,'Session',isolated)
    with isolated.begin() as s:
        for sid in ('2330','0050'):s.add(Stock(id=sid,name=sid,market='twse',payload='{}'))
    prices=[{'Code':sid,'Date':'20261002','OpeningPrice':100,'HighestPrice':101,'LowestPrice':99,'ClosingPrice':100,'TradeVolume':1000} for sid in ('2330','0050')]
    monkeypatch.setattr(ingest,'fetch',lambda url:prices if 'twse.com.tw' in url else [])
    assert ingest.daily()['twse']==1
    with isolated() as s:assert [x.stock_id for x in s.query(Bar)]==['2330']
