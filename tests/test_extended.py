import copy
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.api import app
from backend.rules import initial_stop, exit_signal
from backend.features import features
from backend.backtest import simulate
from backend.assessment import assessment
from test_engine import frame


def cfg():return json.loads(Path('config/defaults.json').read_text(encoding='utf-8'))


def test_stop_methods_are_frozen_at_signal_and_invalid_levels_fallback():
    settings=cfg();row=features(frame()).iloc[-1]
    price=float(row.high+5)
    assert initial_stop(row,price,'long','kline',settings)==row.low
    assert initial_stop(row,price,'long','ma',settings)==row.ma5
    assert initial_stop(row,price,'long','fixed',settings)==pytest.approx(price*.95)
    assert initial_stop(row,1,'long','ma',settings)==pytest.approx(.95)


def test_reduction_restore_fifo_cost_and_no_day_trade(monkeypatch):
    settings=cfg();settings['risk']['strategy_stop_ratio']=.2;settings['risk']['max_loss_ratio']=.3
    raw=frame(80)
    monkeypatch.setattr('backend.backtest.detect',lambda f,i,*args:[{'id':'L-ENTRY-4','direction':'long'}] if i==60 else [])
    def exits(f,i,p,s):
        return {62:{'action':'reduce','fraction':1/3,'target_fraction':1/3,'reason':'減碼'},64:{'action':'restore','fraction':1/3,'target_fraction':0,'reason':'補回'},66:{'action':'exit','fraction':1,'reason':'全出'}}.get(i,{'action':'hold','fraction':0})
    monkeypatch.setattr('backend.backtest.exit_signal',exits)
    result=simulate({'2330':raw},settings,{'start':raw.iloc[55].date,'end':raw.iloc[-1].date,'market_filter':False,'exit_mode':'scale','slippage':0,'allocation':.7})
    assert len(result['trades'])==3
    assert all(t['entry_date']<t['exit_date'] for t in result['trades'])
    assert result['trades'][-1]['entry_date']==raw.iloc[65].date
    assert result['summary']['final_equity']==pytest.approx(settings['backtest']['initial_capital']+sum(t['net_pnl'] for t in result['trades']))


def test_assessment_future_financial_data_never_used():
    raw=frame(150)
    context={'chips_daily':[{'date':'2099-01-01','buy':1e9,'sell':0}],'fundamentals':[{'date':'2099-01-01','revenue':1e12,'revenue_year':2099,'revenue_month':1}]}
    result=assessment(raw,{'paid_in_capital':100,'capital_date':'2099-01-01'},context)
    assert all(x['passed'] is None for x in result['fundamental'])


def test_settings_bad_nested_shape_returns_422():
    settings=cfg();settings['risk']={}
    assert TestClient(app).put('/api/settings',json=settings).status_code==422


def test_backtest_direction_and_stop_method_validation():
    client=TestClient(app)
    data={'stock_ids':['2330'],'start':'2024-01-01','end':'2025-01-01','direction':'short','rule_ids':['L-ENTRY-4']}
    assert client.post('/api/backtests',json=data).status_code==422
    data.update(direction='long',stop_method='invalid')
    assert client.post('/api/backtests',json=data).status_code==422
    data.update(stop_method='fixed',rule_ids=['nonexistent'])
    assert client.post('/api/backtests',json=data).status_code==422


def test_long_sideways_does_not_use_swing_lower_high_exit():
    f=features(frame());i=len(f)-1
    f.loc[i,['close','lower_high5','trend']]=[110,True,'range']
    f.loc[i-1,'lower_high5']=False
    p={'direction':'long','entry_price':100,'stop_price':90,'exit_mode':'long'}
    assert exit_signal(f,i,p,cfg())['rule_id']!='X-LOWER-HIGH'


def test_known_historical_disposition_blocks_only_that_signal_day(monkeypatch):
    raw=frame(70);settings=cfg()
    monkeypatch.setattr('backend.backtest.detect',lambda f,i,*args:[{'id':'L-ENTRY-4','direction':'long'}] if i==60 else [])
    params={'start':raw.iloc[55].date,'end':raw.iloc[-1].date,'market_filter':False}
    allowed=simulate({'2330':raw},settings,params)
    blocked=simulate({'2330':raw},settings,params,restrictions={('2330',raw.iloc[60].date):{'disposition':True}})
    future=simulate({'2330':raw},settings,params,restrictions={('2330',raw.iloc[61].date):{'disposition':True}})
    assert allowed['summary']['open_positions']==future['summary']['open_positions']==1
    assert blocked['summary']['open_positions']==0


def test_cap_is_first_when_strategy_stop_is_wider():
    settings=cfg();f=features(frame());i=len(f)-1
    f.loc[i,'close']=80
    p={'direction':'long','entry_price':100,'stop_price':85,'exit_mode':'swing'}
    assert exit_signal(f,i,p,settings)['rule_id']=='X-MAX-LOSS'


def test_climax_reduces_until_previous_low_is_broken():
    f=features(frame());i=len(f)-1
    f.loc[i-1,'low']=120
    f.loc[i,['close','body','volume_ratio','lower_high5']]=[124,-.08,1.5,False]
    p={'direction':'long','entry_price':80,'stop_price':70,'exit_mode':'swing'}
    assert exit_signal(f,i,p,cfg())['action']=='reduce'
    f.loc[i,'close']=119
    assert exit_signal(f,i,p,cfg())['action']=='exit'


def test_weekly_pressure_uses_completed_weeks_only():
    raw=frame(150)
    prefix=features(raw.iloc[:123]);full=features(raw)
    for col in ('weekly_resistance','weekly_support','weekly_ma20','weekly_pressure_up','weekly_pressure_down'):
        assert prefix[col].tolist()==full[col].iloc[:123].tolist() if prefix[col].dtype==bool else prefix[col].equals(full[col].iloc[:123])
