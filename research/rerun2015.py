"""Decisive re-run on the extended 2015+ dataset.

ERA DEFINITIONS
  HOLDOUT : 2015-01-01 .. 2022-08-31  -- never seen during design. The real test.
  DESIGN  : 2022-09-01 .. 2025-06-30  -- where AOD was built.
  FWD     : 2025-07-01 .. 2026-09-09  -- the walk-forward used in round 1.
"""
import sys; sys.path.insert(0,'research'); sys.path.insert(0,'src')
import rdata, sess as S, engine, pandas as pd, numpy as np
pd.set_option('display.width',280); pd.set_option('display.max_rows',400)

DATA = sys.argv[1] if len(sys.argv)>1 else rdata.PARQUET
HOLD_END  = pd.Timestamp('2022-08-31', tz='UTC')
DES_END   = pd.Timestamp('2025-06-30', tz='UTC')

def era(ts):
    return np.where(ts<=HOLD_END,'1_HOLDOUT', np.where(ts<=DES_END,'2_DESIGN','3_FWD'))

df = rdata.build(DATA); df['year']=df.index.year
print(f"DATA {DATA}\n  {len(df):,} bars  {df.index[0]:%Y-%m-%d} .. {df.index[-1]:%Y-%m-%d}")
d = S.build_sessions(df)
P=S.path(d); O,SP=P['open'],P['spread']
t0=d.groupby('sess').apply(lambda g:g.index[0])
E=pd.Series(era(t0), index=t0.index); dow=t0.dt.dayofweek
print("  sessions per era:"); print(E.value_counts().sort_index().to_string())

# ---------------------------------------------------------------- 1. TOD decomposition
gapm=df.index.to_series().diff().dt.total_seconds()/60
df['reopen']=gapm>10
cont=df[~df['reopen']].copy()
def blk(h):
    if 22<=h or h<=1: return 'A 22-01 asia-open'
    if 2<=h<=6: return 'B 02-06 asia'
    if 7<=h<=11: return 'C 07-11 london'
    if 12<=h<=16: return 'D 12-16 ny overlap'
    return 'E 17-21 ny pm'
cont['blk']=cont['hour'].map(blk)
print("\n"+"="*100); print("1. TIME-OF-DAY DECOMPOSITION, gap bars removed, log-return % per year"); print("="*100)
pb=cont.pivot_table(index='blk',columns='year',values='ret',aggfunc='sum')*100
pb['TOTAL']=pb.sum(axis=1); pb['bars']=cont.groupby('blk').size()
print(pb.round(1).to_string())
print("\ngold total log-return per year (%):")
print((cont.groupby('year')['ret'].sum()*100).round(1).to_string())

# ---------------------------------------------------------------- 2. AOD, locked params
print("\n"+"="*100); print("2. AOD with LOCKED parameters (k_in 2/3/4 -> k_out 36/42/48, ex-Sunday)"); print("="*100)
def leg(ki,ko,extra=0.0):
    e=O[ki]+(SP[ki]+extra)/2+0.10; x=O[ko]-(SP[ko]+extra)/2-0.10
    return ((x-e)/e*1e4)
legs=[leg(ki,ko) for ki in (2,3,4) for ko in (36,42,48)]
aod=pd.concat(legs,axis=1).mean(axis=1)
aod=aod[dow!=6].dropna()
Ea=E.reindex(aod.index); ya=t0.reindex(aod.index).dt.year
def desc(x,lab):
    if len(x)<30: return dict(era=lab,n=len(x))
    return dict(era=lab,n=len(x),mean_bp=round(x.mean(),2),
                t=round(x.mean()/x.std()*np.sqrt(len(x)),2),
                sharpe=round(x.mean()/x.std()*np.sqrt(252),2),
                total_pct=round(x.sum()/100,1),
                maxdd=round((x.cumsum()-x.cumsum().cummax()).min()/100,1),
                win=round((x>0).mean()*100,1))
print(pd.DataFrame([desc(aod[Ea==e],e) for e in sorted(Ea.unique())]+[desc(aod,'ALL')]).to_string(index=False))
print("\nby year:")
g=aod.groupby(ya); r=g.agg(['size','mean','sum']); r['sum%']=(r['sum']/100).round(2)
r['sharpe']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(252)); print(r.round(2).to_string())

