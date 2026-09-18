"""Asia-Open Drift (AOD) — candidate production strategy. Evaluation harness."""
import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np

def build(df=None):
    if df is None: df = rdata.build()
    d = S.build_sessions(df)
    P = S.path(d); A = S.path(d,('atr14',))['atr14']
    t0 = d.groupby('sess').apply(lambda g: g.index[0])
    m = pd.DataFrame({'t0':t0}); m['dow']=t0.dt.dayofweek; m['year']=t0.dt.year
    m['IS'] = t0<=pd.Timestamp(rdata.IS_END,tz='UTC')
    sc = d.groupby('sess')['close'].last()
    m['ma50'] = sc.shift(1).rolling(50).mean(); m['pc']=sc.shift(1)
    m['above50'] = (m['pc']>m['ma50']).astype(float)
    dret = np.log(sc/sc.shift(1)); m['vol20']=dret.rolling(20).std().shift(1)
    m['volq'] = m['vol20'].rolling(250).rank(pct=True)
    return d, P, A, m

def trade(P, A, m, k_in=1, k_out=48, slip=0.10, sl_atr=None, spread_cap=None):
    """Long from k_in open to k_out open. Optional ATR stop checked on lows."""
    O,H,L,SP = P['open'],P['high'],P['low'],P['spread']
    e = O[k_in] + SP[k_in]/2 + slip
    atr = A[k_in]
    out = pd.DataFrame(index=O.index)
    out['entry']=e; out['atr']=atr
    if sl_atr:
        stop = e - sl_atr*atr
        hit = pd.Series(np.nan, index=O.index)
        for k in range(k_in, k_out):
            if k not in L.columns: continue
            msk = hit.isna() & (L[k]<=stop)
            hit[msk]=k
        px_stop = stop - (SP[k_in]/2+slip)
        px_time = O[k_out] - SP[k_out]/2 - slip
        out['exit'] = np.where(hit.notna(), px_stop, px_time)
        out['stopped'] = hit.notna()
    else:
        out['exit'] = O[k_out] - SP[k_out]/2 - slip
        out['stopped']=False
    out['pnl'] = out['exit']-out['entry']
    out['bp']  = out['pnl']/out['entry']*1e4
    if spread_cap is not None:
        out.loc[SP[k_in]>spread_cap, 'bp']=np.nan       # skip if entry spread too wide
    return out.join(m)

def report(t, label):
    t = t.dropna(subset=['bp'])
    def blk(s):
        if len(s)<10: return dict(n=len(s))
        mu=s.mean(); sd=s.std()
        return dict(n=len(s), mean_bp=round(mu,2), t=round(mu/sd*np.sqrt(len(s)),2),
                    sum_pct=round(s.sum()/100,1), win=round((s>0).mean()*100,1),
                    sharpe=round(mu/sd*np.sqrt(252),2))
    a=blk(t['bp']); i=blk(t[t['IS']]['bp']); o=blk(t[~t['IS']]['bp'])
    print(f"\n### {label}")
    print(f"  ALL {a}")
    print(f"  IS  {i}")
    print(f"  OOS {o}")
    return a,i,o

if __name__=="__main__":
    pd.set_option('display.width',250)
    d,P,A,m = build()
    print("="*100); print("ASIA-OPEN DRIFT — variant comparison (net of real spread + $0.10 slippage)"); print("="*100)
    base = trade(P,A,m,1,48); report(base,"BASE long bar1->bar48, no filter, no stop")
    report(trade(P,A,m,1,48).pipe(lambda x: x[x['dow']!=6]), "ex-Sunday")
    for sl in (1.0,1.5,2.0,3.0):
        report(trade(P,A,m,1,48,sl_atr=sl), f"with {sl}x ATR stop")
    for f,nm in [(lambda x: x[x['above50']==1],'trend filter: prev close > 50d MA'),
                 (lambda x: x[x['volq']<0.5],'low-vol half'),
                 (lambda x: x[x['volq']>=0.5],'high-vol half')]:
        report(base.pipe(f), nm)
    print("\n"+"="*100); print("BY YEAR (base, ex-Sunday)"); print("="*100)
    b=base[base['dow']!=6]
    g=b.groupby('year')['bp']; r=g.agg(['size','mean','sum']); r['sum%']=r['sum']/100
    r['t']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s))); print(r.round(2).to_string())
