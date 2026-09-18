import sys; sys.path.insert(0,'research')
import rdata, sess as S, strat, pandas as pd, numpy as np
pd.set_option('display.width',260)
d,P,A,m = strat.build(); O,SP,L,H = P['open'],P['spread'],P['low'],P['high']

def run(k_in,k_out,entry_mode,exit_mode,extra=0.0,ex_sun=True):
    """entry/exit mode: 'cross' pay half-spread+slip, 'mid' pay 0, 'passive' earn nothing but no spread."""
    sp_in = SP[k_in]+extra; sp_out = SP[k_out]+extra
    e = O[k_in] + (sp_in/2+0.10 if entry_mode=='cross' else 0.02 if entry_mode=='passive' else 0)
    x = O[k_out] - (sp_out/2+0.10 if exit_mode=='cross' else 0.02 if exit_mode=='passive' else 0)
    bp = ((x-e)/e*1e4).rename('bp').to_frame().join(m)
    if ex_sun: bp=bp[bp['dow']!=6]
    return bp.dropna(subset=['bp'])

def st(x,lab):
    s=x['bp']; 
    return dict(scenario=lab,n=len(s),mean_bp=round(s.mean(),2),
                t=round(s.mean()/s.std()*np.sqrt(len(s)),2),
                sharpe=round(s.mean()/s.std()*np.sqrt(252),2),
                total_pct=round(s.sum()/100,1),
                IS=round(x[x['IS']]['bp'].mean(),2), OOS=round(x[~x['IS']]['bp'].mean(),2))

KI,KO = 2,42
print("="*110); print(f"EXECUTION SCENARIOS — long bar{KI}->bar{KO} after reopen, ex-Sunday, 4 years, 831 sessions"); print("="*110)
rows=[
 st(run(KI,KO,'cross','cross'),                'A. market in/out, Dukascopy spread + $0.10 slip (baseline)'),
 st(run(KI,KO,'cross','cross',extra=0.20),     'B. market in/out, +$0.20 worse spread (retail CFD)'),
 st(run(KI,KO,'passive','cross'),              'C. LIMIT entry, market exit'),
 st(run(KI,KO,'passive','passive'),            'D. LIMIT entry + LIMIT exit (patient execution)'),
 st(run(KI,KO,'mid','mid'),                    'E. theoretical mid-to-mid (upper bound, not achievable)'),
]
print(pd.DataFrame(rows).to_string(index=False))
print("\nNOTE: 'passive' assumes the limit order fills. In a 4h drift window a resting order")
print("      near the touch fills most of the time, but unfilled sessions are exactly the ones")
print("      that ran away in your favour -> real-world result sits between C and A.")

print("\n"+"="*110); print("ADVERSE-SELECTION CHECK: how often would a passive buy limit at bar-open price actually fill?"); print("="*110)
# resting buy limit at the bar-KI open price, valid for the next 6 bars
lim = O[KI]
filled = pd.Series(False, index=O.index)
for k in range(KI, KI+7):
    if k in L.columns: filled |= (L[k]<=lim)
f = filled.reindex(run(KI,KO,'cross','cross').index)
base = run(KI,KO,'cross','cross')
print(f"fill rate within 6 bars: {f.mean()*100:.1f}%")
print(f"mean bp | filled: {base['bp'][f].mean():+.2f}   unfilled: {base['bp'][~f].mean():+.2f}")
print("-> if unfilled sessions are the strong ones, passive entry loses the best trades.")
