import sys; sys.path.insert(0,'src'); sys.path.insert(0,'research')
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt, pandas as pd, numpy as np, rdata, sess as S
df = rdata.build(); d = S.build_sessions(df)
P=S.path(d); O,SP=P['open'],P['spread']
t0=d.groupby('sess').apply(lambda g:g.index[0]); dow=t0.dt.dayofweek
def leg(ki,ko):
    e=O[ki]+SP[ki]/2+0.10; x=O[ko]-SP[ko]/2-0.10; return (x-e)/e*1e4
aod=pd.concat([leg(ki,ko) for ki in (2,3,4) for ko in (36,42,48)],axis=1).mean(axis=1)
sh =pd.concat([leg(ki,ki+24) for ki in (14,16,18)],axis=1).mean(axis=1)
ts=t0.reindex(aod.index)
m=(dow!=6)
aod=aod[m].dropna(); sh=sh[m].dropna()
ia=ts.reindex(aod.index); is_=ts.reindex(sh.index)
DES=pd.Timestamp('2022-09-01',tz='UTC'); FWD=pd.Timestamp('2025-07-01',tz='UTC')

# gross drift & cost per year in the window, for panel 3
a=df[(df['hour']>=22)|(df['hour']<=1)].copy(); a['year']=a.index.year
gy=a.groupby('year').agg(price=('close','mean'),spread=('spread','mean'))
gy['cost_bp']=(gy['spread']+0.20)/gy['price']*1e4
sess_n=a.groupby('year')['session_day'].nunique()
gy['drift_bp']=a.groupby('year')['ret'].sum()*1e4/sess_n

fig,ax=plt.subplots(3,1,figsize=(12.5,12), height_ratios=[2.3,1.5,1.5])
ax[0].plot(ia.values, aod.cumsum().values/100, lw=1.8, color='#1f77b4', label='AOD 3.5h hold')
ax[0].plot(is_.values, sh.cumsum().values/100, lw=1.4, color='#ff7f0e', label='2-hour variant')
ax[0].axvspan(DES,FWD,color='gold',alpha=.18)
ax[0].axvspan(FWD,ia.max(),color='limegreen',alpha=.14)
ax[0].axhline(0,color='k',lw=.8)
ax[0].text(pd.Timestamp('2017-06-01',tz='UTC'),-30,'HOLDOUT 2015-2022\n(never used in design)',
           fontsize=10,color='crimson',fontweight='bold')
ax[0].text(DES,-30,' designed\n here',fontsize=9,color='#8a6d00')
ax[0].set_ylabel('cumulative %'); ax[0].legend(loc='upper left',fontsize=9); ax[0].grid(alpha=.25)
ax[0].set_title('Both strategies collapse on the 7.6-year holdout  —  XAUUSD 5m, cost-realistic',
                fontweight='bold')

yrs=sorted(set(ia.dt.year))
byy=aod.groupby(ia.dt.year).sum()/100
ax[1].bar([str(y) for y in byy.index], byy.values,
          color=['#d62728' if v<0 else '#2ca02c' for v in byy.values])
ax[1].axhline(0,color='k',lw=.8); ax[1].set_ylabel('AOD % per year'); ax[1].grid(alpha=.25,axis='y')
ax[1].set_title('negative in 8 of the 12 years',fontsize=10)

x=np.arange(len(gy))
ax[2].bar(x-0.2, gy['drift_bp'].values, .4, label='gross drift per session (bp)', color='#2ca02c')
ax[2].bar(x+0.2, gy['cost_bp'].values, .4, label='round-trip cost (bp)', color='#d62728')
ax[2].set_xticks(x); ax[2].set_xticklabels(gy.index.astype(str)); ax[2].legend(fontsize=9)
ax[2].grid(alpha=.25,axis='y'); ax[2].set_ylabel('basis points')
ax[2].set_title('the whole story: cost exceeded the drift in 7 of 8 early years, and only recently flipped',
                fontsize=10)
plt.tight_layout(); plt.savefig('out/research/aod_11y.png',dpi=130)
print("saved. AOD total %.1f%%  2h total %.1f%%"%(aod.sum()/100, sh.sum()/100))
