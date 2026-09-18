import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',280); pd.set_option('display.max_rows',400)
DATA = sys.argv[1] if len(sys.argv)>1 else rdata.PARQUET
df = rdata.build(DATA); df['year']=df.index.year
df = S.build_sessions(df)
P=S.path(df); O,SP,H,L=P['open'],P['spread'],P['high'],P['low']
t0=df.groupby('sess').apply(lambda g:g.index[0])
ISm=(t0<=pd.Timestamp(rdata.IS_END,tz='UTC')); dow=t0.dt.dayofweek
print(f"data {DATA}: {len(df):,} bars, {df.index[0]:%Y-%m-%d} .. {df.index[-1]:%Y-%m-%d}, {O.shape[0]} sessions")

print("\n"+"="*100)
print("A. DRIFT PROFILE INSIDE THE ASIA WINDOW — mean gross bp per 6-bar (30min) slice")
print("   If uniform, a 1h slice captures only ~1/4 of a 4h drift but pays the full cost.")
print("="*100)
rows=[]
for k in range(1,60,6):
    if k+6 not in O.columns: continue
    g=((O[k+6]-O[k])/O[k]*1e4)
    hurdle=((SP[k]/2+SP[k+6]/2+0.10)/O[k]*1e4)
    sel = (dow!=6)
    gi=g[ISm&sel].dropna(); go=g[(~ISm)&sel].dropna()
    rows.append(dict(slice=f"k{k}-{k+6}", is_gross=gi.mean(), is_t=gi.mean()/gi.std()*np.sqrt(len(gi)),
                     oos_gross=go.mean(), hurdle=hurdle[sel].mean()))
r=pd.DataFrame(rows); r['is_net']=r['is_gross']-r['hurdle']; r['oos_net']=r['oos_gross']-r['hurdle']
print(r.round(2).to_string(index=False))
print(f"\ncumulative IS gross across slices k1..k49: {r['is_gross'].sum():.2f} bp   "
      f"total hurdle if traded as 8 separate 30m trades: {r['hurdle'].sum():.2f} bp")

print("\n"+"="*100)
print("B. FULL-DAY SHORT-HOLD SCAN — every start offset, holds of 12 (1h) and 24 (2h) bars")
print("   Reporting GROSS drift vs hurdle. A window is tradeable only if |gross| > hurdle.")
print("="*100)
res=[]
for hold in (12,24):
    for ki in range(1, 266-hold, 1):
        ko=ki+hold
        if ki not in O.columns or ko not in O.columns: continue
        g=((O[ko]-O[ki])/O[ki]*1e4)
        hd=((SP[ki]/2+SP[ko]/2+0.10)/O[ki]*1e4)
        sel=(dow!=6)
        gi=g[ISm&sel].dropna(); go=g[(~ISm)&sel].dropna()
        if len(gi)<400 or len(go)<150: continue
        res.append(dict(hold=hold,k_in=ki,hurdle=hd[sel].mean(),
                        is_g=gi.mean(), is_t=gi.mean()/gi.std()*np.sqrt(len(gi)),
                        oos_g=go.mean(), oos_t=go.mean()/go.std()*np.sqrt(len(go))))
rr=pd.DataFrame(res)
rr['is_net']=rr['is_g']-rr['hurdle']; rr['oos_net']=rr['oos_g']-rr['hurdle']
rr['agree']=np.sign(rr['is_net'])==np.sign(rr['oos_net'])
print(f"scanned {len(rr)} windows")
print(f"  IS net > 0 : {(rr['is_net']>0).sum()}  ({(rr['is_net']>0).mean()*100:.0f}%)")
print(f"  IS net > 0 AND OOS net > 0 : {((rr['is_net']>0)&(rr['oos_net']>0)).sum()}")
print(f"  shortable (IS gross < -hurdle): {(rr['is_g']+rr['hurdle']<0).sum()}")
print("\n--- top 12 by IS net (long side) ---")
print(rr.nlargest(12,'is_net').round(2).to_string(index=False))
print("\n--- of those, how many keep a positive OOS net? ---")
top=rr.nlargest(30,'is_net'); print(f"  {(top['oos_net']>0).sum()}/30")
