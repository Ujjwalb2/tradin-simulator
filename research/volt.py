import sys; sys.path.insert(0,'research')
import rdata, sess as S, strat, pandas as pd, numpy as np
pd.set_option('display.width',260)
d,P,A,m = strat.build()
t = strat.trade(P,A,m,1,48)
t = t[t['dow']!=6].dropna(subset=['bp']).copy()
t['atrbp'] = (A[1]/P['open'][1]*1e4).reindex(t.index)

def ev(x, lab):
    x=x.dropna()
    mu,sd=x.mean(),x.std()
    return dict(lab=lab,n=len(x),mean=round(mu,3),t=round(mu/sd*np.sqrt(len(x)),2),
                sharpe=round(mu/sd*np.sqrt(252),2), sum=round(x.sum(),1))

print("="*100); print("VOL-TARGETED SIZING: scale position by (target_atr / current_atr), capped"); print("="*100)
rows=[]
rows.append(ev(t['bp'],'unscaled (bp)'))
for cap in (2,3,5,99):
    tgt = t['atrbp'].expanding(60).median().shift(1)      # causal target
    w = (tgt/t['atrbp']).clip(upper=cap).fillna(0)
    rows.append(ev(t['bp']*w, f'vol-target cap {cap}x'))
# inverse-vol using prior 20d realised
w2 = (t['vol20'].expanding(60).median().shift(1)/t['vol20']).clip(upper=3).fillna(0)
rows.append(ev(t['bp']*w2,'inv realised-vol cap3'))
print(pd.DataFrame(rows).to_string(index=False))

print("\n"+"="*100); print("IS / OOS for the best sizing"); print("="*100)
tgt = t['atrbp'].expanding(60).median().shift(1)
w = (tgt/t['atrbp']).clip(upper=3).fillna(0)
t['r'] = t['bp']*w
for lab,sub in [('ALL',t),('IS',t[t['IS']]),('OOS',t[~t['IS']])]:
    print(lab, ev(sub['r'],lab))
g=t.groupby('year')['r']; r=g.agg(['size','mean','sum'])
r['t']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
r['sharpe']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(252))
print("\nby year:"); print(r.round(2).to_string())

print("\n"+"="*100); print("SECOND WINDOW? london leg (k_in=94, hold=72) and correlation with leg 1"); print("="*100)
t2 = strat.trade(P,A,m,94,166)
t2 = t2.dropna(subset=['bp'])
for lab,sub in [('ALL',t2),('IS',t2[t2['IS']]),('OOS',t2[~t2['IS']])]:
    print(lab, ev(sub['bp'],lab))
j = pd.DataFrame({'a':t['bp'],'b':t2['bp']}).dropna()
print(f"\ncorrelation leg1 vs leg2: {j['a'].corr(j['b']):.3f}   n={len(j)}")
print("combined 50/50:", ev((j['a']+j['b'])/2,'combo'))
