import json
import uuid
from datetime import date
from sqlalchemy import func
from .db import Session, Stock, Bar, Record, bars, put, get, records, settings, now
from .features import features, aggregate, gaps, clean
from .rules import detect, checks, market_state, exit_signal
from .sop import daily_sop
from .assessment import assessment

def stock_data(s,sid,period='day',end=None):
    st=s.get(Stock,sid)
    if not st: raise ValueError('找不到股票代號')
    raw=bars(s,sid,end)
    cfg=settings(s)
    daily=features(raw,cfg.get('rule_params'))
    f=daily if period=='day' else features(aggregate(raw,period),cfg.get('rule_params'))
    metadata={'id':st.id,'name':st.name,'market':st.market,'industry':st.industry,**json.loads(st.payload)}
    if end and len(f):
        snapshot=get(s,'restriction_snapshot',sid,f.iloc[-1].date,default={})
        metadata.update({key:snapshot.get(key) for key in ('full_delivery','disposition','can_short')})
        metadata['restrictions_date']=snapshot.get('restrictions_date','')
    market=market_state(features(bars(s,'TAIEX',end)))
    ck=checks(daily,metadata,cfg,market, daily.iloc[-1].date if len(daily) else None)
    ck.extend(daily_sop(daily,market))
    historical=[]
    for i in range(max(20,len(f)-80),len(f)):
        historical.extend(detect(f,i,cfg.get('rule_params')))
    context={kind:records_for(s,kind,sid,end,limit=None) for kind in ('fundamentals','financials','chips_daily','margin_daily')}
    evaluation=assessment(raw,metadata,context,market)
    for check in ck:
        if check['name']=='淘汰法：法人連續反向買賣':
            selling=evaluation['institutional_selling']
            if len(daily) and daily.iloc[-1].trend!='bear' and selling is not None:check.update(passed=not selling,hard=True,reason='最近3日法人净額，使用當時已公布資料')
    ck.extend(evaluation['commandments'])
    return clean({'stock':metadata,'bars':f.tail(500).to_dict('records'),'signals':detect(f,params=cfg.get('rule_params')),'historical_signals':historical,'checks':ck,'assessment':evaluation,'gaps':gaps(f)[-30:],'market':market,'data_quality':{'rows':len(raw),'first_date':raw.iloc[0].date if len(raw) else None,'last_date':raw.iloc[-1].date if len(raw) else None,'adjustment_verified':bool(len(raw) and raw.adjustment_verified.all()),'warning':'還原價未驗證，圖表使用目前可取得價源。' if len(raw) and not raw.adjustment_verified.all() else None},'context':{k:v[-20:] for k,v in context.items()}})

def records_for(s,kind,key,end=None,limit=20):
    r=s.query(Record).filter_by(kind=kind,key=key).order_by(Record.date.desc()).first()
    data=json.loads(r.payload).get('rows',[]) if r else []
    if end:data=[x for x in data if x.get('date','9999')<=end]
    return data[-limit:] if limit else data

def institutional_direction(s,sid,f):
    dates=set(f.date.tail(3))
    if len(dates)<3:return {}
    rows=[r for r in records_for(s,'chips_daily',sid,f.iloc[-1].date,limit=None) if r.get('date') in dates]
    if {r['date'] for r in rows}!=dates:return {}
    nets=[sum(float(r.get('buy',0))-float(r.get('sell',0)) for r in rows if r['date']==d) for d in dates]
    return {'institutional_selling':all(v<0 for v in nets),'institutional_buying':all(v>0 for v in nets)}

