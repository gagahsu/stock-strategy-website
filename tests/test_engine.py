import copy
import json
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from backend.features import features, aggregate, gaps
from backend.rules import exit_signal, detect
from backend.backtest import simulate
from backend.adjustments import action_ratios
from backend.api import app, validate_settings
from backend.ingest import iso, save_bar
from backend.db import Session, Bar

@pytest.fixture
def cfg():
    return json.loads(Path('config/defaults.json').read_text(encoding='utf-8'))

def frame(n=150):
    rng=np.random.default_rng(3)
    close=100+np.arange(n)*.1+np.sin(np.arange(n)/4)*3
    return pd.DataFrame({'date':pd.bdate_range('2024-01-01',periods=n).strftime('%Y-%m-%d'),'open':close-.5,'high':close+1,'low':close-1,'close':close,'volume':rng.integers(2000000,4000000,n),'factor':1.,'adjustment_verified':1})

def test_features_are_prefix_invariant():
    raw=frame(); full=features(raw); prefix=features(raw.iloc[:100])
    columns=['ma20','k','d','macd_hist','pivot_high5','pivot_low5','trend','range_high','volume_ratio']
    pd.testing.assert_frame_equal(full.iloc[:100][columns],prefix[columns])
    assert detect(full,99)==detect(prefix,99)

def test_adjustments_do_not_use_after_price():
    ratios=action_ratios([{'date':'2024-06-01','before_price':100,'reference_price':95,'after_price':110}],[])
    assert ratios['2024-06-01']==.95

def test_strategy_stop_and_configurable_cap(cfg):
    f=features(frame()); f.loc[len(f)-1,'close']=92
    p={'direction':'long','entry_price':100,'stop_price':85}
    cfg['risk']['max_loss_ratio']=.07
    assert exit_signal(f,len(f)-1,p,cfg)['rule_id']=='X-MAX-LOSS'
    p['stop_price']=95
    assert exit_signal(f,len(f)-1,p,cfg)['rule_id']=='X-STRATEGY-STOP'

def test_short_stop_mirror(cfg):
    f=features(frame());f.loc[len(f)-1,'close']=109
    cfg['risk']['max_loss_ratio']=.08
    assert exit_signal(f,len(f)-1,{'direction':'short','entry_price':100,'stop_price':120},cfg)['rule_id']=='X-MAX-LOSS'

def test_backtest_uses_next_open_and_no_day_trade(monkeypatch,cfg):
    raw=frame(80);day=raw.iloc[60].date
    monkeypatch.setattr('backend.backtest.detect',lambda df,i,*args:[{'id':'L-ENTRY-4','direction':'long'}] if i==60 else [])
    monkeypatch.setattr('backend.backtest.exit_signal',lambda *args:{'action':'exit','fraction':1,'reason':'test'})
    params={'start':raw.iloc[55].date,'end':raw.iloc[-1].date,'rule_ids':['L-ENTRY-4'],'market_filter':False,'slippage':0,'allocation':.7}
    r=simulate({'2330':raw},cfg,params)
    t=r['trades'][0]
    assert t['entry_date']==raw.iloc[61].date>day
    assert t['exit_date']>t['entry_date']
    assert t['entry_price']==raw.iloc[61].open
    assert t['net_pnl']<t['gross_pnl']
    assert r['params']['commission_rate']==pytest.approx(.000399)
    assert r['summary']['final_equity']==pytest.approx(cfg['backtest']['initial_capital']+t['net_pnl'])

def test_stop_gap_fills_worse_than_stop(monkeypatch,cfg):
    raw=frame(80)
    monkeypatch.setattr('backend.backtest.detect',lambda df,i,*args:[{'id':'L-ENTRY-4','direction':'long'}] if i==60 else [])
    raw.loc[62,['open','high','low','close']]=[90,92,85,91]
    r=simulate({'2330':raw},cfg,{'start':raw.iloc[55].date,'end':raw.iloc[-1].date,'market_filter':False,'slippage':0})
    assert r['trades'][0]['exit_price']==90

def test_unverified_prices_rejected(cfg):
    raw=frame(80);raw['adjustment_verified']=0
    with pytest.raises(ValueError,match='還原價未驗證'):
        simulate({'2330':raw},cfg,{'start':raw.iloc[50].date,'end':raw.iloc[-1].date})

def test_no_trade_empty_signals_does_not_invent_return(monkeypatch,cfg):
    monkeypatch.setattr('backend.backtest.detect',lambda *args:[])
    raw=frame(80)
    r=simulate({'2330':raw},cfg,{'start':raw.iloc[50].date,'end':raw.iloc[-1].date,'market_filter':False})
    assert r['summary']['total_return']==0 and r['summary']['trades']==0

def test_gap_excludes_action_date():
    raw=frame(40); raw.loc[30,['open','high','low','close']]=[150,152,149,151];raw.loc[30:,'factor']=.7
    assert not features(raw).iloc[30].gap_up

def test_weekly_aggregation_does_not_label_future():
    raw=frame(13)
    assert aggregate(raw).iloc[-1].date==raw.iloc[-1].date

def test_settings_invalid_discount(cfg):
    cfg['broker_profiles'][0]['commission_discount_multiplier']=2.8
    with pytest.raises(ValueError):validate_settings(cfg)

def test_api_health_validation_and_origin():
    client=TestClient(app)
    assert client.get('/api/health').status_code==200
    assert client.post('/api/portfolio',json={'stock_id':'2330','entry_date':'2024-01-01','entry_price':0,'shares':1000}).status_code==422
    assert client.post('/api/scan',headers={'origin':'https://attacker.invalid'}).status_code==403

def test_provider_roc_dates():
    assert iso('115/10/02')=='2026-10-02'

def test_weekly_prices_adjust_before_aggregation():
    raw=frame(5);raw.loc[:1,'factor']=.5
    week=aggregate(raw)
    assert week.iloc[0].high==pytest.approx((raw.high*raw.factor).max())
    assert week.iloc[0].raw_close==raw.iloc[-1].close

def test_historical_signals_ignore_later_reversal():
    raw=frame(80); first=detect(features(raw),70)
    raw.loc[71:,['open','high','low','close']]=[200,205,180,190]
    assert detect(features(raw),70)==first

def test_cost_profiles_are_saved_with_result(monkeypatch,cfg):
    raw=frame(80)
    cfg['broker_profiles'].append({'id':'second','name':'另一間券商','commission_base_rate':.001425,'commission_discount_multiplier':.6})
    monkeypatch.setattr('backend.backtest.detect',lambda *args:[])
    r=simulate({'2330':raw},cfg,{'start':raw.iloc[50].date,'end':raw.iloc[-1].date,'broker_profile_id':'second','market_filter':False})
    assert r['params']['commission_rate']==pytest.approx(.000855)
    assert r['params']['settings_snapshot']['broker_profiles'][1]['id']=='second'

def test_upsert_is_idempotent():
    with Session.begin() as s:
        row={'date':'2024-01-01','open':10,'high':11,'low':9,'close':10,'volume':1000}
        save_bar(s,'TEST',row);s.flush();save_bar(s,'TEST',row);s.flush()
        assert s.query(Bar).filter_by(stock_id='TEST').count()==1
        s.delete(s.get(Bar,('TEST','2024-01-01')))
