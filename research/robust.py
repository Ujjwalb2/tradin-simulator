import sys; sys.path.insert(0,'research')
import rdata, sess as S, strat, pandas as pd, numpy as np
pd.set_option('display.width',260)
rng = np.random.default_rng(7)
d,P,A,m = strat.build()
O,SP = P['open'],P['spread']

def series(k_in=1,k_out=48,slip=0.10,extra_spread=0.0,ex_sun=True):
    e=O[k_in]+ (SP[k_in]+extra_spread)/2 + slip
    x=O[k_out]-(SP[k_out]+extra_spread)/2 - slip
    bp=((x-e)/e*1e4).rename('bp').to_frame().join(m)
    if ex_sun: bp=bp[bp['dow']!=6]
    return bp.dropna(subset=['bp'])

t = series()
print("="*100); print("1. HEADLINE — long asia-open window (bar1->bar48 after reopen), ex-Sunday"); print("="*100)
x=t['bp']
print(f"n={len(x)} sessions over {(t['t0'].max()-t['t0'].min()).days/365.25:.1f} years")
print(f"mean {x.mean():.2f} bp/trade | median {x.median():.2f} | std {x.std():.1f}")
print(f"t-stat {x.mean()/x.std()*np.sqrt(len(x)):.2f} | Sharpe(ann, per-trade-day) {x.mean()/x.std()*np.sqrt(252):.2f}")
print(f"cumulative (sum of bp, unlevered 1x notional) = {x.sum()/100:.1f}%")
eq=x.cumsum(); dd=(eq-eq.cummax())
print(f"max drawdown {dd.min()/100:.1f}%  | longest flat {int((dd<0).astype(int).groupby((dd>=0).cumsum()).sum().max())} trades")
print(f"win rate {(x>0).mean()*100:.1f}% | avg win {x[x>0].mean():.1f} | avg loss {x[x<0].mean():.1f}")

print("\n"+"="*100); print("2. COST SENSITIVITY (extra spread added on top of Dukascopy raw)"); print("="*100)
for ex in (0.0,0.10,0.20,0.30,0.50):
    s=series(extra_spread=ex)['bp']
    print(f"  +${ex:.2f} spread -> mean {s.mean():+.2f} bp | sum {s.sum()/100:+.1f}% | t {s.mean()/s.std()*np.sqrt(len(s)):+.2f}")
print("  (breakeven spread: strategy dies when round-trip cost exceeds the ~3.5bp gross drift)")

print("\n"+"="*100); print("3. STATIONARY BLOCK BOOTSTRAP of the t-stat (10k reps, block=20 sessions)"); print("="*100)
v=x.to_numpy(); n=len(v); B=20
ts=[]
for _ in range(10000):
    idx=[]
    while len(idx)<n:
        s0=rng.integers(0,n); idx.extend(range(s0,min(s0+B,n)))
    s=v[np.array(idx[:n])]
    ts.append(s.mean()/s.std()*np.sqrt(n))
ts=np.array(ts)
print(f"  bootstrap mean t {ts.mean():.2f}, 5th pct {np.percentile(ts,5):.2f}, 95th {np.percentile(ts,95):.2f}")
print(f"  P(t<=0) = {(ts<=0).mean()*100:.1f}%   -> one-sided p-value approx {(ts<=0).mean():.3f}")

print("\n"+"="*100); print("4. MULTIPLE-TESTING HAIRCUT"); print("="*100)
N_TRIALS=396
obs_sh = x.mean()/x.std()*np.sqrt(252)
yrs=(t['t0'].max()-t['t0'].min()).days/365.25
# expected max Sharpe of N independent zero-edge trials (Bailey/Lopez de Prado approximation)
g=0.5772
e_max = np.sqrt(2*np.log(N_TRIALS))*(1-g/(2*np.log(N_TRIALS))) if N_TRIALS>1 else 0
e_max_sh = e_max/np.sqrt(yrs)
print(f"  observed annualised Sharpe {obs_sh:.2f} over {yrs:.1f}y")
print(f"  expected BEST Sharpe from {N_TRIALS} pure-noise window trials ~ {e_max_sh:.2f}")
print(f"  -> deflated verdict: {'PASSES (obs > noise max)' if obs_sh>e_max_sh else 'FAILS — indistinguishable from best-of-noise'}")

print("\n"+"="*100); print("5. PARAMETER PLATEAU (is it a knife edge?)  mean bp by entry/exit bar"); print("="*100)
tab=pd.DataFrame({ko:{ki: round(series(ki,ko)['bp'].mean(),2) for ki in (1,2,4,6,9,12)} for ko in (36,42,48,54,60,72)})
tab.index.name='k_in'; tab.columns.name='k_out'; print(tab.to_string())

print("\n"+"="*100); print("6. BENCHMARKS (same 4-year span)"); print("="*100)
sc=d.groupby('sess')['close'].last(); dr=np.log(sc/sc.shift(1)).dropna()
print(f"  buy & hold gold: total {dr.sum()*100:.1f}%, ann Sharpe {dr.mean()/dr.std()*np.sqrt(252):.2f}, "
      f"maxDD {((dr.cumsum()-dr.cumsum().cummax()).min()*100):.1f}%")
print(f"  AOD strategy   : total {x.sum()/100:.1f}%, ann Sharpe {x.mean()/x.std()*np.sqrt(252):.2f}, maxDD {dd.min()/100:.1f}%")
print(f"  AOD time in market: {len(x)*48*5/60:.0f}h of {(t['t0'].max()-t['t0'].min()).days*24:.0f}h = "
      f"{len(x)*48*5/60/((t['t0'].max()-t['t0'].min()).days*24)*100:.1f}%")
