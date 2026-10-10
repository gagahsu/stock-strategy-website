import json
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import ingest
from backend.db import Base, Stock, get


@pytest.mark.parametrize('otc',[
    {'SecuritiesCompanyCode':'6173','Paidin.Capital.NTDollars':'1609280000','Date':'1151010','IssueShares':'160928000'},
    {'公司代號':'6173','實收資本額':'1609280000','出表日期':'1151010','已發行普通股數或TDR原股發行股數':'160928000'},
])
def test_profiles_import_both_official_schemas_preserving_stock_metadata(tmp_path, monkeypatch, otc):
    engine=create_engine('sqlite:///'+str(tmp_path/'profiles.db'))
    Base.metadata.create_all(engine)
    isolated=sessionmaker(engine)
    monkeypatch.setattr(ingest,'Session',isolated)
    listed={'公司代號':'2330','實收資本額':'259,303,804,580','出表日期':'1151010'}
    monkeypatch.setattr(ingest,'fetch',lambda url:[listed] if 'twse.com.tw' in url else [otc])
    with isolated.begin() as s:
        for sid,market in [('2330','twse'),('6173','tpex')]:
            s.add(Stock(id=sid,name=sid,market=market,payload=json.dumps({'full_delivery':False,'isin':'existing'})))
    assert ingest.company_profiles()=={'twse':1,'tpex':1}
    with isolated() as s:
        for sid,market,capital,raw in [('2330','twse',259303804580,listed),('6173','tpex',1609280000,otc)]:
            metadata=json.loads(s.get(Stock,sid).payload)
            assert metadata['paid_in_capital']==capital
            assert metadata['capital_date']=='2026-10-10'
            assert metadata['company_profile']==raw
            assert metadata['isin']=='existing'
            assert metadata['full_delivery'] is False
            assert get(s,'ingest','profiles_'+market)['rows']==1
