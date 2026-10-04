"""Daily event engine: close signals execute next open; stop gaps fill worse price."""
import math
import pandas as pd
from .features import clean, features
from .rules import detect, exit_signal, market_state, initial_stop

FORMULAS=[{'trades':20,'win_rate':.5,'win':.07,'loss':.05,'book_return':.2},{'trades':20,'win_rate':.6,'win':.07,'loss':.05,'book_return':.44},{'trades':30,'win_rate':.5,'win':.07,'loss':.05,'book_return':.3},{'trades':30,'win_rate':.6,'win':.07,'loss':.05,'book_return':.66},{'trades':12,'win_rate':7/12,'win':.20,'loss':.05,'book_return':1.15}]

def simulate(frames, settings, params, market=None, metadata=None, restrictions=None):
    capital=float(params.get('initial_capital',settings['backtest']['initial_capital']))
    if capital<=0: raise ValueError('初始資金需大於零')
    profiles={x['id']:x for x in settings['broker_profiles']}
    profile=profiles[params.get('broker_profile_id',settings['backtest']['broker_profile_id'])]
    fee=float(profile['commission_base_rate'])*float(profile['commission_discount_multiplier'])
    minimum=float(profile.get('minimum_commission',20))
    tax=float(params.get('sell_tax_rate',.003))
    slip=float(params.get('slippage',.001))
    borrow=float(params.get('annual_short_borrow_rate',.03))
    limit=int(params.get('max_positions',2)); limit=min(max(limit,1),5)
    mode=params.get('exit_mode','swing'); direction=params.get('direction','long')
    start=params['start']; end=params['end']
    if start>=end: raise ValueError('起日須早於迄日')
    selected=params.get('rule_ids') or ['L-ENTRY-4']
    usable={}
    for sid,df in frames.items():
        info=(metadata or {}).get(sid,{})
        pool=settings['stock_pool']
        if pool.get('exclude_etf') and info.get('is_etf') or pool.get('exclude_ky') and info.get('is_ky'):continue
        if df.empty: continue
        frame=df[df.date<=end].copy()
        prior=frame[frame.date<start]
        base=float(prior.iloc[-1].factor) if len(prior) else float(frame.iloc[0].factor)
        frame['factor']=frame.factor/base
        usable[sid]=features(frame,settings.get('rule_params'))
    if not usable: raise ValueError('股票池沒有歷史資料')
    unverified=[sid for sid,df in frames.items() if len(df) and not bool(df[df.date<=end].adjustment_verified.all())]
    anomalous=[sid for sid,df in usable.items() if bool(((df.date>=start)&(df.change.abs()>.25)).any())]
    if anomalous and not params.get('allow_unadjusted',False):raise ValueError('還原後仍有超過25%跳價，須核對特殊事件：'+','.join(anomalous))
    if unverified and not params.get('allow_unadjusted',False):
        raise ValueError('還原價未驗證：'+','.join(unverified)+'。請先補齊還原價；原始價研究模式必須明確開啟。')
    dates=sorted({d for df in usable.values() for d in df.date if start<=d<=end})
    if len(dates)<2: raise ValueError('回測期間至少需要2個交易日')
    maps={sid:{r.date:i for i,r in df.iterrows()} for sid,df in usable.items()}
    cash=capital; positions={}; pending=[]; trades=[]; equity=[]; warnings=[]
    if unverified: warnings.append('使用未驗證還原價，績效可能受除權息影響。')
    if anomalous:warnings.append('有異常跳價且已明確允許研究模式，請核對分割／合併／停牌等公告。')
    if mode=='scale':warnings.append('均線補回採FIFO批次成本；補回日整個部位不執行日內停損，以排除當沖，屬保守日K執行近似。')
    warnings.append('歷史處置、全額交割、券源及下市股票尚非完整逐日樣本；結果為研究模擬，含存活者偏差。')
    warnings.append('成交價格與股數採期初基準的還原價模型，非券商逐日現金／除權配股對帳；成本亦依模型成交金額計算。')
    def commission(value): return max(minimum,value*fee)
    def close(sid,p,row,fraction,reason,price=None):
        nonlocal cash
        side=p['side']; qty=max(1,math.floor(p['qty']*fraction)) if fraction<1 else p['qty']
        qty=min(qty,p['qty'])
        px=float(price if price is not None else row.open)*(1-side*slip)
        charge=commission(px*qty)+(px*qty*tax if side==1 else 0)
        remaining=qty
        for lot in p['lots']:
            count=min(remaining,lot['qty'])
            if not count:continue
            gross=side*(px-lot['price'])*count
            duration=(pd.Timestamp(row.date)-pd.Timestamp(lot['date'])).days
            short_charge=lot['price']*count*(tax+borrow*duration/365) if side==-1 else 0
            entry_fee=lot['fee']*count/lot['qty']
            exit_fee=charge*count/qty
            cash+=lot['price']*count+gross-exit_fee-short_charge
            net=gross-exit_fee-short_charge-entry_fee
            trades.append({'stock_id':sid,'direction':p['direction'],'entry_date':lot['date'],'exit_date':row.date,'entry_price':lot['price'],'exit_price':px,'shares':count,'gross_pnl':gross,'net_pnl':net,'return':net/(lot['price']*count+entry_fee),'holding_days':duration,'reason':reason,'entry_rule':p['entry_rule']})
            lot['fee']-=entry_fee;lot['qty']-=count;remaining-=count
            if not remaining:break
        p['qty']-=qty
        if p['qty']==0: positions.pop(sid,None)
        else:
            p['lots']=[lot for lot in p['lots'] if lot['qty']]
            p['entry_price']=sum(lot['qty']*lot['price'] for lot in p['lots'])/p['qty']
            if p['exit_mode']=='scale':p['scaled_fraction']=1-p['qty']/p['original_qty']
    for date in dates:
        retained=[]
        for order in pending:
            sid=order['stock_id']; idx=maps[sid].get(date)
            if idx is None: retained.append(order); continue
            row=usable[sid].iloc[idx]
            if row.volume<=0: retained.append(order); continue
            if order['type']=='exit' and sid in positions:
                p=positions[sid]
                if p['entry_date']!=date: close(sid,p,row,order['fraction'],order['reason'])
            elif order['type']=='restore' and sid in positions:
                p=positions[sid];side=p['side'];px=float(row.open)*(1+side*slip)
                target_qty=math.floor(p['original_qty']*order['fraction'])
                equity_now=equity[-1]['equity'] if equity else capital
                allocation=min(float(params.get('allocation',.7)),settings.get('scanner',{}).get('max_allocation',.9))
                if params.get('capital_model')=='market' and market is not None:allocation=market_state(market[market.date<date])['allocation']
                used=sum(pos['entry_price']*pos['qty'] for pos in positions.values())
                budget=min(cash,max(0,equity_now*allocation-used))
                qty=min(target_qty,math.floor(budget/(px*(1+fee))))
                if qty*px+commission(qty*px)>cash:qty-=1
                if qty>0:
                    charge=commission(qty*px);cash-=qty*px+charge
                    p['lots'].append({'qty':qty,'price':px,'date':date,'fee':charge})
                    p['qty']+=qty;p['entry_price']=sum(lot['qty']*lot['price'] for lot in p['lots'])/p['qty']
                    p['scaled_fraction']=max(0,1-p['qty']/p['original_qty'])
                    p['last_add_date']=date
            elif order['type']=='entry' and sid not in positions and len(positions)<limit:
                side=1 if order['direction']=='long' else -1
                allocation=float(params.get('allocation',.7))
                if params.get('capital_model')=='market' and market is not None:
                    allocation=market_state(market[market.date<date])['allocation']
                max_alloc=settings.get('scanner',{}).get('max_allocation',.9)
                allocation=min(allocation,max_alloc)
                px=float(row.open)*(1+side*slip)
                account_equity=equity[-1]['equity'] if equity else capital
                used=sum(p['entry_price']*p['qty'] for p in positions.values())
                budget=min(cash,account_equity*allocation/limit,max(0,account_equity*allocation-used))
                qty=math.floor(budget/(px*(1+fee)))
                if qty*px+commission(qty*px)>cash: qty-=1
                if qty<=0: continue
                value=qty*px; charge=commission(value); cash-=value+charge
                signal_bar=usable[sid].iloc[maps[sid][order['signal_date']]]
                stop=initial_stop(signal_bar,px,direction,params.get('stop_method','fixed'),settings)
                positions[sid]={'side':side,'direction':order['direction'],'qty':qty,'original_qty':qty,'entry_price':px,'entry_date':date,'entry_fee':charge,'stop_price':stop,'entry_rule':order['rule'],'exit_mode':mode,'scaled_fraction':0,'lots':[{'qty':qty,'price':px,'date':date,'fee':charge}]}
        pending=retained
        for sid,p in list(positions.items()):
            idx=maps[sid].get(date)
            if idx is None or p['entry_date']==date or p.get('last_add_date')==date: continue # first version excludes same-day round trips
            row=usable[sid].iloc[idx]
            if row.volume<=0: continue
            cap_stop=p['entry_price']*(1-p['side']*settings['risk']['max_loss_ratio'])
            stop=max(p['stop_price'],cap_stop) if p['side']==1 else min(p['stop_price'],cap_stop)
            hit=row.low<=stop if p['side']==1 else row.high>=stop
            if hit:
                px=min(float(row.open),stop) if p['side']==1 else max(float(row.open),stop)
                reason='最大虧損上限' if stop==cap_stop and cap_stop!=p['stop_price'] else '策略停損先觸發'
                close(sid,p,row,1,reason+'（跳空以較差開盤價）',px)
                continue
            signal=exit_signal(usable[sid],idx,p,settings)
            if signal['action']!='hold':
                restoring=signal['action']=='restore'
                pending.append({'type':'restore' if restoring else 'exit','stock_id':sid,'fraction':signal['fraction'],'reason':signal['reason']})
                if not restoring:p['scaled_fraction']=signal.get('target_fraction',p['scaled_fraction'])
        total=cash
        for sid,p in positions.items():
            idx=maps[sid].get(date)
            if idx is not None: p['last_price']=float(usable[sid].iloc[idx].close)
            total+=p['entry_price']*p['qty']+p['side']*(p.get('last_price',p['entry_price'])-p['entry_price'])*p['qty']
        equity.append({'date':date,'equity':total,'cash':cash,'positions':len(positions)})
        for sid,df in usable.items():
            idx=maps[sid].get(date)
            if idx is None or idx<60 or sid in positions: continue
            row=df.iloc[idx]
            snapshot=(restrictions or {}).get((sid,date))
            if snapshot and (settings['stock_pool']['exclude_full_delivery'] and snapshot.get('full_delivery') or settings['stock_pool']['exclude_disposition'] and snapshot.get('disposition')):continue
            vf=settings['stock_pool']['volume_filter']; n=vf['lookback_trading_days']
            if idx+1<n or df.iloc[idx-n+1:idx+1].volume.mean()/1000<vf['minimum_lots']: continue
            if market is not None and len(market):
                expected_dates=set(market[market.date<=date].date.tail(n))
                if not expected_dates.issubset(set(df.iloc[:idx+1].date)):continue
            if row.raw_close<settings.get('scanner',{}).get('minimum_price',5): continue
            # Optional market gate applies using only same-date completed index bars.
            if params.get('market_filter',True):
                regime=market_state(market[market.date<=date]) if market is not None else {'direction':'unknown'}
                expected='bull' if direction=='long' else 'bear'
                if regime['direction']!=expected: continue
            needs_mirror=any(x.startswith('S-') and not x.startswith(('S-ENTRY','S-HW')) for x in selected)
            signal=next((x for x in detect(df,idx,settings.get('rule_params'),needs_mirror) if x['id'] in selected and x['direction']==direction),None)
            if signal: pending.append({'type':'entry','stock_id':sid,'direction':direction,'rule':signal['id'],'signal_date':date})
    values=pd.Series([x['equity'] for x in equity])
    peak=values.cummax().clip(lower=capital)
    net=sum(x['net_pnl'] for x in trades); wins=[x for x in trades if x['net_pnl']>0]; losses=[x for x in trades if x['net_pnl']<=0]
    years=max((pd.Timestamp(dates[-1])-pd.Timestamp(dates[0])).days/365.25,1/365.25)
    win_rate=len(wins)/len(trades) if trades else 0
    avg_win=sum(x['return'] for x in wins)/len(wins) if wins else 0
    avg_loss=abs(sum(x['return'] for x in losses)/len(losses)) if losses else 0
    summary={'initial_capital':capital,'final_equity':float(values.iloc[-1]),'total_return':float(values.iloc[-1]/capital-1),'annualized_return':float((values.iloc[-1]/capital)**(1/years)-1) if values.iloc[-1]>0 else -1,'max_drawdown':float((values/peak-1).min()),'trades':len(trades),'win_rate':win_rate,'average_win':avg_win,'average_loss':avg_loss,'profit_factor':sum(x['net_pnl'] for x in wins)/abs(sum(x['net_pnl'] for x in losses)) if losses and sum(x['net_pnl'] for x in losses)!=0 else None,'realized_pnl':net,'open_positions':len(positions),'average_holding_days':sum(x['holding_days'] for x in trades)/len(trades) if trades else 0}
    benchmarks=[{**x,'actual_trades_per_year':len(trades)/years,'actual_win_rate':win_rate,'actual_average_win':avg_win,'actual_average_loss':avg_loss,'actual_annual_return':summary['annualized_return']} for x in FORMULAS]
    return clean({'summary':summary,'equity':equity,'trades':trades,'positions':positions,'warnings':warnings,'benchmarks':benchmarks,'params':{**params,'settings_snapshot':settings,'commission_rate':fee,'minimum_commission':minimum},'execution':'收盤訊號次交易日開盤成交；隔日持倉觸及停損價執行，跳空採較差價並計滑價。未平倉部位按最後收盤估值。書中方程式是簡化報酬加總，非資金曲線保證。'})
