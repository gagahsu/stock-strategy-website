"""Daily 17-point checklist; intraday/news items remain explicit manual checks."""
from .features import clean

def daily_sop(f,market=None):
    if f.empty:return []
    x=f.iloc[-1]
    items=[
        ('波浪多空架構',x.trend!='range',x.trend),
        ('分時強弱與漲跌停時點',None,'日K資料不含盤中走法'),
        ('量價與籌碼配合',x.volume_ratio>=1.3,'籌碼另見個股資料'),
        ('週線與月線方向',None,'請切換週／月K核對支撐壓力'),
        ('日／週KD',x.k>x.d,'週KD另見週K特徵'),
        ('近3~5日K線型態',None,'圖表訊號與原圖核對'),
        ('主流／題材／轉機',None,'新聞與題材需人工確認'),
        ('均線排列與位置',bool(x.bull3 or x.bear3),'MA5/10/20'),
        ('盤整或發動',x.close>x.range_high or x.close<x.range_low,'近10日箱型突破'),
        ('獲利空間與風險',None,'依支阻、停損與資金計畫確認'),
        ('強弱勢股內的回檔與反彈',None,'依相對强度排名與個股趨勢核對'),
        ('明日最佳3~5檔',None,'從候選名單選定'),
        ('資金分配',market is not None and market.get('allocation',0)>0,'參照大盤建議水位'),
        ('擬定進出場策略',None,'進場前設定策略停損與出場模組'),
        ('類股啟動與輪動',None,'參照強弱類股排名'),
        ('主流類股轉弱',x.macd_divergence or x.kd_divergence,'個股背離為參考，類股另核對'),
        ('強勢股資料庫',None,'加入鎖股清單並每日檢視')]
    return clean([{'number':i+1,'name':name,'passed':passed,'reason':reason,'hard':False} for i,(name,passed,reason) in enumerate(items)])