def scan():
    result=[]; errors=[]
    with Session() as s:
        cfg=settings(s);index=features(bars(s,'TAIEX')); market=market_state(index)
        calendar=set(index.date.tail(cfg['stock_pool']['volume_filter']['lookback_trading_days'])) if len(index) else set()
        ids=[x[0] for x in s.query(Bar.stock_id).group_by(Bar.stock_id).having(func.count(Bar.date)>=60) if x[0]!='TAIEX']
        for sid in ids:
            try:
                st=s.get(Stock,sid)
                if not st: continue
                f=features(bars(s,sid),cfg.get('rule_params')); x=f.iloc[-1]
                metadata=json.loads(st.payload)
                metadata.update(institutional_direction(s,sid,f))
                ck=checks(f,metadata,cfg,market,x.date)
                ck.append({'name':'日均量窗口完整','passed':bool(calendar and calendar.issubset(set(f.date))),'reason':'大盤交易日缺漏不能當作零成交量或壓縮掉','hard':True})
                signals=detect(f,params=cfg.get('rule_params'))
                long_ck=checks(f,metadata,cfg,market,x.date,'long')
                short_ck=checks(f,metadata,cfg,market,x.date,'short')
                complete_window=bool(calendar and calendar.issubset(set(f.date)))
                verified=bool(f.tail(60).adjustment_verified.all())
                ck.append({'name':'最近60日還原價已驗證','reason':'來源未驗證時保留研究訊號，但不納入可交易候選','passed':verified,'hard':True})
                eligible_long=all(c['passed'] is True for c in long_ck if c['hard']) and complete_window and verified and x.date==market.get('date')
                eligible_short=all(c['passed'] is True for c in short_ck if c['hard']) and complete_window and verified and x.date==market.get('date')
                eligible=any((signal['direction']=='long' and eligible_long) or (signal['direction']=='short' and eligible_short) for signal in signals)
                row=clean({'id':sid,'name':st.name,'industry':st.industry,'date':x.date,'close':x.raw_close,'change':x.change,'volume_ratio':x.volume_ratio,'return20':x.return20,'relative_strength':x.return20-index.iloc[-1].return20 if len(index) else None,'trend':x.trend,'signals':signals,'checks':ck,'eligible_long':eligible_long,'eligible_short':eligible_short,'eligible':eligible,'status':'candidate' if eligible and signals else 'watch' if signals else 'none'})
                result.append(row)
            except Exception as exc:
                errors.append({'id':sid,'error':type(exc).__name__})
    result.sort(key=lambda x:x['return20'] if x['return20'] is not None else -999,reverse=True)
    industries={}
    for row in result:
        if row['return20'] is not None: industries.setdefault(row['industry'],[]).append(row['return20'])
    ranks=sorted([{'industry':key,'return20':sum(vals)/len(vals),'stocks':len(vals)} for key,vals in industries.items()],key=lambda x:x['return20'],reverse=True)
    payload={'updated_at':now(),'market':market,'rows':result,'industry_ranks':ranks,'errors':errors,'coverage':{'scanned':len(result),'description':'只掃描已有至少60日日K的股票；資料缺漏不視為無訊號。'}}
    with Session.begin() as s:
        put(s,'scan','latest',payload)
        for row in result:
            if row['signals']:
                put(s,'signals',row['id'],{'signals':row['signals']},row['date'])
                if any(x['id'] in ('L-RIGHT-FOOT','L-2ND-WAVE') or x['id'].startswith('L-BOTTOM') for x in row['signals']):
                    old=get(s,'watchlist',row['id'])
                    if not old: put(s,'watchlist',row['id'],{'added_at':now(),'reason':'底部／強勢股自動入選','automatic':True,'active':True})
            old=get(s,'watchlist',row['id'])
            if old and old.get('automatic') and old.get('active') and row['trend']=='bear':
                put(s,'watchlist',row['id'],{**old,'active':False,'removed_at':now(),'removal_reason':'趨勢轉空，移出自動鎖股候選'})
    return payload

def watchlist(s):
    latest=get(s,'scan','latest',default={'rows':[]})
    lookup={r['id']:r for r in latest['rows']}
    rows=[]
    for record in records(s,'watchlist'):
        sid=record['key']; st=s.get(Stock,sid); row=lookup.get(sid,{})
        rows.append({**record,'name':st.name if st else sid,'scan':row})
    return sorted(rows,key=lambda x:x['scan'].get('return20') or -999,reverse=True)

def portfolio(s):
    cfg=settings(s); rows=[]; invested=0; value=0; initial=cfg['backtest']['initial_capital']
    for item in records(s,'position'):
        f=features(bars(s,item['stock_id']))
        st=s.get(Stock,item['stock_id']); row={'id':item['key'],**item,'name':st.name if st else item['stock_id']}
        invested+=item['entry_price']*item['shares']
        if len(f):
            x=f.iloc[-1]; side=1 if item['direction']=='long' else -1
            profit=side*(x.raw_close/item['entry_price']-1)
            # Position prices are actual trade prices, so evaluate in current raw scale.
            current=f.copy()
            # All historical observations stay on one scale; per-day division
            # would reintroduce ex-dividend gaps into otherwise adjusted candles.
            current_scale=float(x.factor)
            for col in ('close','open','high','low','ma3','ma5','ma10','ma20','ma60','ma120','ma240','range_high','range_low','pivot_high5','pivot_low5','support_line5','resistance_line5','key_red_high','key_red_mid','key_red_low','key_black_high','key_black_mid','key_black_low','weekly_resistance','weekly_support','weekly_ma20'):
                if col in current:current[col]=current[col]/current_scale
            action=exit_signal(current,len(current)-1,item,cfg)
            days=(date.fromisoformat(x.date)-date.fromisoformat(item['entry_date'])).days
            row.update({'last_date':x.date,'close':x.raw_close,'return':profit,'pnl':profit*item['entry_price']*item['shares'],'action':action,'trapped_warning':profit<-.05,'slow_stock':days>=7 and profit<.05,'holding_days':days,'add_on_hint':0<=profit<.10 and x.volume_ratio>=1.3 and x.body>.02})
            value+=row['pnl']
        rows.append(clean(row))
    market=market_state(features(bars(s,'TAIEX')))
    months=sorted(records(s,'monthly_return'),key=lambda x:x['key'],reverse=True)
    return {'rows':rows,'invested':invested,'unrealized_pnl':value,'allocation':invested/initial,'market':market,'target':cfg['target_management'],'monthly_returns':months}

def review_positions():
    with Session.begin() as s:
        data=portfolio(s)
        for row in data['rows']:
            action=row.get('action',{})
            if action.get('action','hold')!='hold' or row.get('trapped_warning') or row.get('slow_stock'):
                key=f'{row["id"]}:{row["last_date"]}:{action.get("rule_id")}'
                if get(s,'alert',key): continue
                text=f'{row["stock_id"]} {row["name"]}：{action.get("reason","持股警示")}，報酬 {row.get("return",0):.1%}'
                put(s,'alert',key,{'position_id':row['id'],'text':text,'action':action,'status':'pending','created_at':now(),'attempts':0},row['last_date'])
    return data
