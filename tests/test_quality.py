import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from backend import quality
from backend.db import Base, Bar, get


def test_quality_calculation_does_not_hold_writer_lock_and_preserves_report(tmp_path, monkeypatch):
    path = tmp_path / 'quality.db'
    engine = create_engine('sqlite:///' + str(path))
    Base.metadata.create_all(engine)
    isolated = sessionmaker(engine)
    monkeypatch.setattr(quality, 'Session', isolated)
    with isolated.begin() as s:
        for sid, dates in [('TAIEX', ['2026-10-01', '2026-10-02', '2026-10-05']),
                           ('AAA', ['2026-10-01', '2026-10-05']),
                           ('BBB', ['2026-10-01', '2026-10-02', '2026-10-05'])]:
            for day in dates:
                s.add(Bar(stock_id=sid, date=day, open=10, high=11, low=9,
                          close=10, volume=1000, factor=1, adjustment_verified=0))
    probes = []

    @event.listens_for(engine, 'before_cursor_execute')
    def inspect_writer_availability(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith('SELECT') and 'daily_bars' in statement and parameters == ('BBB',):
            # AAA has already been calculated. An early quality write would
            # hold the writer lock here, blocking the independent connection.
            with sqlite3.connect(path, timeout=0) as other:
                other.execute('BEGIN IMMEDIATE')
                other.rollback()
            probes.append(True)

    report = quality.audit()
    assert probes
    by_id = {row['id']: row for row in report}
    assert by_id['AAA']['missing_trading_dates'] == ['2026-10-02']
    assert by_id['BBB']['missing_trading_dates'] == []
    assert by_id['AAA']['unverified_bars'] == 2
    assert by_id['BBB']['rows'] == 3
    with isolated() as s:
        assert get(s, 'quality', 'AAA') == by_id['AAA']
        assert get(s, 'quality_summary', 'latest')['rows'] == report
