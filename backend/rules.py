"""Book-backed rules. Geometric/subjective proxies are explicitly labelled."""
import math
from .features import clean

ENTRY_NAMES=['打底完成','突破盤整','拉回','回後買上漲','K線橫盤突破','ABC 突破','型態確認','突破大量黑K']
BULL_NAMES=['低檔大量長紅K','破切反彈過高大漲','大量雙腳反轉','缺口之上續漲','碎步上漲攻擊','底部洗盤上攻大漲','空轉多過空高','紅黑紅上漲','突破大量黑K','低檔連2日大量被突破','低檔大量長下影線','月線上盤整突破','雙盤底大量突破','雙弧底大量突破','均線糾結紅K突破','突破ABC上漲','島型反轉','突破上升軌道線']
BEAR_NAMES=['高檔大量長黑一日反轉','大量長黑破切反轉','大量雙頭反轉','遇壓爆量黑K','連2日大量被黑K跌破','高檔大量長上影反轉','高檔跳空黑K反轉','連3日長上影','反彈大量紅K跌破','創高爆量黑K','黑紅黑夾擊','缺口之下續空','多轉空破多底','跌破ABC','跌破下降軌道']
M_NAMES=['多頭大量不漲','空頭大量不跌','利多不漲（近似）','利空不跌（近似）','該回不回過高','該彈不彈破低','多轉空','空轉多','晨星／夜星','一星二陽／陰突破','關前放量不漲','高低檔久盤突破']
BOTTOM_NAMES=['底部狹幅盤整','月線上橫盤','雙盤底','緩漲後攻擊','突破緩漲軌道']
HW_NAMES={'L':['多頭確認突破MA5','回檔不破前低突破MA5','突破盤整上頸線','突破均線糾結','回檔1～2日突破黑K高點','假跌破後突破上頸線'],'S':['空頭確認跌破MA5','反彈不過前高跌破MA5','跌破盤整下頸線','跌破均線糾結','反彈1～2日跌破紅K低點','假突破後跌破下頸線']}

def catalogue():
    items=[]
    def add(id,name,chapter,direction='long',proxy=False,category='entry'):
        items.append({'id':id,'name':name,'chapter':chapter,'direction':direction,'category':category,'approximate':proxy,'description':name+('：使用可調數值條件近似，需核對原圖。' if proxy else '：依完成日K與書中條件判斷。')})
    for i,name in enumerate(ENTRY_NAMES,1):
        add(f'L-ENTRY-{i}',name,'11-1',proxy=i in (1,6,7))
        add(f'S-ENTRY-{i}',name+'（空方鏡像）','11-1','short',True)
    for direction in ('L','S'):
        for i in range(1,7): add(f'{direction}-HW-{i}',HW_NAMES[direction][i-1],'12-1','long' if direction=='L' else 'short',i in (1,4,6))
    for prefix,names,direction in [('P-BULL',BULL_NAMES,'long'),('P-BEAR',BEAR_NAMES,'short')]:
        for i,name in enumerate(names,1): add(f'{prefix}-{i}',name,'12-4',direction,True,'pattern')
    for i,name in enumerate(M_NAMES,1): add(f'M-{i}',name,'11-3','warning',True,'warning')
    for i,name in enumerate(BOTTOM_NAMES,1): add(f'L-BOTTOM-{i}',name,'10-4',proxy=True)
    for id,name,chapter,proxy in [('L-2ND-WAVE','強勢飆股第2波','10-3',True),('L-RIGHT-FOOT','黃金右腳','2-2',False),('L-GAP-BREAKOUT','向上突破缺口','9-2',True),('L-3D2G','3日2缺口','9-5',False),('L-MA-TANGLE-BO','均線糾結突破','4-2',False),('L-BB-SQUEEZE-BO','布林收斂突破','8-5',True)]: add(id,name,chapter,proxy=proxy)
    for i in range(1,4):
        add(f'L-GRANVILLE-{i}',f'葛蘭碧買 {i}','4-2',proxy=True)
    add('L-MA5-CROSS','MA5回後上漲（MA20範圍）','4-3')
    add('L-MA10-CROSS','MA10回後上漲（MA20範圍）','4-3')
    add('W-EXHAUST-UP','高檔跳空後3日內爆量回補','9-2','warning',True,'warning')
    add('W-EXHAUST-DOWN','低檔跳空後3日內爆量回補','9-3','warning',True,'warning')
    for item in list(items):
        if item['id'].startswith('L-') and not item['id'].startswith(('L-ENTRY','L-HW')):
            items.append({**item,'id':'S-'+item['id'][2:],'direction':'short','name':item['name']+'（空方鏡像）','approximate':True})
    return items

