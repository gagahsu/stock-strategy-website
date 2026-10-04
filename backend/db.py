"""Local SQLite by default; PostgreSQL via DATABASE_URL. No hosted account required."""
import json
import os
from pathlib import Path
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, String, Float, Integer, Text, UniqueConstraint, Index
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env')
(ROOT / 'data').mkdir(exist_ok=True)
url = os.getenv('DATABASE_URL') or f"sqlite:///{(ROOT / 'data' / 'strategy.db').as_posix()}"
if url.startswith('postgres://'):
    url = url.replace('postgres://', 'postgresql+psycopg://', 1)
elif url.startswith('postgresql://'):
    url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
engine = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 60} if url.startswith('sqlite') else {}, pool_pre_ping=True)
if url.startswith('sqlite'):
    from sqlalchemy import event
    @event.listens_for(engine,'connect')
    def sqlite_options(connection,record):
        connection.execute('PRAGMA journal_mode=WAL')
        connection.execute('PRAGMA busy_timeout=60000')
Session = sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Stock(Base):
    __tablename__ = 'stocks'
    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    market = Column(String, nullable=False)
    industry = Column(String, default='其他')
    payload = Column(Text, default='{}')

class Bar(Base):
    __tablename__ = 'daily_bars'
    stock_id = Column(String, primary_key=True)
    date = Column(String, primary_key=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(Float, nullable=False)  # shares, never lots
    factor = Column(Float, default=1.0)
    adjustment_verified = Column(Integer, default=0)
    source = Column(String, default='FinMind')

class Record(Base):
    __tablename__ = 'records'
    kind = Column(String, primary_key=True)
    key = Column(String, primary_key=True)
    date = Column(String, primary_key=True, default='')
    payload = Column(Text, nullable=False)
    __table_args__ = (Index('ix_records_kind_date', 'kind', 'date'),)

def now():
    return datetime.now(timezone.utc).isoformat()

def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, default=str)

def put(s, kind, key, value, date=''):
    s.merge(Record(kind=kind, key=key, date=date, payload=encode(value)))

def get(s, kind, key, date='', default=None):
    r = s.get(Record, (kind, key, date))
    return json.loads(r.payload) if r else default

def records(s, kind):
    values=[{'key': r.key, 'date': r.date, **json.loads(r.payload)} for r in s.query(Record).filter_by(kind=kind).order_by(Record.date.desc()).all()]
    return sorted(values,key=lambda x:x.get('finished_at',x.get('created_at',x.get('updated_at',x['date']))),reverse=True)

def init():
    Base.metadata.create_all(engine)
    with Session.begin() as s:
        put(s, 'schema', 'version', {'version': 1})

def settings(s):
    defaults=json.loads((ROOT / 'config/defaults.json').read_text(encoding='utf-8'))
    def merge(base,override):
        for key,value in override.items():
            if isinstance(value,dict) and isinstance(base.get(key),dict):merge(base[key],value)
            else:base[key]=value
        return base
    return merge(defaults,get(s,'settings','active',default={}))

def bars(s, stock_id, end=None):
    import pandas as pd
    q = s.query(Bar).filter_by(stock_id=stock_id)
    if end:
        q = q.filter(Bar.date <= end)
    rows = q.order_by(Bar.date).all()
    return pd.DataFrame([{c: getattr(r, c) for c in ('date', 'open', 'high', 'low', 'close', 'volume', 'factor', 'adjustment_verified')} for r in rows])

init()