# ---------------------------------------------------------------- 3. Short-hold variant
print("\n"+"="*100); print("3. SHORT-HOLD (2h) variant: k_in 14/16/18 -> k_out +24, ex-Sunday"); print("="*100)
legs2=[leg(ki,ki+24) for ki in (14,16,18)]
sh=pd.concat(legs2,axis=1).mean(axis=1); sh=sh[dow!=6].dropna()
Es=E.reindex(sh.index); ys=t0.reindex(sh.index).dt.year
print(pd.DataFrame([desc(sh[Es==e],e) for e in sorted(Es.unique())]+[desc(sh,'ALL')]).to_string(index=False))
print("\nby year:")
g=sh.groupby(ys); r=g.agg(['size','mean','sum']); r['sum%']=(r['sum']/100).round(2)
r['sharpe']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(252)); print(r.round(2).to_string())

# ---------------------------------------------------------------- 4. 1h variant
print("\n"+"="*100); print("4. ONE-HOUR variant: k_in 14/16/18 -> k_out +12, ex-Sunday"); print("="*100)
legs3=[leg(ki,ki+12) for ki in (14,16,18)]
oh=pd.concat(legs3,axis=1).mean(axis=1); oh=oh[dow!=6].dropna()
Eo=E.reindex(oh.index)
print(pd.DataFrame([desc(oh[Eo==e],e) for e in sorted(Eo.unique())]+[desc(oh,'ALL')]).to_string(index=False))

# ---------------------------------------------------------------- 5. cost sensitivity
print("\n"+"="*100); print("5. COST SENSITIVITY on the full 11y sample (extra spread on top of quoted)"); print("="*100)
for ex in (0.0,0.10,0.20,0.30,0.50):
    a=pd.concat([leg(ki,ko,ex) for ki in (2,3,4) for ko in (36,42,48)],axis=1).mean(axis=1)[dow!=6].dropna()
    s=pd.concat([leg(ki,ki+24,ex) for ki in (14,16,18)],axis=1).mean(axis=1)[dow!=6].dropna()
    print(f"  +${ex:.2f}:  AOD(3.5h) {a.mean():+.2f}bp t={a.mean()/a.std()*np.sqrt(len(a)):+.2f} "
          f"| SHORT(2h) {s.mean():+.2f}bp t={s.mean()/s.std()*np.sqrt(len(s)):+.2f}")

# ---------------------------------------------------------------- 6. window scan, 11y
print("\n"+"="*100); print("6. WINDOW SCAN on 11y — gross drift vs hurdle, holdout vs design+fwd"); print("="*100)
res=[]
for hold in (12,24,36,48):
    for ki in range(1,266-hold,3):
        ko=ki+hold
        if ki not in O.columns or ko not in O.columns: continue
        g=((O[ko]-O[ki])/O[ki]*1e4); hd=((SP[ki]/2+SP[ko]/2+0.10)/O[ki]*1e4)
        sel=(dow!=6); m_h=(E=='1_HOLDOUT')&sel; m_r=(E!='1_HOLDOUT')&sel
        gh=g[m_h].dropna(); gr=g[m_r].dropna()
        if len(gh)<600 or len(gr)<400: continue
        res.append(dict(hold=hold,k_in=ki,hurdle=hd[sel].mean(),
            hold_g=gh.mean(), hold_t=gh.mean()/gh.std()*np.sqrt(len(gh)),
            rest_g=gr.mean(), rest_t=gr.mean()/gr.std()*np.sqrt(len(gr))))
rr=pd.DataFrame(res); rr['hold_net']=rr['hold_g']-rr['hurdle']; rr['rest_net']=rr['rest_g']-rr['hurdle']
print(f"scanned {len(rr)} windows. holdout net>0: {(rr['hold_net']>0).sum()} | both eras net>0: {((rr['hold_net']>0)&(rr['rest_net']>0)).sum()}")
print("\n--- top 15 by HOLDOUT net (i.e. best on data never used in design) ---")
print(rr.nlargest(15,'hold_net').round(2).to_string(index=False))
print(f"\nshortable anywhere (holdout gross < -hurdle): {(rr['hold_g']+rr['hurdle']<0).sum()}")
