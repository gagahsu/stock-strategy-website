"""Real book example, separately from executable next-open backtest accounting."""
import json
from pathlib import Path
import pandas as pd
import pytest
from backend.features import features, gaps


def test_book_3707_ma5_events_and_price_sum():
    fixture=json.loads(Path('tests/fixtures/book_ma5_3707.json').read_text(encoding='utf-8'))
    raw=pd.DataFrame(fixture['bars']);f=features(raw).set_index('date')
    entries=[];exits=[]
    for event in fixture['events']:
        x=f.loc[event['date']];idx=raw.index[raw.date==event['date']][0];p=f.iloc[idx-1]
        assert x.close==pytest.approx(event['close'])
        if event['action']=='buy':
            assert x.close>x.ma5
            if not entries:
                assert x.close>p.high and x.volume_ratio>1.3 and x.body>.035
            else:assert p.close<=p.ma5
            assert x.body>0
            entries.append(x.close)
        else:
            assert x.close<x.ma5
            if event['date']=='2019-09-25':
                # SOP15 permits a small, low-volume crossing to wait one more day.
                assert p.body<0 and abs(p.change)<.01 and p.volume_ratio<1 and p.ma20_up
            else:assert p.close>=p.ma5
            exits.append(x.close)
    # The book sums six price differences over first entry, rather than compounding.
    price_sum=sum(b-a for a,b in zip(entries,exits))
    # The book rounds Jul16's 0.45 to 0.4 and reports 7.6 / 45.6%.
    # Preserve exact arithmetic from verified quotes rather than matching a typo.
    assert price_sum==pytest.approx(7.65)
    assert round(price_sum/entries[0]*100,1)==45.9
    assert abs(price_sum/entries[0]-.456)<.004


def test_book_1305_gap_four_levels_and_progressive_breaks():
    fixture=json.loads(Path('tests/fixtures/book_gap_1305.json').read_text(encoding='utf-8'))
    f=features(pd.DataFrame(fixture['bars']))
    gap=next(x for x in gaps(f) if x['date']==fixture['gap_date'] and x['direction']=='up')
    for key,price in fixture['levels'].items():assert gap[key]==pytest.approx(price)
    indexed=f.set_index('date')
    for key,date in zip(('upper_high','upper','lower','lower_bottom'),fixture['break_dates']):
        assert indexed.loc[date].close<gap[key]
    assert indexed.loc['2012-10-04'].body<-.02 and indexed.loc['2012-10-04'].volume_ratio>1.3
    # Ordinary filling is known on Sep25; the later large black K upgrades it.
    before=gaps(f[f.date<='2012-09-24'])
    ordinary=gaps(f[f.date<='2012-09-25'])
    assert next(x for x in before if x['date']==fixture['gap_date'])['status']=='未補'
    assert next(x for x in ordinary if x['date']==fixture['gap_date'])['status']=='假封口'
    assert gap['status']=='真封口' and gap['filled_date']=='2012-10-04'
