import sys; sys.path.insert(0,'research')
import rdata, sess as S, strat, pandas as pd, numpy as np
pd.set_option('display.width',280)
d,P,A,m = strat.build(); O,SP=P['open'],P['spread']
def bp(ki,ko,extra=0.0,ex_sun=True):
    e=O[ki]+(SP[ki]+extra)/2+0.10; x=O[ko]-(SP[ko]+extra)/2-0.10
    r=((x-e)/e*1e4).rename('bp').to_frame().join(m)
    if ex_sun: r=r[r['dow']!=6]
    return r.dropna(subset=['bp'])

print("="*115); print("PLATEAU MAP — mean net bp.  IS (top) / OOS (bottom) for each entry/exit pair"); print("="*115)
kis=[1,2,3,4,6,8,10]; kos=[30,36,42,48,54,60]
for lab,sel in [('IS',lambda t:t[t['IS']]),('OOS',lambda t:t[~t['IS']])]:
    tab=pd.DataFrame({ko:{ki: round(sel(bp(ki,ko))['bp'].mean(),2) for ki in kis} for ko in kos})
    tab.index.name=f'k_in ({lab})'; tab.columns.name='k_out'
    print(f"\n--- {lab} ---"); print(tab.to_string())
print("\nBoth panels positive nearly everywhere => broad plateau, not a knife-edge fit.")

print("\n"+"="*115); print("PLATEAU-AVERAGE STRATEGY (average of the 5 configs k_in in 2..4 x k_out in 36..48)"); print("="*115)
cfgs=[(ki,ko) for ki in (2,3,4) for ko in (36,42,48)]
mat=pd.concat([bp(ki,ko)['bp'].rename(f'{ki}_{ko}') for ki,ko in cfgs],axis=1)
avg=mat.mean(axis=1).dropna()
meta=bp(3,42).reindex(avg.index)
print(f"n={len(avg)} mean {avg.mean():.2f}bp t={avg.mean()/avg.std()*np.sqrt(len(avg)):.2f} "
      f"sharpe {avg.mean()/avg.std()*np.sqrt(252):.2f} total {avg.sum()/100:.1f}%")
print(f"  IS  mean {avg[meta['IS']].mean():.2f}  t {avg[meta['IS']].mean()/avg[meta['IS']].std()*np.sqrt(meta['IS'].sum()):.2f}")
print(f"  OOS mean {avg[~meta['IS']].mean():.2f}  t {avg[~meta['IS']].mean()/avg[~meta['IS']].std()*np.sqrt((~meta['IS']).sum()):.2f}")
g=avg.groupby(meta['year']); r=g.agg(['size','mean','sum']); r['sum%']=r['sum']/100
r['sharpe']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(252)); print("\nby year:"); print(r.round(2).to_string())
eq=avg.cumsum(); print(f"\nmaxDD {(eq-eq.cummax()).min()/100:.1f}%   win {(avg>0).mean()*100:.1f}%")

print("\n"+"="*115); print("SANITY: is this just gold beta? regress strategy bp on same-session gold return"); print("="*115)
sc=d.groupby('sess')['close'].last(); dr=(np.log(sc/sc.shift(1))*1e4).reindex(avg.index)
j=pd.DataFrame({'s':avg,'g':dr}).dropna()
beta=np.polyfit(j['g'],j['s'],1); resid=j['s']-(beta[0]*j['g']+beta[1])
print(f"  beta to gold daily return = {beta[0]:.3f}   alpha = {beta[1]:.2f} bp/session")
print(f"  residual alpha t-stat = {resid.mean()/resid.std()*np.sqrt(len(resid)):.2f}  (nb: window is *inside* the session)")
print(f"  correlation with gold daily return: {j['s'].corr(j['g']):.3f}")
