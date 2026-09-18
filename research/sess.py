"""Session-level table: one row per trading day, anchored on the daily reopen."""
import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np

def build_sessions(df=None):
    if df is None: df = rdata.build()
    gapm = df.index.to_series().diff().dt.total_seconds()/60
    df = df.copy(); df['reopen'] = gapm > 10
    df.loc[df.index[0],'reopen'] = True
    df['sess'] = df['reopen'].cumsum()
    df['k'] = df.groupby('sess').cumcount()
    df['sess_len'] = df['sess'].map(df.groupby('sess').size())
    df = df[df['sess_len']>=200]
    return df

def session_table(df):
    """Features known AT the reopen (i.e. from the *previous* session) + fwd paths."""
    g = df.groupby('sess')
    st = pd.DataFrame(index=g.size().index)
    st['t0']    = g.apply(lambda x: x.index[0])
    st['year']  = g['year'].first() if 'year' in df else st['t0'].dt.year
    st['dow']   = st['t0'].dt.dayofweek
    st['open0'] = g['open'].first()
    st['len']   = g.size()
    # previous-session summary (shift by one session)
    prev_close  = g['close'].last().shift(1)
    prev_open   = g['open'].first().shift(1)
    prev_hi     = g['high'].max().shift(1)
    prev_lo     = g['low'].min().shift(1)
    st['prev_ret']   = np.log(prev_close/prev_open)              # prior day body
    st['prev_range'] = (prev_hi-prev_lo)/prev_close
    st['prev_clspos']= (prev_close-prev_lo)/(prev_hi-prev_lo)    # where prior day closed in its range
    st['gap']        = np.log(st['open0']/prev_close)            # reopen gap
    # NY-afternoon return of the prior session = last 60 bars before its close
    ny = g.apply(lambda x: np.log(x['close'].iloc[-1]/x['close'].iloc[-61]) if len(x)>61 else np.nan)
    st['prev_ny'] = ny.shift(1)
    # trailing momentum on session closes
    sc = g['close'].last()
    for n in (1,3,5,10,20,60):
        st[f'mom{n}d'] = np.log(sc/sc.shift(n)).shift(1)
    st['above_ma20'] = (sc.shift(1) > sc.shift(1).rolling(20).mean()).astype(float)
    st['above_ma50'] = (sc.shift(1) > sc.shift(1).rolling(50).mean()).astype(float)
    # realised vol of prior sessions (daily close-to-close)
    dret = np.log(sc/sc.shift(1))
    st['vol20'] = dret.rolling(20).std().shift(1)
    st['vol_z'] = (st['vol20']-st['vol20'].rolling(120).mean())/st['vol20'].rolling(120).std()
    st['atr_pct'] = (g['atr14'].first()/st['open0'])
    return st

def path(df, cols=('open','high','low','close','spread')):
    return {c: df.pivot_table(index='sess', columns='k', values=c, aggfunc='first') for c in cols}
