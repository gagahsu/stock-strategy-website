"""Free reference-price factor construction; invalid/missing actions fail closed."""
from .db import Session, Bar, put, now
from .ingest import fin

def action_ratios(dividends,reductions):
    ratios={}
    for x in dividends:
        before=float(x['before_price']); after=float(x['reference_price'])
        if before<=0 or after<=0: raise ValueError('除權息參考價不合法')
        ratios[x['date']]=after/before
    for x in reductions:
        before=x.get('ClosingPriceonTheLastTradingDay',x.get('before_close'))
        after=x.get('PostReductionReferencePrice',x.get('after_ref_close'))
        if before is None or after is None: raise ValueError('減資資料欄位無法解析，保持未驗證')
        before=float(str(before).replace(',',''));after=float(str(after).replace(',',''))
        if min(before,after)<=0: raise ValueError('減資參考價不合法')
        ratios[x['date']]=after/before
    return ratios

def rebuild(sid,start,end):
    if sid=='TAIEX':
        dividends=[]; reductions=[]
    else:
        dividends=fin('TaiwanStockDividendResult',sid,start,end)
        reductions=fin('TaiwanStockCapitalReductionReferencePrice',sid,start,end)
    ratios=action_ratios(dividends,reductions)
    with Session.begin() as s:
        rows=s.query(Bar).filter_by(stock_id=sid).filter(Bar.date<=end).order_by(Bar.date.desc()).all()
        factor=1.;events=sorted(ratios.items(),reverse=True);pointer=0
        for row in rows:
            while pointer<len(events) and events[pointer][0]>row.date:
                factor*=events[pointer][1];pointer+=1
            row.factor=factor;row.adjustment_verified=1
        put(s,'corporate_actions',sid,{'rows':dividends,'reductions':reductions,'method':'reference_price_backward_factor','updated_at':now()},end)
        put(s,'adjustment_audit',sid,{'start':start,'end':end,'events':ratios,'rows':len(rows),'method':'free_reference_price','limitations':'無法保證來源涵蓋分割、合併等所有特殊事件；巨幅跳價需另核對。'})
    return {'stock_id':sid,'events':len(ratios),'rows':len(rows)}
