from copy import deepcopy
from datetime import date
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import official_index
from backend.db import Base, Bar, get


def responses():
    return ({'stat':'OK','date':'20261001','fields':['日期','開盤指數','最高指數','最低指數','收盤指數'],
        'data':[['115/10/02','48,390.65','48,491.62','48,205.81','48,475.74'],
                ['115/10/05','48,574.95','49,770.66','48,574.95','49,712.04']]},
        {'stat':'OK','date':'20261001','fields':['日期','成交股數','發行量加權股價指數'],
        'data':[['115/10/02','11,017,717,304','48,475.74'],['115/10/05','14,475,105,395','49,712.04']]})


@pytest.mark.parametrize('bad',['month','status','missing_volume','close','invalid_ohlc','duplicate'])
def test_official_index_rejects_unmatched_or_invalid_source_tables(bad):
    prices,volume=deepcopy(responses())
    if bad=='month':prices['date']='20260901'
    if bad=='status':prices['stat']='error'
    if bad=='missing_volume':volume['data'].pop()
    if bad=='close':volume['data'][-1][-1]='49,000'
    if bad=='invalid_ohlc':prices['data'][-1][2]='40,000'
    if bad=='duplicate':prices['data'].append(prices['data'][0])
    with pytest.raises(ValueError):official_index.parse_month('2026-10',prices,volume)


def test_official_index_refresh_keeps_history_and_marks_real_index_rows_verified(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'official-index.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    monkeypatch.setattr(official_index,'Session',isolated)
    with isolated.begin() as s:
        s.add(Bar(stock_id='TAIEX',date='2016-10-04',open=9000,high=9100,low=8900,close=9000,
            volume=100000,factor=1,adjustment_verified=1))
    prices,volume=responses();calls=[]
    def provider(url,params):
        calls.append(url);assert params['date']=='20261001'
        return prices if url==official_index.OHLC_URL else volume
    monkeypatch.setattr(official_index,'fetch',provider)
    report=official_index.refresh(date(2026,10,5))
    assert calls==[official_index.OHLC_URL,official_index.VOLUME_URL]
    assert report['last_date']=='2026-10-05'
    with isolated() as s:
        bar=s.get(Bar,('TAIEX','2026-10-05'))
        assert bar.close==49712.04 and bar.volume==14475105395 and bar.factor==1 and bar.adjustment_verified==1
        assert s.get(Bar,('TAIEX','2016-10-04')) is not None
        assert get(s,'official_index','latest')==report


def test_official_index_does_not_store_future_rows(tmp_path,monkeypatch):
    engine=create_engine('sqlite:///'+str(tmp_path/'index-cutoff.db'))
    Base.metadata.create_all(engine);isolated=sessionmaker(engine)
    monkeypatch.setattr(official_index,'Session',isolated)
    prices,volume=responses()
    monkeypatch.setattr(official_index,'fetch',lambda url,params:prices if url==official_index.OHLC_URL else volume)
    assert official_index.refresh(date(2026,10,2))['last_date']=='2026-10-02'
    with isolated() as s:assert s.get(Bar,('TAIEX','2026-10-05')) is None
