"""Consistent SQLite backup includes active WAL, never delete source data."""
import sqlite3
from datetime import datetime
from backend.db import ROOT, engine

def run():
    if engine.dialect.name!='sqlite':raise ValueError('PostgreSQL請使用資料庫平台備份或pg_dump')
    destination=ROOT/'data'/'backups'
    destination.mkdir(exist_ok=True)
    target=destination/(datetime.now().strftime('strategy-%Y%m%d-%H%M%S-%f')+'.db')
    with sqlite3.connect(engine.url.database) as source,sqlite3.connect(target) as backup:source.backup(backup)
    with sqlite3.connect(target) as connection:
        if connection.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('備份完整性失敗')
    return target

if __name__=='__main__':print(run())
