"""Shared stock universe for scanning and bulk backfill."""
import json
from datetime import date
from html.parser import HTMLParser
import httpx
from .db import Stock, Session, get, put, now


class IsinRows(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=''
    def handle_data(self,text):
        if self.cell is not None:self.cell+=text
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:self.row.append(self.cell.strip());self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def equities_from_isin(rows,market,asof=None):
    asof=asof or date.today().isoformat()
    result=[]
    for row in rows:
        if len(row)<6:continue
        parts=row[0].split(maxsplit=1)
        if len(parts)!=2:continue
        sid,name=parts
        if len(sid)!=4 or not sid.isdigit() or sid.startswith('00') or not row[5].startswith(('ES','ED')):continue
        if not row[3].startswith('上市' if market=='twse' else '上櫃'):continue
        listed=row[2].replace('/','-')
        try:date.fromisoformat(listed)
        except ValueError:continue
        if listed>asof:continue
        result.append({'id':sid,'name':name,'market':market,'industry':row[4],'listed_date':listed,'isin':row[1]})
    return result


def save_current_universe(markets):
    # Never turn a partial/blocked response into an empty current universe.
    if set(markets)!= {'twse','tpex'} or any(len(rows)<100 for rows in markets.values()):raise ValueError('官方上市櫃名單不完整，保留原名單')
    with Session.begin() as s:
        for market,rows in markets.items():
            for row in rows:
                stock=s.get(Stock,row['id'])
                meta=json.loads(stock.payload or '{}') if stock else {}
                meta.update(is_etf=False,is_ky='KY' in row['name'],listed_date=row['listed_date'],isin=row['isin'])
                s.merge(Stock(id=row['id'],name=row['name'],market=market,industry=row['industry'],payload=json.dumps(meta,ensure_ascii=False)))
            put(s,'current_universe',market,{'rows':rows,'source':'TWSE ISIN','updated_at':now()})
    return {market:len(rows) for market,rows in markets.items()}


def refresh_current_universe():
    markets={}
    for market,mode in [('twse',2),('tpex',4)]:
        response=httpx.get('https://isin.twse.com.tw/isin/C_public.jsp',params={'strMode':mode},timeout=45)
        response.raise_for_status()
        parser=IsinRows();parser.feed(response.content.decode('cp950',errors='replace'))
        markets[market]=equities_from_isin(parser.rows,market)
    return save_current_universe(markets)


def is_etf(stock):
    return stock.id.startswith('00') or bool(json.loads(stock.payload or '{}').get('is_etf'))


def pool_stocks(s,cfg,include_index=False):
    rows=[]
    snapshots=[get(s,'current_universe',market) for market in ('twse','tpex')]
    current={row['id'] for snap in snapshots if snap for row in snap['rows']} if all(snapshots) else None
    for stock in s.query(Stock):
        if stock.market=='index':
            if include_index:rows.append(stock)
            continue
        if stock.market not in ('twse','tpex'):continue
        if cfg['stock_pool'].get('exclude_etf',False) and is_etf(stock):continue
        if current is not None and not is_etf(stock) and stock.id not in current:continue
        rows.append(stock)
    return rows
