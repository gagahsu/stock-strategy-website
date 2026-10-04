import hmac
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func
from .db import Session, Stock, Bar, Record, ROOT, settings, put, get, records, bars, now
from .features import features, clean
from .rules import CATALOGUE, BY_ID, market_state
from .service import stock_data, scan, watchlist, portfolio, review_positions
from .backtest import simulate
from . import ingest
from .notifications import dispatch

@asynccontextmanager
async def lifespan(app):
    # A single local API process owns the executor. Interrupted tasks are explicit.
    with Session.begin() as s:
        for job in records(s,'job'):
            if job.get('status') in ('queued','running'):
                put(s,'job',job['key'],{**job,'status':'interrupted','finished_at':now(),'error':'服務重新啟動，請重新執行；已完成資料與結果保留。'})
    yield

app=FastAPI(title='台股策略研究 API',version='1.0.0',lifespan=lifespan)
pool=ThreadPoolExecutor(max_workers=1)

@app.middleware('http')
async def access(request:Request,call_next):
    secret=os.getenv('API_TOKEN','')
    supplied=request.headers.get('Authorization','').removeprefix('Bearer ')
    peer=request.client.host if request.client else ''
    if secret and not hmac.compare_digest(supplied,secret): return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'需要有效存取憑證'},401)
    if not secret and peer not in ('127.0.0.1','::1','testclient'): return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'未設定憑證時僅允許本機存取'},403)
    if request.method in ('POST','PUT','DELETE') and request.headers.get('origin'):
        origin=request.headers['origin']
        allowed=os.getenv('APP_ORIGIN','http://localhost:3000').split(',')+['http://127.0.0.1:3000']
        if origin not in allowed: return __import__('starlette.responses',fromlist=['JSONResponse']).JSONResponse({'detail':'來源不允許'},403)
    return await call_next(request)

@app.exception_handler(ValueError)
async def invalid(request,exc):
    from fastapi.responses import JSONResponse
    return JSONResponse({'detail':str(exc)},422)

def task(kind,fn):
    id=str(uuid.uuid4())
    with Session.begin() as s: put(s,'job',id,{'kind':kind,'status':'queued','created_at':now()})
    def run():
        with Session.begin() as s: put(s,'job',id,{'kind':kind,'status':'running','created_at':now()})
        try:
            result=fn()
            data={'kind':kind,'status':'done','finished_at':now(),'result':clean(result)}
        except Exception as exc:
            data={'kind':kind,'status':'failed','finished_at':now(),'error':str(exc)}
        with Session.begin() as s: put(s,'job',id,data)
    pool.submit(run)
    return {'job_id':id}

@app.get('/api/health')
def health(): return {'status':'ok','version':'1.0.0'}

@app.get('/api/status')
def status():
    with Session() as s:
        counts=s.query(Bar.stock_id,func.count(Bar.date),func.min(Bar.date),func.max(Bar.date),func.sum(Bar.adjustment_verified)).group_by(Bar.stock_id).all()
        return {'stocks':s.query(Stock).count(),'bars':s.query(Bar).count(),'coverage':[{'id':id,'rows':n,'first':first,'last':last,'verified':int(verified or 0)} for id,n,first,last,verified in counts],'ingest':records(s,'ingest'),'bulk':get(s,'bulk','latest'),'quality':get(s,'quality_summary','latest'),'jobs':records(s,'job')[:20],'line_configured':bool(os.getenv('LINE_CHANNEL_ACCESS_TOKEN') and os.getenv('LINE_RECIPIENT_USER_ID'))}

@app.get('/api/stocks')
def stocks(q:str='',limit:int=100):
    with Session() as s:
        query=s.query(Stock)
        if q: query=query.filter((Stock.id.contains(q)) | (Stock.name.contains(q)))
        return [{'id':x.id,'name':x.name,'market':x.market,'industry':x.industry} for x in query.order_by(Stock.id).limit(min(max(limit,1),4000))]

