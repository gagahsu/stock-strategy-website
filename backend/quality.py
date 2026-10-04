from .db import Session, Bar, Stock, get, put, now

def audit():
    report=[]
    with Session.begin() as s:
        calendar={x.date for x in s.query(Bar).filter_by(stock_id='TAIEX')}
        ids=[x[0] for x in s.query(Bar.stock_id).group_by(Bar.stock_id)]
        for sid in ids:
            rows=s.query(Bar).filter_by(stock_id=sid).order_by(Bar.date).all()
            dates={x.date for x in rows}
            expected={d for d in calendar if rows[0].date<=d<=rows[-1].date}
            missing=sorted(expected-dates)
            suspicious=[]
            for prev,row in zip(rows,rows[1:]):
                change=row.close*row.factor/(prev.close*prev.factor)-1
                if abs(change)>.25: suspicious.append({'date':row.date,'change':change})
            # Missing bars may be suspension, never silently fill with zero.
            value={'id':sid,'rows':len(rows),'first':rows[0].date,'last':rows[-1].date,'missing_trading_dates':missing,'unverified_bars':sum(not x.adjustment_verified for x in rows),'suspicious_moves':suspicious,'warning':'缺交易日可能為停牌或來源缺漏，須核對公告。' if missing or suspicious else None}
            put(s,'quality',sid,value)
            report.append(value)
        put(s,'quality_summary','latest',{'updated_at':now(),'rows':report})
    return report
