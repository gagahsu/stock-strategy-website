import argparse
import json
import os
import re
import time
import csv
import math
from io import StringIO
from datetime import date, timedelta
import httpx
from sqlalchemy import or_
from .db import Session, Stock, Bar, Record, put, get, now

FIN = 'https://api.finmindtrade.com/api/v4/data'
TWSE = 'https://openapi.twse.com.tw/v1'
TPEX = 'https://www.tpex.org.tw/openapi/v1'

def fetch(url, params=None):
    for attempt in range(4):
        try:
            headers={'Accept':'text/csv'} if 'tpex.org.tw/openapi/v1' in url else {'Accept':'application/json'}
            r = httpx.get(url, params=params, headers=headers, timeout=45, follow_redirects=True)
            r.raise_for_status()
            data = list(csv.DictReader(StringIO(r.text.lstrip('\ufeff')))) if 'text/csv' in r.headers.get('content-type','') else r.json()
            if isinstance(data, dict) and data.get('status',200) != 200:
                raise ValueError(f"Data provider status {data.get('status')}: {data.get('msg','request failed')}")
            return data
        except (httpx.HTTPError, ValueError) as exc:
            quota=isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code==402
            if attempt == 3 or quota:
                status=f' HTTP {exc.response.status_code}' if isinstance(exc,httpx.HTTPStatusError) else ''
                # HTTP errors retain the authenticated URL; omit their traceback chain.
                raise RuntimeError(f'資料來源暫時不可用：{url.split("?")[0]} ({type(exc).__name__}{status})') from None
            time.sleep(min(2 ** attempt, 8))

def fin(dataset, stock_id=None, start=None, end=None):
    params = {'dataset':dataset}
    for key, value in [('data_id',stock_id),('start_date',start),('end_date',end),('token',os.getenv('FINMIND_TOKEN'))]:
        if value:
            params[key] = value
    return fetch(FIN, params).get('data', [])

def num(value):
    try:
        return float(str(value).replace(',','').replace(' ',''))
    except (ValueError,TypeError):
        return None

def iso(value):
    text = re.sub(r'[^0-9]', '', str(value))
    if len(text)==7:
        return f'{int(text[:3])+1911}-{text[3:5]}-{text[5:7]}'
    if len(text)==8:
        return f'{text[:4]}-{text[4:6]}-{text[6:8]}'
    raise ValueError('Invalid provider date')

def bar_values(stock_id, row):
    vals = [num(row[x]) for x in ('open','high','low','close','volume')]
    if any(x is None or not math.isfinite(x) for x in vals) or min(vals[:4])<=0 or vals[4]<0:
        return None
    o,h,l,c,v = vals
    if h < max(o,c,l) or l > min(o,c,h):
        raise ValueError(f'OHLC invalid: {stock_id} {row["date"]}')
    return {'open':o,'high':h,'low':l,'close':c,'volume':v}

def save_bar(s, stock_id, row):
    values=bar_values(stock_id,row)
    if values is None:return False
    old = s.get(Bar, (stock_id,row['date']))
    source=row.get('source','FinMind')
    if old:
        for key,value in {**values,'source':source}.items():setattr(old,key,value)
    else:
        if s.get_bind().dialect.name=='sqlite':
            from sqlalchemy.dialects.sqlite import insert
        else:
            from sqlalchemy.dialects.postgresql import insert
        statement=insert(Bar).values(stock_id=stock_id,date=row['date'],**values,
                                    factor=1.,adjustment_verified=0,source=source)
        # A parallel provider may create this row after the lookup. Keep its factors.
        s.execute(statement.on_conflict_do_update(index_elements=['stock_id','date'],
                    set_={**values,'source':source}))
    return True

