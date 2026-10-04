"""Causal features: only completed bars are used, pivots carry confirmation dates."""
import numpy as np
import pandas as pd

def clean(v):
    if isinstance(v, dict):
        return {k: clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean(x) for x in v]
    if isinstance(v, (np.bool_,)):
        return bool(v)
    if isinstance(v, (float, np.floating)):
        return float(v) if np.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    return v

def features(raw, params=None):
    if raw.empty:
        return raw.copy()
    f = raw.copy().reset_index(drop=True)
    params=params or {}
    factor = f.get('factor', pd.Series(1., index=f.index)).fillna(1.)
    for col in ('open', 'high', 'low', 'close'):
        if 'raw_'+col not in f: f['raw_' + col] = f[col]
        f[col] *= factor
    c, o, h, l, v = [f[x] for x in ('close', 'open', 'high', 'low', 'volume')]
    for n in (3, 5, 10, 20, 60, 120, 240):
        f[f'ma{n}'] = c.rolling(n).mean()
        f[f'ma{n}_up'] = c > c.shift(n)
    f['body'] = (c - o) / o
    f['change'] = c.pct_change(fill_method=None)
    f['upper_shadow'] = (h - pd.concat([c, o], axis=1).max(axis=1)) / o
    f['lower_shadow'] = (pd.concat([c, o], axis=1).min(axis=1) - l) / o
    f['volume5'] = v.rolling(5).mean()
    f['volume20'] = v.rolling(20).mean()
    f['volume_ratio'] = v / v.shift(1).rolling(5).mean().replace(0, np.nan)
    f['yesterday_volume_ratio'] = v / v.shift(1).replace(0, np.nan)
    f['macd'] = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    f['macd_signal'] = f.macd.ewm(span=9, adjust=False).mean()
    f['macd_hist'] = (f.macd - f.macd_signal) * 2
    rsv = 100 * (c - l.rolling(9).min()) / (h.rolling(9).max() - l.rolling(9).min()).replace(0, np.nan)
    kval, dval, k, d = [], [], 50., 50.
    for value in rsv:
        if pd.notna(value):
            k = k * 2 / 3 + value / 3
            d = d * 2 / 3 + k / 3
        kval.append(k); dval.append(d)
    f['k'], f['d'] = kval, dval
    for n in (6, 12):
        diff = c.diff()
        gain = diff.clip(lower=0).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
        loss = (-diff.clip(upper=0)).ewm(alpha=1/n, adjust=False, min_periods=n).mean()
        f[f'rsi{n}'] = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
        f.loc[(loss == 0) & (gain > 0), f'rsi{n}'] = 100
    f['bias20'] = c / f.ma20 - 1
    std = c.rolling(20).std(ddof=0)
    f['bb_upper'], f['bb_lower'] = f.ma20 + 2 * std, f.ma20 - 2 * std
    f['channel_upper'], f['channel_lower'] = f.ma20 * 1.15, f.ma20 * .85
    f['tangle'] = (f[['ma5','ma10','ma20']].max(axis=1) / f[['ma5','ma10','ma20']].min(axis=1) - 1) < params.get('tangle_spread',.03)
    f['bull3'] = (f.ma5 > f.ma10) & (f.ma10 > f.ma20)
    f['bull4'] = f.bull3 & (f.ma20 > f.ma60)
    f['bear3'] = (f.ma5 < f.ma10) & (f.ma10 < f.ma20)
    f['bear4'] = f.bear3 & (f.ma20 < f.ma60)
    f['range_high'] = h.shift(1).rolling(params.get('range_days',10)).max()
    f['range_low'] = l.shift(1).rolling(params.get('range_days',10)).min()
    f['range_width'] = f.range_high / f.range_low - 1
    f['high60'] = h.shift(1).rolling(60).max()
    f['low60'] = l.shift(1).rolling(60).min()
    f['rise_from_bottom'] = c / l.rolling(120, min_periods=20).min() - 1
    f['return20'] = c.pct_change(20, fill_method=None)
    f['gap_up'] = l > h.shift(1)
    f['gap_down'] = h < l.shift(1)
    # Exclude all factor changes from gap detection (corporate actions).
    action = factor.ne(factor.shift(1)) & factor.shift(1).notna()
    f.loc[action, ['gap_up', 'gap_down']] = False
    f['hidden_gap_up'] = (pd.concat([o,c],axis=1).min(axis=1) > pd.concat([o,c],axis=1).max(axis=1).shift(1)) & ~f.gap_up
    f['hidden_gap_down'] = (pd.concat([o,c],axis=1).max(axis=1) < pd.concat([o,c],axis=1).min(axis=1).shift(1)) & ~f.gap_down
    f.loc[action, ['hidden_gap_up', 'hidden_gap_down']] = False
    for n in (5,10,20):
        highs, lows, side = [], [], None
        ph, pl, hh, hl, lh, ll = [], [], [], [], [], []
        phi,pli,supports,resistances=[],[],[],[]
        high_points,low_points=[],[]
        group_high=group_low=np.nan;high_index=low_index=0
        close_values=c.to_numpy();high_values=h.to_numpy();low_values=l.to_numpy()
        def line(points,i):
            if len(points)<2 or points[-1][0]==points[-2][0]:return np.nan
            (a,pa),(b,pb)=points[-2:]
            return pb+(pb-pa)*(i-b)/(b-a)
        for i, ma in enumerate(f[f'ma{n}'].to_numpy()):
            if np.isnan(ma):
                ph.append(np.nan); pl.append(np.nan); hh.append(False); hl.append(False); lh.append(False); ll.append(False)
                phi.append(np.nan);pli.append(np.nan);supports.append(np.nan);resistances.append(np.nan)
                continue
            new_side = 1 if close_values[i] >= ma else -1
            if side is None:
                group_high,group_low=high_values[i],low_values[i];high_index=low_index=i
            else:
                if high_values[i]>group_high:group_high=high_values[i];high_index=i
                if low_values[i]<group_low:group_low=low_values[i];low_index=i
            if side is not None and side != new_side:
                if side == 1:
                    highs.append(float(group_high))
                    high_points.append((high_index,highs[-1]))
                else:
                    lows.append(float(group_low))
                    low_points.append((low_index,lows[-1]))
                group_high,group_low=high_values[i],low_values[i];high_index=low_index=i
            side = new_side
            ph.append(highs[-1] if highs else np.nan); pl.append(lows[-1] if lows else np.nan)
            hh.append(len(highs)>1 and highs[-1]>highs[-2]); lh.append(len(highs)>1 and highs[-1]<highs[-2])
            hl.append(len(lows)>1 and lows[-1]>lows[-2]); ll.append(len(lows)>1 and lows[-1]<lows[-2])
            phi.append(high_points[-1][0] if high_points else np.nan);pli.append(low_points[-1][0] if low_points else np.nan)
            supports.append(line(low_points,i));resistances.append(line(high_points,i))
        for name, values in [('pivot_high',ph),('pivot_low',pl),('higher_high',hh),('higher_low',hl),('lower_high',lh),('lower_low',ll)]:
            f[f'{name}{n}'] = values
        for name,values in [('pivot_high_index',phi),('pivot_low_index',pli),('support_line',supports),('resistance_line',resistances)]:f[f'{name}{n}']=values
    f['trend'] = np.where(f.higher_high5 & f.higher_low5, 'bull', np.where(f.lower_high5 & f.lower_low5, 'bear', 'range'))
    f['price_divergence'] = (c > c.shift(5)) & (v.rolling(5).mean() < v.shift(5).rolling(5).mean())
    f['macd_divergence'] = (c > c.shift(10)) & (f.macd_hist < f.macd_hist.shift(10))
    f['kd_divergence'] = (c > c.shift(10)) & (f.k < f.k.shift(10)) & f.k.between(20,80)
    for side,condition in [('red',(f.body>.035)&(f.volume_ratio>=1.3)),('black',(f.body<-.035)&(f.volume_ratio>=1.3))]:
        for name,values in [('high',h),('mid',(o+c)/2),('low',l)]:f[f'key_{side}_{name}']=values.where(condition).ffill()
    f['bull_confirmation']=(f.trend=='bull')&(f.trend.shift(1)!='bull')
    f=f.copy()
    f['bear_confirmation']=(f.trend=='bear')&(f.trend.shift(1)!='bear')
    # Map only prior completed weeks. No current-week final high/low can
    # become visible to a Monday or Tuesday historical observation.
    week_key=pd.to_datetime(f.date).dt.to_period('W-FRI')
    weekly=f.assign(week_key=week_key).groupby('week_key').agg(high=('high','max'),low=('low','min'),close=('close','last'))
    resistance=weekly.high.rolling(12).max().shift(1)
    support=weekly.low.rolling(12).min().shift(1)
    week_ma=weekly.close.rolling(20).mean().shift(1)
    f['weekly_resistance']=week_key.map(resistance)
    f['weekly_support']=week_key.map(support)
    f['weekly_ma20']=week_key.map(week_ma)
    f['weekly_pressure_up']=((h>=f.weekly_resistance*.97)&(c<=f.weekly_resistance*1.01) | (h>=f.weekly_ma20*.97)&(c<f.weekly_ma20)).rolling(5,min_periods=1).max().astype(bool)
    f['weekly_pressure_down']=((l<=f.weekly_support*1.03)&(c>=f.weekly_support*.99) | (l<=f.weekly_ma20*1.03)&(c>f.weekly_ma20)).rolling(5,min_periods=1).max().astype(bool)
    return f