CATALOGUE=catalogue()
BY_ID={x['id']:x for x in CATALOGUE}

def market_state(f):
    if len(f)<60:
        return {'state':'資料不足','direction':'unknown','allocation':0,'reason':'至少需要60根日K'}
    r=f.iloc[-1]
    if r.close < r.ma120 and not r.ma120_up:
        label,direction,allocation='長期空頭','bear',.2
    elif r.bear4:
        label,direction,allocation='中期空頭','bear',.3
    elif r.close<r.ma20 and not r.ma20_up:
        label,direction,allocation='月線下空頭','bear',.4
    elif r.rise_from_bottom>=1:
        label,direction,allocation='末升段警示','bull',.5
    elif r.bull4:
        label,direction,allocation='4線多排','bull',.7
    elif r.close>r.ma20 and r.ma20_up:
        label,direction,allocation='空轉多／初期多頭','bull',.4
    else:
        label,direction,allocation='盤整觀察','range',.3
    return clean({'date':r.date,'state':label,'direction':direction,'allocation':allocation,'reason':'依月線／季線／半年線及均線排列；區間6~8成採中值7成，可調上限。'})

def detect(f,i=None,params=None,mirror=True):
    if len(f)<21: return []
    i=len(f)-1 if i is None else i
    if i<20: return []
    x,p,q=f.iloc[i],f.iloc[i-1],f.iloc[i-2]
    params=params or {}
    tail=f.iloc[max(0,i-60):i]  # strictly excludes signal day
    body=params.get('body_threshold',.02)
    red=x.body>body; black=x.body<-body
    attack=x.volume_ratio>=params.get('attack_volume_ratio',1.3); explosive=x.volume_ratio>=params.get('explosive_volume_ratio',2)
    high=x.close>=x.high60*.95; low=x.close<=x.low60*1.3 or x.close<=x.high60*.85
    bo=x.close>x.range_high; bd=x.close<x.range_low
    narrow=x.range_width<=params.get('range_width',.10)
    up=x.close>x.ma20 and x.ma20_up
    down=x.close<x.ma20 and not x.ma20_up
    cross_up=x.close>x.ma5 and p.close<=p.ma5
    cross_down=x.close<x.ma5 and p.close>=p.ma5
    over_y=x.close>p.high; below_y=x.close<p.low
    hh=x.higher_high5; hl=x.higher_low5; lh=x.lower_high5; ll=x.lower_low5
    buy=red and attack and up
    sell=black and attack and down
    channel_up=x.close>tail.high.max() if len(tail)==60 else False
    channel_down=x.close<tail.low.min() if len(tail)==60 else False
    recent_black=f.iloc[max(0,i-3):i]; recent_black=recent_black[(recent_black.body<-.02)&(recent_black.volume_ratio>=1.3)]
    recent_red=f.iloc[max(0,i-3):i]; recent_red=recent_red[(recent_red.body>.02)&(recent_red.volume_ratio>=1.3)]
    black_bo=len(recent_black)>0 and x.close>recent_black.high.max()
    red_bd=len(recent_red)>0 and x.close<recent_red.low.min()
    above_gap=False;below_gap=False;island=False
    recent_rows={j:r for j,r in enumerate(f.iloc[max(0,i-21):i+1].itertuples(index=False),max(0,i-21))}
    for j in range(max(1,i-20),i):
        gap_bar,previous=recent_rows[j],recent_rows[j-1]
        if gap_bar.gap_up and f.iloc[j:i+1].close.min()>previous.high:above_gap=True
        if gap_bar.gap_down and f.iloc[j:i+1].close.max()<previous.low:below_gap=True
        if gap_bar.gap_down and x.gap_up and f.iloc[j:i].high.max()<min(previous.low,x.low):island=True
    recent_shadow=f.iloc[max(0,i-5):i]
    recent_shadow=recent_shadow[(recent_shadow.lower_shadow>.03)&(recent_shadow.volume_ratio>=1.3)]
    shadow_confirmation=len(recent_shadow)>0 and x.close>recent_shadow.high.max() and red and attack
    break_support=x.close<x.support_line5 and p.close>=p.support_line5
    break_resistance=x.close>x.resistance_line5 and p.close<=p.resistance_line5
    double=hl and x.close>x.pivot_high5
    double_top=lh and x.close<x.pivot_low5
    abc=lh and hl and x.close>p.high and up
    abc_s=lh and hl and x.close<p.low and down
    entries=[buy and bo and p.trend!='bull',buy and bo,buy and cross_up and hl,buy and cross_up and over_y,buy and x.close>f.iloc[i-3:i].high.max(),buy and abc,buy and double,buy and black_bo]
    sentries=[sell and bd and p.trend!='bear',sell and bd,sell and cross_down and lh,sell and cross_down and below_y,sell and x.close<f.iloc[i-3:i].low.min(),sell and abc_s,sell and double_top,sell and red_bd]
    hw=[cross_up and x.trend=='bull',cross_up and hl,bo,p.tangle and bo,p.body<0 and over_y,p.low<p.range_low and bo]
    shw=[cross_down and x.trend=='bear',cross_down and lh,bd,p.tangle and bd,p.body>0 and below_y,p.high>p.range_high and bd]
    bottom=[len(tail)>=40 and tail.high.max()/tail.low.min()-1<.15 and bo,up and narrow and bo,double,x.ma20_up and x.change>.03,channel_up]
    bulls=[low and red and explosive,over_y and hh and attack,double and buy,x.gap_up and buy,x.ma20_up and buy,p.low<p.range_low and buy and bo,x.trend=='bull' and p.trend!='bull' and over_y,q.body>0 and p.body<0 and red and over_y,black_bo and buy,q.volume_ratio>=2 and p.volume_ratio>=2 and x.close>max(q.high,p.high),low and x.lower_shadow>.03 and attack,up and bo and narrow,double and buy,double and buy,p.tangle and buy and bo,abc and buy,x.gap_up and bool(tail.gap_down.tail(10).any()),channel_up and buy]
    bears=[high and black and explosive,black and x.close<x.ma20 and attack,double_top and sell,high and black and explosive,q.volume_ratio>=2 and p.volume_ratio>=2 and x.close<min(q.low,p.low),high and x.upper_shadow>.03 and explosive,high and x.gap_up and black,bool((f.iloc[i-2:i+1].upper_shadow>.02).all()) and high,red_bd and sell,x.high>x.high60 and black and explosive,q.body<0 and p.body>0 and black and below_y,x.gap_down and sell,x.trend=='bear' and p.trend!='bear' and below_y,abc_s and sell,channel_down and sell]
    # The drawings show confirmation after the setup, rather than the setup alone.
    bulls[1]=red and attack and (break_resistance or over_y and hh)
    bulls[3]=above_gap and buy
    bulls[4]=buy and bool((f.iloc[max(0,i-5):i].body.abs()<=body).all()) and p.close>p.ma20
    bulls[10]=shadow_confirmation
    bulls[16]=island and red
    bulls[17]=channel_up and buy and x.support_line5>p.support_line5
    bears[0]=high and black and explosive or p.close>=p.high60*.95 and p.body<-.035 and p.volume_ratio>=2 and below_y
    bears[1]=black and attack and break_support
    bears[9]=black and explosive and x.high>tail.high.max()
    bears[11]=below_gap and sell and bd
    bears[14]=black and attack and break_support and x.support_line5<p.support_line5
    m=[up and explosive and (x.change<=0 or x.upper_shadow>.03),down and explosive and (x.change>=0 or x.lower_shadow>.03),up and explosive and lh,down and explosive and hl,up and p.volume_ratio>=2 and over_y,down and p.volume_ratio>=2 and below_y,x.trend=='bear' and p.trend!='bear',x.trend=='bull' and p.trend!='bull',q.body<-.02 and abs(p.body)<.01 and red or q.body>.02 and abs(p.body)<.01 and black,q.body>.02 and p.body>0 and black and x.close<q.low or q.body<-.02 and p.body<0 and red and x.close>q.high,high and explosive and not bo,narrow and (bo or bd)]
    fired=[]
    def add(id,condition):
        if bool(condition):
            meta=BY_ID[id]
            fired.append({**meta,'date':x.date,'reason':f'{meta["name"]}；實體 {x.body:.1%}、量比 {x.volume_ratio:.2f}、趨勢 {x.trend}', 'stop_price':clean(float(x.low if meta['direction']=='long' else x.high))})
    for k,condition in enumerate(entries,1): add(f'L-ENTRY-{k}',condition)
    for k,condition in enumerate(sentries,1): add(f'S-ENTRY-{k}',condition)
    for k,condition in enumerate(hw,1): add(f'L-HW-{k}',buy and x.bull4 and condition)
    for k,condition in enumerate(shw,1): add(f'S-HW-{k}',sell and x.bear4 and condition)
    for prefix,values in [('P-BULL',bulls),('P-BEAR',bears),('M',m),('L-BOTTOM',bottom)]:
        for k,condition in enumerate(values,1): add(f'{prefix}-{k}',condition)
    add('L-2ND-WAVE',buy and narrow and bo and .15<=x.rise_from_bottom<1)
    add('L-RIGHT-FOOT',hl and x.ma10>x.ma20)
    add('L-GAP-BREAKOUT',buy and x.gap_up and bo)
    add('L-3D2G',bool(f.iloc[i-2:i+1].gap_up.sum()>=2 and (f.iloc[i-2:i+1].body>0).all()))
    add('L-MA-TANGLE-BO',buy and p.tangle and bo)
    add('L-BB-SQUEEZE-BO',buy and (p.bb_upper-p.bb_lower)/p.ma20<.1 and x.close>x.bb_upper)
    add('L-GRANVILLE-1',buy and x.ma20_up and p.close<=p.ma20)
    add('L-GRANVILLE-2',buy and x.ma20_up and p.close<p.ma20 and x.close>x.ma20)
    add('L-GRANVILLE-3',buy and x.ma20_up and p.low>=p.ma20 and over_y)
    add('L-MA5-CROSS',x.body>0 and cross_up and x.close>x.ma20)
    add('L-MA10-CROSS',x.body>0 and x.close>x.ma10 and p.close<=p.ma10 and x.close>x.ma20)
    for j in range(max(1,i-3),i):
        g,prior=recent_rows[j],recent_rows[j-1]
        add('W-EXHAUST-UP',g.gap_up and g.close>=g.high60*.95 and f.iloc[max(0,j-1):j+2].volume_ratio.max()>=2 and x.close<=prior.high and x.body<0)
        add('W-EXHAUST-DOWN',g.gap_down and g.close<=g.low60*1.05 and f.iloc[max(0,j-1):j+2].volume_ratio.max()>=2 and x.close>=prior.low and x.body>0)
    if mirror:
        # Reciprocal OHLC preserves positive prices and reverses price direction.
        from .features import features
        inverse=f.__dict__.get('_inverse_features')
        if inverse is None:
            raw=f[['date','open','high','low','close','volume']].copy()
            raw['open'],raw['close']=1/raw.open,1/raw.close
            old_high,old_low=raw.high.copy(),raw.low.copy()
            raw['high'],raw['low']=1/old_low,1/old_high
            raw['factor']=1.
            inverse=features(raw,params)
            f.__dict__['_inverse_features']=inverse
        for item in detect(inverse,i=i,params=params,mirror=False):
            sid='S-'+item['id'][2:]
            if item['id'].startswith('L-') and sid in BY_ID and not sid.startswith(('S-ENTRY','S-HW')):
                fired.append({**BY_ID[sid],'date':x.date,'reason':BY_ID[sid]['name']+'；以價格倒數鏡像近似','stop_price':clean(float(x.high))})
    return list({item['id']:item for item in fired}.values())


