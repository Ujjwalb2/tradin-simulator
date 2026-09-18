import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np
pd.set_option('display.width',220); pd.set_option('display.max_rows',300)

df = rdata.build()
IS = df[df.index <= rdata.IS_END].copy()

print("="*90); print("1. VOLATILITY & COST BY UTC HOUR  (in-sample)"); print("="*90)
g = IS.groupby('hour').agg(
    bars=('ret','size'),
    absmove=('tr','mean'),
    spread=('spread','mean'),
    drift_bp=('ret', lambda s: s.mean()*1e4),
)
g['edge_needed'] = g['spread']+0.10
g['tr_per_cost'] = g['absmove']/g['edge_needed']
# t-stat on hourly drift
tt = IS.groupby('hour')['ret'].apply(lambda s: s.mean()/s.std()*np.sqrt(len(s)))
g['t_drift'] = tt
print(g.round(3).to_string())

print(); print("="*90); print("2. FORWARD 1-DAY DRIFT BY HOUR-OF-ENTRY (mean $ move over next 12 bars=1h)"); print("="*90)
fw = rdata.fwd_returns(IS, (12,24,48))
tmp = IS[['hour']].join(fw)
for k in (12,24,48):
    s = tmp.groupby('hour')[f'f{k}']
    res = pd.DataFrame({'mean':s.mean(),'t':s.mean()/s.std()*np.sqrt(s.count())})
    print(f'-- horizon {k} bars --'); print(res.round(3).T.to_string())

print(); print("="*90); print("3. RETURN AUTOCORRELATION (5m log ret, IS)"); print("="*90)
r = IS['ret'].dropna()
print(pd.Series({f'lag{k}': r.autocorr(k) for k in range(1,13)}).round(4).to_string())

print(); print("="*90); print("4. AUTOCORR BY SESSION (does gold trend or revert, by hour block?)"); print("="*90)
blocks = {'asia 00-06':range(0,7),'london 07-11':range(7,12),'ny_ovl 12-16':range(12,17),'ny_pm 17-21':range(17,22),'late 22-23':range(22,24)}
for name, hrs in blocks.items():
    sub = IS[IS['hour'].isin(hrs)]['ret'].dropna()
    print(f"{name:14s} n={len(sub):7d}  ac1={sub.autocorr(1):+.4f}  ac2={sub.autocorr(2):+.4f}  ac3={sub.autocorr(3):+.4f}  std={sub.std()*1e4:.1f}bp")

print(); print("="*90); print("5. DAY OF WEEK (IS)"); print("="*90)
g2 = IS.groupby('dow').agg(bars=('ret','size'), drift_bp=('ret',lambda s: s.mean()*1e4), tr=('tr','mean'))
g2['t'] = IS.groupby('dow')['ret'].apply(lambda s: s.mean()/s.std()*np.sqrt(len(s)))
print(g2.round(3).to_string())
