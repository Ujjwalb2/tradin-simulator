import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',300)
df = rdata.build(); df['year']=df.index.year
df = S.build_sessions(df)
P = S.path(df); O,H,L,C,SP,A = P['open'],P['high'],P['low'],P['close'],P['spread'],S.path(df,('atr14',))['atr14']
t0 = df.groupby('sess').apply(lambda g: g.index[0])
dow = t0.dt.dayofweek
ISm = t0 <= pd.Timestamp(rdata.IS_END, tz='UTC')

WIN_END = 48                       # end of asia-open window (4h after reopen)
ref = O[1]                         # window reference price (bar 1 open, post-gap)
atr = A[1]
exitp = O[WIN_END]

print("="*100)
print("Q: conditional on how far price has moved from the window open by bar k,")
print("   what is the return from bar k to end-of-window (bar 48)?  IS ONLY, gross bp")
print("="*100)
for k in (6,12,18,24):
    dev = (O[k]-ref)/atr                        # deviation in ATR at bar k
    fwd = (exitp-O[k])/O[k]*1e4                 # bp to window end
    d = pd.DataFrame({'dev':dev,'fwd':fwd})[ISm & (dow!=6)].dropna()
    q = pd.qcut(d['dev'],6,duplicates='drop')
    r = d.groupby(q,observed=True)['fwd'].agg(['size','mean'])
    r['t']=d.groupby(q,observed=True)['fwd'].apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
    print(f"\n-- deviation measured at bar k={k} (ATR units), forward to bar {WIN_END} --")
    print(r.round(2).to_string())

print("\n"+"="*100)
print("Q2: same but deviation measured from the window's RUNNING HIGH (pullback depth)")
print("="*100)
for k in (12,24):
    runhi = H.loc[:, 1:k].max(axis=1)
    pull = (O[k]-runhi)/atr
    fwd = (exitp-O[k])/O[k]*1e4
    d = pd.DataFrame({'pull':pull,'fwd':fwd})[ISm & (dow!=6)].dropna()
    q = pd.qcut(d['pull'],6,duplicates='drop')
    r=d.groupby(q,observed=True)['fwd'].agg(['size','mean'])
    r['t']=d.groupby(q,observed=True)['fwd'].apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
    print(f"\n-- pullback from running high at k={k} --"); print(r.round(2).to_string())

print("\n"+"="*100)
print("Q3: FIRST-TOUCH dip entry. Buy the first time price trades ref - x*ATR within bars 1..24.")
print("   Exit at bar 48 open. Net of spread+slippage. IS only, ex-Sunday.")
print("="*100)
rows=[]
for x in (0.0,0.25,0.5,0.75,1.0,1.5,2.0):
    lim = ref - x*atr
    hit_k = pd.Series(np.nan, index=O.index)
    for k in range(1,25):
        m = hit_k.isna() & (L[k]<=lim)
        hit_k[m]=k
    ent = lim.copy()                      # limit fill at the level
    ent = ent + SP[1]/2 + 0.10            # pay half spread + slip
    ex  = exitp - SP[WIN_END]/2 - 0.10
    pnl = (ex-ent).where(hit_k.notna())
    bp  = pnl/ent*1e4
    d = pd.DataFrame({'bp':bp,'hit':hit_k})[ISm & (dow!=6)]
    f = d['bp'].dropna()
    if len(f)<50: continue
    rows.append(dict(x_atr=x, n=len(f), fill_rate=round(len(f)/d.shape[0]*100,1),
                     mean_bp=round(f.mean(),2), t=round(f.mean()/f.std()*np.sqrt(len(f)),2),
                     sum_pct=round(f.sum()/100,1), win=round((f>0).mean()*100,1)))
print(pd.DataFrame(rows).to_string(index=False))