def aggregate(raw, period='week'):
    """End-of-period label never after latest available date; no future bars."""
    if raw.empty:
        return raw.copy()
    frame = raw.copy()
    for col in ('open','high','low','close'):
        frame['raw_'+col]=frame[col]
        frame[col]=frame[col]*frame.factor
    frame['factor']=1.
    frame['period'] = pd.to_datetime(frame.date).dt.to_period('W-FRI' if period == 'week' else 'M')
    rules = {'date':'last','open':'first','high':'max','low':'min','close':'last','raw_open':'first','raw_high':'max','raw_low':'min','raw_close':'last','volume':'sum','factor':'last','adjustment_verified':'min'}
    return frame.groupby('period').agg({k:v for k,v in rules.items() if k in frame}).reset_index(drop=True)

def gaps(f):
    result = []
    for i in range(1,len(f)):
        row, prev = f.iloc[i], f.iloc[i-1]
        for direction in ('up','down'):
            if not row['gap_'+direction]:
                continue
            lower, upper = (prev.high,row.low) if direction=='up' else (row.high,prev.low)
            after = f.iloc[i+1:]
            filled = after[after.close <= lower] if direction=='up' else after[after.close >= upper]
            status, filled_date = '未補', None
            if len(filled):
                real=filled[(filled.volume_ratio>=1.3)&(filled.body<-.02 if direction=='up' else filled.body>.02)]
                x=real.iloc[0] if len(real) else filled.iloc[0]
                filled_date=x.date;status='真封口' if len(real) else '假封口'
            result.append(clean({'date':row.date,'direction':direction,'upper_high':max(row.high,prev.high),'upper':upper,'lower':lower,'lower_bottom':min(row.low,prev.low),'status':status,'filled_date':filled_date}))
    return result
