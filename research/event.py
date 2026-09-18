import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',300)
df = rdata.build(); df['year']=df.index.year
IS = df[df.index<=rdata.IS_END]

print("="*100); print("EVENT STUDY: large-range bar at US data time (12:30/13:30/14:00 UTC) -> follow-through?"); print("="*100)
for slot in (750, 810, 840):     # 12:30, 13:30, 14:00 UTC in minutes
    d = df[df['tod']==slot].copy()
    d['rngx'] = (d['high']-d['low'])/d['atr14']
    d['dir']  = np.sign(d['close']-d['open'])
    # forward moves from the NEXT bar open
    nxt = df['open'].shift(-1).reindex(d.index)
    for hh in (6,12,36):
        d[f'f{hh}'] = (df['close'].shift(-hh).reindex(d.index) - nxt)
    d = d.dropna()
    ISd = d[d.index<=rdata.IS_END]
    big = ISd[ISd['rngx']>2.0]
    print(f"\n-- slot {slot//60:02d}:{slot%60:02d} UTC, spike bars (range>2xATR): n={len(big)} of {len(ISd)} --")
    for hh in (6,12,36):
        cont = (big['dir']*big[f'f{hh}'])       # continuation P&L in $
        rev  = -cont
        print(f"   h={hh:2d}  continuation mean ${cont.mean():+.3f} t={cont.mean()/cont.std()*np.sqrt(len(cont)):+.2f}"
              f"   | reversal mean ${rev.mean():+.3f}   (cost ~$0.6)")

print("\n"+"="*100); print("TURN OF MONTH: full-day return by day-of-month position (IS, log-ret % summed)"); print("="*100)
d2 = df.copy(); d2['dom']=d2.index.day
sd = d2.groupby(d2.index.tz_localize(None).to_period('D')).agg(ret=('ret','sum'))
sd = sd[sd['ret']!=0].copy()
sd['ts'] = sd.index.to_timestamp()
sd['IS'] = sd['ts']<=pd.Timestamp(rdata.IS_END)
mo = sd['ts'].dt.to_period('M')
sd['bdom']=sd.groupby(mo).cumcount()+1
sd['bdom_rev']=sd.groupby(mo)['bdom'].transform('max')-sd['bdom']
g=sd[sd['IS']].groupby('bdom')['ret']
r=g.agg(['size','mean','sum'])*100; r['size']=g.size()
r['t']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
print("first 10 business days of month (IS):"); print(r.head(10).round(2).to_string())
g2=sd[sd['IS']].groupby('bdom_rev')['ret']; r2=g2.agg(['size','mean','sum'])*100; r2['size']=g2.size()
r2['t']=g2.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
print("\nlast 5 business days (bdom_rev 0 = last day) (IS):"); print(r2.head(5).round(2).to_string())
