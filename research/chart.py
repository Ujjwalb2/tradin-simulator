import sys; sys.path.insert(0,'src'); sys.path.insert(0,'research')
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, pandas as pd, numpy as np, rdata, aod, sess as S
df = rdata.build(); p = aod.portfolio(df)
d = S.build_sessions(df); sc = d.groupby('sess')['close'].last()
t0 = d.groupby('sess').apply(lambda g: g.index[0])
bh = pd.Series((np.log(sc/sc.shift(1))*100).values, index=t0.values).dropna()
eq = p['bp'].cumsum()/100; ddv = eq-eq.cummax()
IS_END = pd.Timestamp(rdata.IS_END, tz='UTC')

fig, ax = plt.subplots(3,1, figsize=(12,11), height_ratios=[2.2,1,1.2], sharex=False)
ax[0].plot(eq.index, eq.values, lw=1.8, color='#1f77b4', label='AOD (unlevered, 1x notional)')
ax[0].plot(bh.index, bh.cumsum().values, lw=1.2, color='#999', label='Buy & hold gold')
ax[0].axvline(IS_END, color='crimson', ls='--', lw=1.2)
ax[0].text(IS_END, ax[0].get_ylim()[1]*0.92, ' OOS starts', color='crimson', fontsize=9)
ax[0].set_ylabel('cumulative %'); ax[0].legend(loc='upper left', fontsize=9)
ax[0].set_title('AOD — Asia-Open Drift, XAUUSD 5m  |  long only, no stop, time exit', fontweight='bold')
ax[0].grid(alpha=.25)

ax[1].fill_between(ddv.index, ddv.values, 0, color='crimson', alpha=.45)
ax[1].axvline(IS_END, color='crimson', ls='--', lw=1.2)
ax[1].set_ylabel('drawdown %'); ax[1].grid(alpha=.25)

yr = p.groupby('year')['bp'].sum()/100
cols = ['#2ca02c' if v>0 else '#d62728' for v in yr.values]
ax[2].bar(yr.index.astype(str), yr.values, color=cols)
ax[2].set_ylabel('% per year'); ax[2].grid(alpha=.25, axis='y')
for i,v in enumerate(yr.values): ax[2].text(i, v, f'{v:+.1f}%', ha='center',
    va='bottom' if v>0 else 'top', fontsize=9)
ax[2].set_title('return by year — note: all of it is 2025-2026', fontsize=10)
plt.tight_layout(); plt.savefig('out/research/aod_equity.png', dpi=130)
print('saved out/research/aod_equity.png')
print(f"AOD total {eq.iloc[-1]:.1f}%  maxDD {ddv.min():.1f}%   B&H total {bh.sum():.1f}%")
