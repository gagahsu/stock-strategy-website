"""Local integration checks: actual stored bars, no live financial transactions."""
import json
from pathlib import Path
from fastapi.testclient import TestClient
from backend.api import app
from backend.db import Session,bars,put,get,Record
from backend.features import features
from backend.backtest import simulate

client=TestClient(app)
report={'routes':{}}
for path in ['health','status','stocks?q=2330','settings','rules','scan','watchlist','portfolio','alerts','stock/2330','stock/2330?period=week','stock/2330?period=month']:
    r=client.get('/api/'+path)
    assert r.status_code==200,(path,r.text[:200])
    report['routes'][path]=r.status_code
cfg=client.get('/api/settings').json()
with Session() as s:
    frames={sid:bars(s,sid) for sid in ['2330','2317','2454']}
    index=features(bars(s,'TAIEX'))
result=simulate(frames,cfg,{'start':'2024-01-01','end':'2026-10-02','rule_ids':['L-ENTRY-4'],'market_filter':True},index)
assert result['summary']['trades']>0
assert all(x['entry_date']<x['exit_date'] for x in result['trades'])
report['actual_data_backtest']=result['summary']
with Session.begin() as s:put(s,'backtest','validation-20261003',result)
Path('data/verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
