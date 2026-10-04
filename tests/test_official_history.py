import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import official_history as official
from backend.db import Base, Bar, get


def response(market, rows):
    names = list(official.FIELDS[market].values())
    # Real sources also contain warrants/ETFs. They must not enter the equity pool.
    padding = [[str(900000 + n), '100', '102', '99', '101', '1000'] for n in range(100)]
    return {'stat': 'OK', 'date': '20261002', 'tables': [{'fields': names, 'data': rows + padding}]}


@pytest.fixture
def database(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path / 'official.db'))
    Base.metadata.create_all(engine)
    session = sessionmaker(engine)
    monkeypatch.setattr(official, 'Session', session)
    return session


def test_both_sources_preserve_share_volume_and_requested_date():
    for market in ('twse', 'tpex'):
        rows = official.parse_day(market, '2026-10-02', response(market, [['2330', '1,100', '1,120', '1,090', '1,110', '1,234,567']]))
        assert rows[0]['volume'] == '1,234,567'
        assert rows[0]['close'] == '1,110'
        assert rows[0]['date'] == '2026-10-02'
    with pytest.raises(ValueError):
        official.parse_day('twse', '2026-10-01', response('twse', []))


def test_supplement_excludes_etf_preserves_verified_prices_and_allows_board_transfer(database, monkeypatch):
    with database.begin() as s:
        s.add(Bar(stock_id='2330', date='2026-10-02', open=100, high=102, low=99, close=101, volume=12345, factor=.75, adjustment_verified=1))
    payload = response('tpex', [['2330', '200', '202', '199', '201', '999'], ['7750', '10', '12', '9', '11', '1,234,567'], ['0050', '100', '102', '99', '101', '1000']])
    monkeypatch.setattr(official, 'fetch', lambda *_: payload)
    result = official.ingest_day('tpex', '2026-10-02', {'2330', '7750'}, 'pool1')
    assert result['inserted'] == 1 and result['preserved'] == 1
    with database() as s:
        old = s.get(Bar, ('2330', '2026-10-02'))
        assert (old.close, old.volume, old.factor, old.adjustment_verified) == (101, 12345, .75, 1)
        new = s.get(Bar, ('7750', '2026-10-02'))
        assert new.volume == 1234567 and new.adjustment_verified == 0
        assert s.get(Bar, ('0050', '2026-10-02')) is None
        assert get(s, 'ingest', '7750') is None
    # Official daily checkpoints do not impersonate completed FinMind history.
    def forbidden(*_):
        raise AssertionError('completed provider day should not be fetched twice')
    monkeypatch.setattr(official, 'fetch', forbidden)
    assert official.ingest_day('tpex', '2026-10-02', {'2330', '7750'}, 'pool1')['cached']


def test_incomplete_response_does_not_create_completed_checkpoint(database, monkeypatch):
    monkeypatch.setattr(official, 'fetch', lambda *_: {'stat': 'OK', 'date': '20261002', 'tables': []})
    with pytest.raises(ValueError):
        official.ingest_day('twse', '2026-10-02', {'2330'}, 'pool')
    with database() as s:
        assert s.query(Bar).count() == 0
        assert get(s, 'official_history_day', 'twse', '2026-10-02') is None


def test_concurrent_insert_wins_without_duplicate_or_factor_overwrite(database, monkeypatch):
    monkeypatch.setattr(official, 'fetch', lambda *_: response('twse', [['2330', '200', '202', '199', '201', '999']]))
    original = official.bar_values
    def concurrent_writer(sid, row):
        # Insert after the collector's existing-key query, reproducing the live race.
        with database.begin() as s:
            s.add(Bar(stock_id=sid, date=row['date'], open=100, high=102, low=99,
                      close=101, volume=12345, factor=.75, adjustment_verified=1))
        return original(sid, row)
    monkeypatch.setattr(official, 'bar_values', concurrent_writer)
    result = official.ingest_day('twse', '2026-10-02', {'2330'}, 'pool')
    assert result['inserted'] == 0 and result['preserved'] == 1
    with database() as s:
        row = s.get(Bar, ('2330', '2026-10-02'))
        assert (row.close, row.factor, row.adjustment_verified) == (101, .75, 1)


def test_bad_prices_are_quarantined_without_fabricating_nontrading_bars(database, monkeypatch):
    monkeypatch.setattr(official, 'fetch', lambda *_: response('twse', [
        ['2330', '100', '98', '99', '101', '1000'],
        ['7750', '--', '--', '--', '--', '0'],
    ]))
    result = official.ingest_day('twse', '2026-10-02', {'2330', '7750'}, 'pool')
    assert result['rejected'] == 1 and result['no_valid_price'] == 1 and result['inserted'] == 0
    with database() as s:
        assert s.query(Bar).count() == 0
        assert get(s, 'official_rejected_bar', '2330', '2026-10-02')['row']['high'] == '98'