def stock_list():
    raw = fin('TaiwanStockInfo')
    latest={}
    for x in sorted(raw,key=lambda x:x.get('date','')):
        latest[x['stock_id']]=x
    rows=list(latest.values())
    count = 0
    with Session.begin() as s:
        for x in rows:
            market = x.get('type','')
            if market not in ('twse','tpex'):
                continue
            sid = x['stock_id']
            # Ordinary equities and ETF codes; exclude warrants and bonds.
            if not (len(sid)==4 and sid.isdigit() or sid.startswith('00') and len(sid)<=6):
                continue
            old = s.get(Stock,sid)
            payload = json.loads(old.payload) if old else {}
            payload.update({'is_etf':sid.startswith('00'),'is_ky':'KY' in x.get('stock_name','')})
            s.merge(Stock(id=sid,name=x['stock_name'],market=market,industry=x.get('industry_category','其他'),payload=json.dumps(payload,ensure_ascii=False)))
            count += 1
        s.merge(Stock(id='TAIEX',name='加權指數',market='index',industry='指數',payload='{}'))
        put(s,'ingest','stock_list',{'count':count,'updated_at':now()})
    return count


def company_profiles():
    report={}
    for market,url in [('twse',TWSE+'/opendata/t187ap03_L'),('tpex',TPEX+'/mopsfin_t187ap03_O')]:
        try:
            rows=fetch(url);count=0
            with Session.begin() as s:
                for row in rows:
                    # TPEx exposes Chinese CSV headings and English JSON keys.
                    sid=row.get('公司代號',row.get('SecuritiesCompanyCode'))
                    st=s.get(Stock,str(sid or ''))
                    if not st:continue
                    capital=num(row.get('實收資本額',row.get('Paidin.Capital.NTDollars')))
                    capital_date=iso(row.get('出表日期',row.get('Date')))
                    payload=json.loads(st.payload)
                    payload.update({'paid_in_capital':capital,'capital_date':capital_date,'company_profile':row})
                    st.payload=json.dumps(payload,ensure_ascii=False);count+=1
                put(s,'ingest','profiles_'+market,{'rows':count,'updated_at':now()})
            report[market]=count
        except Exception as exc:report[market]=str(exc)
    return report

def restrictions():
    report = {}
    for market, base, altered, punish in [('twse',TWSE,'/exchangeReport/TWT85U','/announcement/punish'),('tpex',TPEX,'/tpex_cmode','/tpex_disposal_information')]:
        try:
            a,p = fetch(base+altered),fetch(base+punish)
            today = date.today().isoformat()
            with Session.begin() as s:
                changed = {str(x.get('Code',x.get('SecuritiesCompanyCode',x.get('SecuritiesCode','')))) for x in a if market=='twse' or x.get('AlteredTrading','').strip() not in ('','否','N','0')}
                disposed = set()
                for x in p:
                    period = x.get('DispositionPeriod',x.get('DisposalPeriod',''))
                    dates = re.findall(r'\d{3,4}/\d{2}/\d{2}',period)
                    if len(dates)==2 and iso(dates[0]) <= today <= iso(dates[1]):
                        disposed.add(str(x.get('Code',x.get('SecuritiesCompanyCode',x.get('SecuritiesCode','')))))
                for st in s.query(Stock).filter_by(market=market):
                    data = json.loads(st.payload)
                    data.update({'full_delivery':st.id in changed,'disposition':st.id in disposed,'restrictions_date':today})
                    st.payload = json.dumps(data,ensure_ascii=False)
                    put(s,'restriction_snapshot',st.id,data,today)
                put(s,'ingest','restrictions_'+market,{'updated_at':now(),'date':today,'status':'ok'})
            report[market]='ok'
        except Exception as exc:
            report[market]=str(exc)
    return report

def daily():
    report = {}
    for market, url in [('twse',TWSE+'/exchangeReport/STOCK_DAY_ALL'),('tpex',TPEX+'/tpex_mainboard_daily_close_quotes')]:
        try:
            rows = fetch(url)
            n=0
            with Session.begin() as s:
                from .universe import pool_stocks
                from .db import settings
                known = {x.id for x in pool_stocks(s,settings(s)) if x.market==market}
                for x in rows:
                    sid = x.get('Code',x.get('SecuritiesCompanyCode',x.get('SecuritiesCode','')))
                    if sid not in known:
                        continue
                    row={'date':iso(x['Date']), 'source':market.upper(),'open':x.get('OpeningPrice',x.get('Open')),'high':x.get('HighestPrice',x.get('High')),'low':x.get('LowestPrice',x.get('Low')),'close':x.get('ClosingPrice',x.get('Close')),'volume':x.get('TradeVolume',x.get('TradingShares'))}
                    n += save_bar(s,sid,row)
                put(s,'ingest','daily_'+market,{'rows':n,'updated_at':now()})
            report[market]=n
        except Exception as exc:
            report[market]=str(exc)
    return report