@app.get('/api/stock/{sid}')
def stock(sid:str,period:str='day',end:str|None=None):
    if period not in ('day','week','month'): raise ValueError('不支援的週期')
    with Session() as s: return stock_data(s,sid,period,end)

@app.get('/api/rules')
def rules(): return CATALOGUE

@app.get('/api/settings')
def get_settings():
    with Session() as s: return settings(s)

def validate_settings(cfg):
    required=json.loads((ROOT/'config/defaults.json').read_text(encoding='utf-8'))
    if set(required)-set(cfg): raise ValueError('缺少必要設定')
    for ratio in [cfg['risk']['max_loss_ratio'],cfg['risk'].get('strategy_stop_ratio',.05),cfg['target_management']['monthly_target_return']]:
        if not isinstance(ratio,(int,float)) or not 0<ratio<1: raise ValueError('比例必須大於0且小於100%')
    if not 0<cfg['backtest']['initial_capital']<1e12: raise ValueError('本金範圍錯誤')
    v=cfg['stock_pool']['volume_filter']
    if not isinstance(v['lookback_trading_days'],int) or not 1<=v['lookback_trading_days']<=240: raise ValueError('日均量期間須為1~240交易日')
    if not 0<=v['minimum_lots']<=1e9: raise ValueError('成交量門檻不合法')
    profiles=cfg['broker_profiles']; ids=[x['id'] for x in profiles]
    if not profiles or len(ids)!=len(set(ids)) or cfg['backtest']['broker_profile_id'] not in ids: raise ValueError('券商方案ID重複或預設方案不存在')
    for p in profiles:
        if not 0<=p['commission_base_rate']<=.1 or not 0<=p['commission_discount_multiplier']<=1 or not 0<=p.get('minimum_commission',20)<=10000: raise ValueError('券商費率範圍錯誤')
    if cfg['backtest'].get('allow_day_trading'): raise ValueError('第一版不支援當沖')
    if cfg['target_management']['stage'] not in ('beginner','advanced','ultimate'):raise ValueError('目標階段錯誤')
    for key in ('exclude_full_delivery','exclude_disposition','exclude_etf','exclude_ky'):
        if not isinstance(cfg['stock_pool'][key],bool):raise ValueError('股票池開關須為布林值')
    for key,low,high in [('body_threshold',.001,.2),('attack_volume_ratio',.1,20),('explosive_volume_ratio',.1,50),('range_width',.001,1),('tangle_spread',.001,.5),('range_days',3,120)]:
        if not low<=cfg['rule_params'][key]<=high:raise ValueError('規則參數範圍錯誤：'+key)
    if not isinstance(cfg['rule_params']['range_days'],int):raise ValueError('盤整期間須為整數')
    if not 0<cfg['scanner']['max_allocation']<=.9 or not 0<=cfg['scanner']['minimum_price']<=1e6:raise ValueError('投入比例或價格門檻錯誤')

@app.put('/api/settings')
def save_settings(cfg:dict):
    try: validate_settings(cfg)
    except (KeyError,TypeError,OverflowError) as exc: raise ValueError('設定欄位缺漏或型別錯誤') from exc
    with Session.begin() as s: put(s,'settings','active',cfg)
    return cfg

class IngestRequest(BaseModel):
    command:str='history'
    stock_ids:list[str]=Field(default_factory=list,max_length=4000)
    years:int=Field(10,ge=1,le=20)

@app.post('/api/ingest')
def ingest_job(req:IngestRequest):
    if req.command=='daily': return task('daily',lambda:{'daily':ingest.daily(),'restrictions':ingest.restrictions()})
    if req.command=='list': return task('list',lambda:{'stocks':ingest.stock_list(),'profiles':ingest.company_profiles()})
    if req.command!='history': raise ValueError('不支援的抓取命令')
    with Session() as s:
        if any(not s.get(Stock,sid) for sid in req.stock_ids): raise ValueError('股票代號不存在')
    return task('history',lambda:ingest.backfill(req.stock_ids or None,req.years))