def initial_stop(signal_bar, entry_price, direction, method, settings):
    """Freeze strategy level at entry; configurable loss cap is applied separately."""
    side=1 if direction=='long' else -1
    fixed=entry_price*(1-side*settings['risk'].get('strategy_stop_ratio',.05))
    names={'kline':'low' if side==1 else 'high','trend':'pivot_low5' if side==1 else 'pivot_high5','ma':'ma5','support':'range_high' if side==1 else 'range_low'}
    if method=='fixed':return fixed
    value=float(signal_bar[names[method]])
    # Invalid/unknown support cannot silently widen a strategy stop.
    return value if math.isfinite(value) and side*(entry_price-value)>0 else fixed

def checks(f,stock,settings,market=None,asof=None,direction=None):
    if f.empty: return []
    x=f.iloc[-1]; config=settings['stock_pool']; volume=config['volume_filter']
    n=volume['lookback_trading_days']; avg=f.volume.tail(n).mean()/1000 if len(f)>=n else None
    md=stock
    direction=direction or ('long' if x.trend!='bear' else 'short')
    restrictions_known=bool(md.get('restrictions_date')) and (not asof or md['restrictions_date']>=asof)
    rows=[]
    def add(name,passed,reason,hard=False): rows.append({'name':name,'passed':passed,'reason':reason,'hard':hard})
    add('日均量',avg is not None and avg>=volume['minimum_lots'],f'{n}日平均 {avg:,.0f} 張 / 門檻 {volume["minimum_lots"]:,.0f} 張' if avg is not None else '完整窗口資料不足',True)
    add('全額交割',not md.get('full_delivery') if restrictions_known else None,'排除全額交割；未知或過期時不納入可交易候選',config['exclude_full_delivery'])
    add('處置股',not md.get('disposition') if restrictions_known else None,'排除處置股；未知或過期時不納入可交易候選',config['exclude_disposition'])
    add('股價',x.raw_close>=settings.get('scanner',{}).get('minimum_price',5),'預設至少5元，可調',True)
    add('ETF',not md.get('is_etf') or not config['exclude_etf'],'依股票池設定',config['exclude_etf'])
    add('KY',not md.get('is_ky') or not config['exclude_ky'],'依股票池設定',config['exclude_ky'])
    add('趨勢',x.trend in ('bull','bear'),'頭頭高底底高／頭頭低底底低')
    add('位置',x.rise_from_bottom<1,'漲幅達1倍列末升警示')
    add('K線轉折',abs(x.body)>.02,'實體幅度大於2%')
    add('均線',bool(x.bull3 or x.bear3),'至少3線排列')
    add('成交量',x.volume_ratio>=1.3,'相對前5日均量至少1.3倍')
    add('指標',bool(x.k>x.d if direction=='long' else x.k<x.d),'KD多空配合')
    add('大盤濾網',market.get('direction')==('bull' if direction=='long' else 'bear') if market else None,'大盤月線方向配合',True)
    if direction=='short': add('券源／停券',md.get('can_short'), '須取得歷史券源與停券資訊；未確認僅作研究警示',True)
    side=1 if direction=='long' else -1
    eliminated_flow=md.get('institutional_selling' if side==1 else 'institutional_buying')
    elimination=[('沒走出底部／頭部',side*(x.close-x.ma20)>0),('支阻不過',not(side*(x.close-x.ma5)<0 and x.volume_ratio>=2)),('趨勢不明',x.trend!='range'),('沒有量能',x.volume_ratio>=.5),('波段幅度達1倍',x.rise_from_bottom<1 if side==1 else x.high60/x.close-1<1),('遇壓大量反向K',not(side*x.body<-.035 and x.volume_ratio>=2)),('背離加轉折轉弱',not((x.macd_divergence or x.kd_divergence) and (x.lower_high5 if side==1 else x.higher_low5))),('法人連續反向買賣',not eliminated_flow if eliminated_flow is not None else None),('爆量不漲／跌',not(x.volume_ratio>=2 and side*x.change<=0)),('看不懂的股票',None),('無技術面',bool(x.bull3 if side==1 else x.bear3))]
    for name,passed in elimination: add('淘汰法：'+name,clean(passed),'未知項需人工確認' if passed is None else '依數值條件判斷；空方採鏡像',passed is not None)
    return clean(rows)

