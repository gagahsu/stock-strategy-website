"""Real book example, separately from executable next-open backtest accounting."""
import json
from pathlib import Path
import pandas as pd
import pytest
from backend.features import features


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