def history(sid, start, end=None, extras=True):
    end=end or date.today().isoformat()
    fid = 'TAIEX' if sid=='TAIEX' else sid
    with Session() as s: checkpoint=get(s,'ingest',sid,default={})
    prior=checkpoint.get('status') in ('partial','ok') and bool(checkpoint.get('start') and checkpoint.get('end'))
    resumed=prior and checkpoint['start']<=start and checkpoint['end']>=end
    effective_start=min(start,checkpoint['start']) if prior else start
    effective_end=max(end,checkpoint['end']) if prior else end
    if resumed:
        with Session() as s:
            resumed=bool(s.query(Bar.date).filter(Bar.stock_id==sid,Bar.date>=effective_start,Bar.date<=effective_end).first())
    same_range=prior and effective_start==checkpoint['start'] and effective_end==checkpoint['end']
    completed=list(checkpoint.get('completed_datasets',[])) if same_range else []
    # Bridge any gap when a later daily update extends an existing history interval.
    fetch_start=min(start,checkpoint['end']) if prior and end>checkpoint['end'] else start
    fetch_end=max(end,checkpoint['start']) if prior and start<checkpoint['start'] else end
    rows=[] if resumed else fin('TaiwanStockPrice',fid,fetch_start,fetch_end)
    rejected=list(checkpoint.get('rejected_dates',[])) if prior else []
    with Session.begin() as s:
        for x in rows:
            try:
                if not save_bar(s,sid,{'date':x['date'],'open':x['open'],'high':x['max'],'low':x['min'],'close':x['close'],'volume':x['Trading_Volume']}):
                    raise ValueError('非有效成交行情，未填補K線')
            except (ValueError,KeyError) as exc:
                rejected.append(x.get('date','unknown'))
                put(s,'rejected_bar',sid,{'row':x,'reason':str(exc),'updated_at':now()},x.get('date','unknown'))
        rejected=sorted(set(rejected))
        row_count=s.query(Bar).filter(Bar.stock_id==sid,Bar.date>=effective_start,Bar.date<=effective_end).count()
        put(s,'ingest',sid,{'start':effective_start,'end':effective_end,'rows':row_count,'rejected_dates':rejected,'updated_at':now(),'status':'partial','completed_datasets':completed,'warnings':[] if row_count else ['尚未取得有效日K']})
    if not row_count:
        raise RuntimeError('尚未取得有效日K；保留待補狀態，稍後重新取價')
    errors=[]
    auxiliary_failure=None
    # Free ex-dividend and capital-reduction reference prices, paid feed optional.
    try:
        from .adjustments import rebuild
        with Session() as s:
            first=s.query(Bar).filter_by(stock_id=sid).order_by(Bar.date).first()
            adjustment_start=first.date if first else start
            previous=get(s,'adjustment_audit',sid,default={})
            actions=get(s,'corporate_actions',sid,previous.get('end',''),default={})
            bad=s.query(Bar.date).filter(Bar.stock_id==sid,Bar.date<=effective_end,or_(
                Bar.adjustment_verified!=1,Bar.adjustment_verified.is_(None),
                Bar.factor.is_(None),Bar.factor<=0,Bar.factor>=float('inf'))).first()
            reusable=bool(first and first.date<=effective_end and
                previous.get('method')=='free_reference_price' and
                previous.get('start','9999')<=adjustment_start and previous.get('end','')>=effective_end and
                actions.get('method')=='reference_price_backward_factor' and
                isinstance(actions.get('rows'),list) and isinstance(actions.get('reductions'),list) and not bad)
        if not reusable:rebuild(sid,adjustment_start,effective_end)
    except Exception:
        errors.append('還原價尚未取得；回測將拒絕未驗證的區間')
        # Preserve raw-loaded checkpoint and stop request fan-out after quota failure.
        with Session.begin() as s:put(s,'ingest',sid,{'start':effective_start,'end':effective_end,'rows':row_count,'rejected_dates':rejected,'status':'partial','warnings':errors,'completed_datasets':completed,'updated_at':now()})
        raise RuntimeError('還原價來源暫時不可用；保留原始資料，稍後續跑')
    if extras and sid!='TAIEX':
        for dataset, kind in [('TaiwanStockInstitutionalInvestorsBuySell','chips_daily'),('TaiwanStockMarginPurchaseShortSale','margin_daily'),('TaiwanStockMonthRevenue','fundamentals'),('TaiwanStockFinancialStatements','financials')]:
            if dataset in completed:continue
            try:
                data=fin(dataset,sid,effective_start,effective_end)
                with Session.begin() as s:
                    # Whole provider response retained to audit exact published field names.
                    put(s,kind,sid,{'rows':data,'fetched_at':now(),'source':FIN,'dataset':dataset,'start':effective_start,'end':effective_end},effective_end)
                completed.append(dataset)
                with Session.begin() as s:put(s,'ingest',sid,{'start':effective_start,'end':effective_end,'rows':row_count,'rejected_dates':rejected,'status':'partial','completed_datasets':completed,'updated_at':now()})
            except Exception as exc:
                auxiliary_failure=exc
                errors.append(dataset+' 尚未取得')
                break
    with Session.begin() as s:
        put(s,'ingest',sid,{'start':effective_start,'end':effective_end,'rows':row_count,'rejected_dates':rejected,'updated_at':now(),'status':'partial' if errors else 'ok','warnings':errors,'completed_datasets':completed,'extras_completed':not errors and (extras or sid=='TAIEX' or same_range and checkpoint.get('extras_completed',False))})
    if errors:raise RuntimeError('輔助資料尚未齊全；保留進度，稍後續跑') from auxiliary_failure
    return {'stock_id':sid,'rows':row_count,'warnings':errors}