@app.get('/api/jobs/{id}')
def job(id:str):
    with Session() as s: return get(s,'job',id,default={'status':'not_found'})


@app.post('/api/bulk/{command}')
def bulk(command:str):
    flag=ROOT/'data'/'STOP_BACKFILL'
    if command=='stop':
        flag.touch()
        return {'status':'stopping','message':'目前請求完成後停止，已完成資料會保留。'}
    if command!='start':raise ValueError('不支援的批次操作')
    import subprocess,sys
    if flag.exists():flag.unlink()
    log=(ROOT/'data'/'bulk.log').open('a',encoding='utf-8')
    errors=(ROOT/'data'/'bulk-error.log').open('a',encoding='utf-8')
    process=subprocess.Popen([sys.executable,'-m','backend.worker','--years','10'],cwd=ROOT,stdout=log,stderr=errors,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    log.close();errors.close()
    return {'status':'starting','pid':process.pid}

@app.get('/api/scan')
def latest_scan():
    with Session() as s: return get(s,'scan','latest',default={'rows':[],'industry_ranks':[],'market':{},'updated_at':None})

@app.post('/api/scan')
def run_scan(): return task('scan',scan)

@app.get('/api/watchlist')
def get_watchlist():
    with Session() as s: return watchlist(s)

class Watch(BaseModel):
    stock_id:str
    reason:str=Field('手動鎖股',max_length=500)

@app.post('/api/watchlist')
def add_watch(req:Watch):
    with Session.begin() as s:
        if not s.get(Stock,req.stock_id): raise ValueError('找不到股票')
        put(s,'watchlist',req.stock_id,{'added_at':now(),'reason':req.reason,'automatic':False,'active':True})
    return {'ok':True}

@app.delete('/api/watchlist/{sid}')
def remove_watch(sid:str):
    with Session.begin() as s:
        r=s.get(Record,('watchlist',sid,''))
        if r: s.delete(r)
    return {'ok':True}

class BT(BaseModel):
    stock_ids:list[str]=Field(min_length=1,max_length=100)
    start:str
    end:str
    initial_capital:float=Field(300000,gt=0,le=1e12)
    broker_profile_id:str='default'
    rule_ids:list[str]=Field(default_factory=lambda:['L-ENTRY-4'])
    direction:str='long'
    exit_mode:str='swing'
    stop_method:str='fixed'
    max_positions:int=Field(2,ge=1,le=5)
    allocation:float=Field(.7,gt=0,le=.9)
    capital_model:str='fixed'
    slippage:float=Field(.001,ge=0,le=.1)
    sell_tax_rate:float=Field(.003,ge=0,le=.1)
    annual_short_borrow_rate:float=Field(.03,ge=0,le=1)
    allow_unadjusted:bool=False
    market_filter:bool=True
    out_of_sample_fraction:float=Field(.3,gt=0,lt=.8)
    @model_validator(mode='after')
    def validate_dates(self):
        date.fromisoformat(self.start); date.fromisoformat(self.end)
        if self.start>=self.end: raise ValueError('期間錯誤')
        if self.direction not in ('long','short') or self.exit_mode not in ('swing','long','hot','scale','kline','ma5','ma10'): raise ValueError('方向或出場模組錯誤')
        if self.stop_method not in ('fixed','kline','trend','ma','support'):raise ValueError('停損方法錯誤')
        if self.capital_model not in ('fixed','market'):raise ValueError('資金模型錯誤')
        if any(x not in BY_ID for x in self.rule_ids): raise ValueError('規則不存在')
        if not self.rule_ids or any(BY_ID[x]['direction']!=self.direction for x in self.rule_ids):raise ValueError('進場規則與方向不符')
        return self

def backtest_pool(s,ids,start,end):
    metadata={x.id:json.loads(x.payload) for x in s.query(Stock).filter(Stock.id.in_(ids))}
    snapshots={(r.key,r.date):json.loads(r.payload) for r in s.query(Record).filter(Record.kind=='restriction_snapshot',Record.key.in_(ids),Record.date>=start,Record.date<=end)}
    return metadata,snapshots

@app.post('/api/backtests')
def backtest(req:BT):
    with Session() as s:
        if req.broker_profile_id not in {x['id'] for x in settings(s)['broker_profiles']}: raise ValueError('券商方案不存在')
    id=str(uuid.uuid4())
    def run():
        with Session() as s:
            frames={sid:bars(s,sid,req.end) for sid in req.stock_ids}
            cfg=settings(s);market=features(bars(s,'TAIEX',req.end))
            metadata,snapshots=backtest_pool(s,req.stock_ids,req.start,req.end)
            result=simulate(frames,cfg,req.model_dump(),market,metadata,snapshots)
            dates=sorted({d for f in frames.values() if len(f) for d in f.date if req.start<=d<=req.end})
            if len(dates)>=10:
                oos_start=dates[int(len(dates)*(1-req.out_of_sample_fraction))]
                oos_params={**req.model_dump(),'start':oos_start}
                result['out_of_sample']=simulate(frames,cfg,oos_params,market,metadata,snapshots)
                result['out_of_sample']['label']=f'末段{req.out_of_sample_fraction:.0%}保留期間；同參數重新從現金開始，未經參數調校。'
        with Session.begin() as s: put(s,'backtest',id,result)
        return {'run_id':id,'summary':result['summary']}
    return {**task('backtest',run),'run_id':id}


class Comparison(BaseModel):
    base:BT
    stop_ratios:list[float]=Field(default_factory=lambda:[.03,.05,.07],min_length=1,max_length=4)
    exit_modes:list[str]=Field(default_factory=lambda:['swing','long','kline'],min_length=1,max_length=5)
    @model_validator(mode='after')
    def validate(self):
        if any(not 0<v<1 for v in self.stop_ratios):raise ValueError('停損比例範圍錯誤')
        if any(v not in ('swing','long','kline','scale','hot','ma5','ma10') for v in self.exit_modes):raise ValueError('出場模組錯誤')
        return self


@app.post('/api/backtest-comparison')
def compare(req:Comparison):
    ids=[str(uuid.uuid4()) for _ in range(len(req.stop_ratios)*len(req.exit_modes))]
    def run():
        import copy
        with Session() as s:
            cfg=settings(s)
            if req.base.broker_profile_id not in {x['id'] for x in cfg['broker_profiles']}:raise ValueError('券商方案不存在')
            frames={sid:bars(s,sid,req.base.end) for sid in req.base.stock_ids}
            market=features(bars(s,'TAIEX',req.base.end))
            metadata,snapshots=backtest_pool(s,req.base.stock_ids,req.base.start,req.base.end)
        index=0;out=[]
        dates=sorted({d for f in frames.values() if len(f) for d in f.date if req.base.start<=d<=req.base.end})
        for ratio in req.stop_ratios:
            for mode in req.exit_modes:
                config=copy.deepcopy(cfg);config['risk']['strategy_stop_ratio']=ratio
                params={**req.base.model_dump(),'exit_mode':mode}
                result=simulate(frames,config,params,market,metadata,snapshots)
                if len(dates)>=10:
                    boundary=dates[int(len(dates)*(1-req.base.out_of_sample_fraction))]
                    result['out_of_sample']=simulate(frames,config,{**params,'start':boundary},market,metadata,snapshots)
                    result['out_of_sample']['label']='相同保留期間比較；多次查看／挑選參數後，這段期間不能再視為未接觸樣本。'
                with Session.begin() as s:put(s,'backtest',ids[index],result)
                out.append({'run_id':ids[index],'stop_ratio':ratio,'exit_mode':mode,'summary':result['summary']});index+=1
        return {'comparisons':out}
    return {**task('comparison',run),'run_ids':ids}

@app.get('/api/backtests')
def backtests():
    with Session() as s: return [{'id':r['key'],'summary':r['summary'],'params':r['params']} for r in records(s,'backtest')]

@app.get('/api/backtests/{id}')
def backtest_result(id:str):
    with Session() as s:
        result=get(s,'backtest',id)
        if result is None: raise HTTPException(404,'結果尚未完成')
        return result

class Position(BaseModel):
    stock_id:str
    entry_date:str
    entry_price:float=Field(gt=0)
    shares:int=Field(gt=0,le=100000000)
    direction:str='long'
    stop_price:float|None=Field(None,gt=0)
    exit_mode:str='swing'
    scaled_fraction:float=Field(0,ge=0,lt=1)
    @model_validator(mode='after')
    def validate(self):
        date.fromisoformat(self.entry_date)
        if self.entry_date>date.today().isoformat(): raise ValueError('進場日不能在未來')
        if self.direction not in ('long','short') or self.exit_mode not in ('swing','long','hot','scale','kline','ma5','ma10'): raise ValueError('方向或出場模組錯誤')
        if self.stop_price and (self.stop_price>=self.entry_price if self.direction=='long' else self.stop_price<=self.entry_price): raise ValueError('停損價須在進場價的虧損側')
        return self

@app.get('/api/portfolio')
def get_portfolio():
    with Session() as s: return portfolio(s)

@app.post('/api/portfolio')
def add_position(req:Position):
    id=str(uuid.uuid4())
    with Session.begin() as s:
        if not s.get(Stock,req.stock_id): raise ValueError('股票不存在')
        put(s,'position',id,{**req.model_dump(),'created_at':now()})
    return {'id':id}

@app.put('/api/portfolio/{id}')
def edit_position(id:str,req:Position):
    with Session.begin() as s:
        old=get(s,'position',id)
        if old is None:raise HTTPException(404,'持股不存在')
        if not s.get(Stock,req.stock_id):raise ValueError('股票不存在')
        put(s,'position',id,{**req.model_dump(),'created_at':old['created_at'],'updated_at':now()})
    return {'id':id}

@app.delete('/api/portfolio/{id}')
def remove_position(id:str):
    with Session.begin() as s:
        r=s.get(Record,('position',id,''))
        if r: s.delete(r)
    return {'ok':True}

@app.post('/api/portfolio/review')
def review(): return task('review',lambda:{'portfolio':review_positions(),'notifications':dispatch()})

@app.put('/api/monthly-return/{month}')
def monthly(month:str,data:dict):
    if not re.fullmatch(r'\d{4}-\d{2}',month): raise ValueError('月份格式錯誤')
    date.fromisoformat(month+'-01')
    value=float(data['return'])
    if not -1<=value<=10: raise ValueError('報酬比例不合法')
    with Session.begin() as s: put(s,'monthly_return',month,{'return':value,'updated_at':now()})
    return {'ok':True}

@app.get('/api/alerts')
def alerts():
    with Session() as s: return records(s,'alert')

@app.post('/api/notifications/preview')
def preview_notifications(): return dispatch(dry_run=True)

@app.get('/api/notes/{chapter}')
def notes(chapter:str):
    if not re.fullmatch(r'Part\d{2}',chapter): raise ValueError('章節格式錯誤')
    paths=list((ROOT/'docs/notes').glob(chapter+'_*.md'))
    if not paths: raise HTTPException(404,'章節不存在')
    return {'text':paths[0].read_text(encoding='utf-8')}

@app.get('/api/scan-presets')
def presets():
    with Session() as s: return records(s,'scan_preset')

@app.post('/api/scan-presets')
def save_preset(data:dict):
    name=str(data.get('name','')).strip()
    if not name or len(name)>100: raise ValueError('請輸入1~100字名稱')
    with Session.begin() as s: put(s,'scan_preset',str(uuid.uuid4()),{'name':name,'filters':data.get('filters',{}),'created_at':now()})
    return {'ok':True}