def exit_signal(f,i,position,settings):
    x=f.iloc[i]; p=f.iloc[i-1] if i else x
    side=1 if position['direction']=='long' else -1
    entry=position['entry_price']; price=float(x.close)
    profit=side*(price/entry-1)
    stop=position.get('stop_price') or entry*(1-side*settings['risk'].get('strategy_stop_ratio',.05))
    cap=entry*(1-side*settings['risk']['max_loss_ratio'])
    strategy_first=side*(stop-cap)>=0
    if side*(price-(stop if strategy_first else cap))<=0:
        return {'action':'exit','fraction':1,'reason':'策略停損先觸發' if strategy_first else '達設定最大虧損上限','rule_id':'X-STRATEGY-STOP' if strategy_first else 'X-MAX-LOSS'}
    mode=position.get('exit_mode','swing')
    if mode in ('ma5','ma10') and side*(price-x[mode])<0:
        exception=mode=='ma5' and side*x.body<0 and abs(x.change)<.01 and x.volume_ratio<1 and (x.ma20_up if side==1 else not x.ma20_up) and side*(p.close-p.ma5)>=0
        if exception:return {'action':'hold','fraction':0,'reason':'量縮小幅破MA5，依SOP15觀察次日','rule_id':'X-MA5-WAIT'}
        return {'action':'exit','fraction':1,'reason':mode.upper()+'單一均線戰法','rule_id':'X-'+mode.upper()}
    lower=bool(x.lower_high5) if side==1 else bool(x.higher_low5)
    if lower and mode not in ('hot','long') and (i==0 or not bool(p.lower_high5 if side==1 else p.higher_low5)): return {'action':'exit','fraction':1,'reason':'新確認的趨勢轉弱','rule_id':'X-LOWER-HIGH'}
    if mode=='long' and x.trend==('bear' if side==1 else 'bull'):
        return {'action':'exit','fraction':1,'reason':'長線趨勢反轉確認','rule_id':'X-LONG-REVERSAL'}
    if mode=='kline' and side*(price-(p.low if side==1 else p.high))<0: return {'action':'exit','fraction':1,'reason':'跌破／突破前日K線','rule_id':'X-K-LINE'}
    if mode=='hot':
        last=f.iloc[max(0,i-2):i]
        level=last.low.min() if side==1 else last.high.max()
        if side*(price-level)<0 or side*(price-x.ma3)<0 or side*x.body<0 and x.volume_ratio>=2:
            return {'action':'exit','fraction':1,'reason':'飆股續抱條件失效','rule_id':'X-HOT-STOCK'}
    if mode=='scale':
        target=sum(side*(price-x[f'ma{n}'])<0 for n in (5,10,20)) / 3
        already=position.get('scaled_fraction',0)
        if target>already: return {'action':'reduce','fraction':(target-already)/(1-already),'reason':'三均線分批減碼','rule_id':'X-3MA-SCALE','target_fraction':target}
        if target<already: return {'action':'restore','fraction':already-target,'reason':'站回均線補回原部位','rule_id':'X-3MA-RESTORE','target_fraction':target}
        return {'action':'hold','fraction':0,'reason':'三均線部位不變','rule_id':None}
    if mode in ('swing','long'):
        if (profit>.20 or i>=3 and (side*f.iloc[i-3:i].body>.035).all()) and side*x.body<-.035 and x.volume_ratio>=1.3:
            full=side*(price-(p.low if side==1 else p.high))<0
            return {'action':'exit' if full else 'reduce','fraction':1 if full else .5,'reason':'急漲／急跌後大量反向K，依前日低／高點全出或減半','rule_id':'X-CLIMAX'}
        if side*x.body<-.035 and x.volume_ratio>=3 and (x.close>=x.high60*.95 if side==1 else x.close<=x.low60*1.05):
            return {'action':'exit','fraction':1,'reason':'高低檔異常天量一日反轉','rule_id':'X-ONE-DAY-REVERSAL'}
        if mode=='swing' and side*x.body<0 and side*(price-x.ma5)<0 and side*p.body<0 and abs(p.body)<.01 and p.volume_ratio<1:
            return {'action':'exit','fraction':1,'reason':'量縮小幅破MA5後次日續跌／漲','rule_id':'X-SWING-SOP-15'}
        weekly_pressure=position.get('weekly_pressure',x.get('weekly_pressure_up' if side==1 else 'weekly_pressure_down',False))
        if mode=='swing' and weekly_pressure and side*x.body<0 and side*(price-x.ma5)<0:
            return {'action':'exit','fraction':1,'reason':'週線接近支阻且日線反向跌破MA5','rule_id':'X-SWING-SOP-19'}
        if side*(price-(x.range_low if side==1 else x.range_high))<0 and x.range_width<.10:
            return {'action':'exit','fraction':1,'reason':'盤整跌破／突破','rule_id':'X-RANGE-BREAK'}
        if p.volume_ratio>=1.3 and side*p.body<-.035 and side*(x.open-p.close)<0 and side*(x.close-x.open)<0:
            return {'action':'exit','fraction':1,'reason':'大量反向K後次日開低／開高續反向','rule_id':'X-SWING-SOP-7'}
        if side*x.body<0 and abs(x.body)>.01 and x.volume_ratio>=1.3 and side*(price-(p.open+p.close)/2)<0 and side*(x.k-p.k)<0:
            return {'action':'reduce','fraction':.5,'reason':'遇壓反向K強覆蓋且KD轉弱','rule_id':'X-SWING-SOP-11'}
        if side==1 and x.ma60>x.close and not x.ma60_up and price<x.ma5:
            return {'action':'exit','fraction':1,'reason':'季線下彎遇壓跌破MA5','rule_id':'X-SWING-SOP-20'}
    ma=x.ma20 if mode=='long' else x.ma5
    if profit>.10 and side*(price-ma)<0: return {'action':'exit','fraction':1,'reason':'獲利逾10%跌破停利均線','rule_id':'X-LONG-MA20' if mode=='long' else 'X-MA5-AFTER-10'}
    if profit>.2 and side*x.body<-.035 and x.volume_ratio>=1.3:
        full=side*(price-(p.low if side==1 else p.high))<0
        return {'action':'exit' if full else 'reduce','fraction':1 if full else .5,'reason':'急漲／急跌後大量反向K','rule_id':'X-CLIMAX'}
    return {'action':'hold','fraction':0,'reason':'未觸發出場條件','rule_id':None}