def backfill(ids=None, years=10, extras=True):
    start=(date.today()-timedelta(days=365*years+3)).isoformat()
    with Session() as s:
        ids=ids or [x.id for x in s.query(Stock).order_by(Stock.id)]
    outcomes=[]
    for sid in ids:
        with Session() as s:
            checkpoint=get(s,'ingest',sid,default={})
        # Re-fetch entire interval when adjustment baseline changes; raw prices upsert.
        if checkpoint.get('status')=='ok' and (not extras or checkpoint.get('extras_completed')) and checkpoint.get('end')==date.today().isoformat() and checkpoint.get('start','9999')<=start:
            continue
        try:
            item=history(sid,start,extras=extras)
        except Exception as exc:
            item={'stock_id':sid,'error':str(exc)}
            # Quota/network failures must not fan out thousands of failing calls.
            outcomes.append(item)
            break
        outcomes.append(item)
        print(json.dumps(item,ensure_ascii=False),flush=True)
        time.sleep(float(os.getenv('DATA_REQUEST_INTERVAL','1')))
    return outcomes

def main():
    p=argparse.ArgumentParser()
    p.add_argument('command',choices=['list','daily','backfill','update'])
    p.add_argument('--stocks',default='')
    p.add_argument('--years',type=int,default=10)
    p.add_argument('--no-extras',action='store_true')
    args=p.parse_args()
    if args.command in ('list','update'):
        print('stocks',stock_list())
        print('restrictions',restrictions())
        print('company_profiles',company_profiles())
    if args.command in ('daily','update'):
        print('daily',daily())
    if args.command in ('backfill','update'):
        backfill(args.stocks.split(',') if args.stocks else None,args.years,not args.no_extras)

if __name__=='__main__':
    main()
