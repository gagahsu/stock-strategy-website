"""Book evaluation table. Unknown information remains unknown; all dates are as-of."""
from .features import features, aggregate, clean
from .availability import known_as_of


def assessment(raw, metadata, context, market=None, industry_rank=None):
    day=features(raw); week=features(aggregate(raw,'week')); month=features(aggregate(raw,'month'))
    if day.empty:return {'technical':[],'fundamental':[],'commandments':[]}
    x=day.iloc[-1]; w=week.iloc[-1]; asof=x.date
    rows=[]
    def add(name,value,reason=''):
        rows.append({'name':name,'value':clean(value),'reason':reason})
    for title,f in [('日',day),('週',week),('月',month)]:
        r=f.iloc[-1]
        add(title+'波型',r.trend,'以已確認MA5轉折高低判斷')
        add(title+'位置','末升警示' if r.rise_from_bottom>=1 else '月線上' if r.close>r.ma20 else '月線下')
        add(title+'K線',f'實體 {r.body:.2%}')
        add(title+'均線','4線多排' if r.bull4 else '4線空排' if r.bear4 else '3線多排' if r.bull3 else '3線空排' if r.bear3 else '雜亂')
        add(title+'量比',r.volume_ratio,'本期／前5期平均')
        add(title+'MACD',r.macd_hist,'柱值正負與延長縮短需合併判讀')
        add(title+'KD',f'K {r.k:.1f} / D {r.d:.1f}')
    supports=[float(v) for v in (x.pivot_low5,x.ma20,x.range_low) if v==v and v<x.close]
    resistances=[float(v) for v in (x.pivot_high5,x.high60,x.ma60) if v==v and v>x.close]
    support=max(supports) if supports else None; resistance=min(resistances) if resistances else None
    add('短線支撐',support,'最近已確認低點／月線／區間低')
    add('短線壓力',resistance,'最近已確認高點／60日高／季線')
    add('獲利風險比',(resistance-x.close)/(x.close-support) if support and resistance and x.close>support else None,'僅以目前支阻估算；不保證觸及')
    add('背離','警示' if x.price_divergence or x.macd_divergence or x.kd_divergence else '未出現數值近似背離','目前以固定期差比較，非完整柱群判讀')
    add('策略','短線守MA5／長線守MA20' if x.bull3 else '等待排列及突破确认')
    chips=context.get('chips_daily',[])
    chips=[r for r in chips if r.get('date','9999')<=asof]
    dates=day.date.tail(3).tolist()
    complete_chips=len(dates)==3 and set(dates).issubset({r['date'] for r in chips})
    nets=[sum(float(r.get('buy',0))-float(r.get('sell',0)) for r in chips if r['date']==d) for d in dates]
    add('法人最近3日淨買賣超',sum(nets) if complete_chips else None,'最近3個個股交易日；缺漏維持未知，不含未来日期')
    margin=[r for r in context.get('margin_daily',[]) if r.get('date','9999')<=asof]
    m=margin[-1] if margin else {}
    add('融資餘額',m.get('MarginPurchaseTodayBalance'))
    add('融券餘額',m.get('ShortSaleTodayBalance'))
    revenues=[r for r in context.get('fundamentals',[]) if known_as_of(r,'fundamentals',asof)]
    latest=revenues[-1] if revenues else None
    prior=next((r for r in reversed(revenues) if latest and r.get('revenue_year')==latest.get('revenue_year',0)-1 and r.get('revenue_month')==latest.get('revenue_month')),None)
    yoy=float(latest['revenue'])/float(prior['revenue'])-1 if latest and prior and prior.get('revenue') else None
    capital=metadata.get('paid_in_capital') if metadata.get('capital_date','9999')<=asof else None
    bases=[{'name':'熱門類股','passed':industry_rank is not None and industry_rank<=3 if industry_rank else None,'reason':'20日報酬前三類股；不代表新聞題材'},
           {'name':'股本50億以下','passed':capital<5_000_000_000 if capital is not None else None,'reason':f'{capital:,.0f}元' if capital is not None else '當期股本資料尚未取得'},
           {'name':'營收年增','passed':yoy>0 if yoy is not None else None,'reason':f'{yoy:.2%}（依來源公開／建立日）' if yoy is not None else '當時可取得的同期資料不足；缺公開日期不假設已公布'},
           {'name':'法人買超','passed':sum(nets)>0 if complete_chips else None,'reason':'最近3個個股交易日合計；缺漏維持未知'}]
    side=1 if x.trend!='bear' else -1
    bodies=day.body.tail(3)*side
    weekly_level=w.high60 if side==1 else w.low60
    pressure=bool(weekly_level==weekly_level and abs(x.close/weekly_level-1)<.05)
    pass_values=[side*(x.close-x.ma20)>0,not bool((bodies>0).all()),not bool((x.price_divergence or x.kd_divergence) and (x.k>80 if side==1 else x.k<20) and abs(x.bias20)>.15),not pressure,side*(x.close-x.ma20)>0,not bool(x.lower_low5 if side==1 else x.higher_high5),bool(x.close>x.range_high if side==1 else x.close<x.range_low),x.trend==('bull' if side==1 else 'bear'),not bool((bodies>.035).all() and x.volume_ratio>=2),side*x.body>0]
    names=['月線方向','不追第3根','背離／乖離風險','週線支阻距離','回檔／反彈後月線','前低／前高守住','退出盤整區','順勢非逆勢','不追連續急漲跌','進場K顏色配合']
    commands=[{'name':('做多' if side==1 else '做空')+'戒律 '+str(i+1)+'：'+name,'passed':bool(v),'reason':'日週已完成K數值判斷；距支阻5%為近似','hard':False} for i,(name,v) in enumerate(zip(names,pass_values))]
    return clean({'technical':rows,'fundamental':bases,'commandments':commands,'weekly_pressure':pressure,'institutional_selling':all(v<0 for v in nets) if complete_chips else None})
