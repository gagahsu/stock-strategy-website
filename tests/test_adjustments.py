import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import adjustments
from backend.db import Base, Bar, get


@pytest.mark.parametrize('value', [float('nan'), float('inf'), -float('inf')])
@pytest.mark.parametrize('field', ['before', 'after'])
@pytest.mark.parametrize('kind', ['dividend', 'reduction'])
def test_nonfinite_reference_prices_are_rejected(value, field, kind):
    prices = {'before': 100, 'after': 95, field: value}
    if kind == 'dividend':
        dividends = [{'date': '2026-06-01', 'before_price': prices['before'],
                      'reference_price': prices['after']}]
        reductions = []
    else:
        dividends = []
        reductions = [{'date': '2026-06-01', 'before_close': prices['before'],
                       'after_ref_close': prices['after']}]
    with pytest.raises(ValueError):
        adjustments.action_ratios(dividends, reductions)


@pytest.mark.parametrize('ratio', [1e200, 1e-200])
def test_invalid_cumulative_factor_rolls_back_entire_verification(tmp_path, monkeypatch, ratio):
    engine = create_engine('sqlite:///' + str(tmp_path / 'adjustments.db'))
    Base.metadata.create_all(engine)
    isolated = sessionmaker(engine)
    monkeypatch.setattr(adjustments, 'Session', isolated)
    events = [{'date': day, 'before_price': 1, 'reference_price': ratio}
              for day in ('2026-05-01', '2026-06-01')]
    monkeypatch.setattr(adjustments, 'fin', lambda dataset, *args:
                        events if dataset == 'TaiwanStockDividendResult' else [])
    with isolated.begin() as s:
        for day in ('2026-04-01', '2026-07-01'):
            s.add(Bar(stock_id='TEST', date=day, open=10, high=11, low=9,
                      close=10, volume=1000, factor=.75, adjustment_verified=0))
    with pytest.raises(ValueError, match='累積還原因子'):
        adjustments.rebuild('TEST', '2026-04-01', '2026-07-01')
    with isolated() as s:
        assert all((bar.factor, bar.adjustment_verified) == (.75, 0)
                   for bar in s.query(Bar).all())
        assert get(s, 'adjustment_audit', 'TEST') is None
        assert get(s, 'corporate_actions', 'TEST', '2026-07-01') is None
