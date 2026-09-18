import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',280); pd.set_option('display.max_rows',300)
df = rdata.build(); df['year']=df.index.year
a = df[(df['hour']>=22)|(df['hour']<=1)]
print("="*105)
print("WHY THE HOLDOUT FAILS: cost vs drift, per year, in the Asia-open window")
print("="*105)
g = a.groupby('year').agg(price=('close','mean'), spread_usd=('spread','mean'),
                          atr_usd=('atr14','mean'), bars=('ret','size'))
g['cost_rt_usd'] = g['spread_usd']+0.20                 # round trip: 1 full spread + 2x slip
g['cost_bp']     = g['cost_rt_usd']/g['price']*1e4
g['drift_yr_pct']= a.groupby('year')['ret'].sum()*100
g['sessions']    = a.groupby('year')['session_day'].nunique()
g['drift_bp_per_sess'] = g['drift_yr_pct']/g['sessions']*100
g['edge_ratio']  = g['drift_bp_per_sess']/g['cost_bp']
print(g.round(2).to_string())
print("\nedge_ratio > 1 means the window's gross drift covers the round-trip cost.")
print("\n"+"="*105)
print("SPREAD SANITY: is the early-era spread plausible or a data artifact?")
print("="*105)
q = a.groupby('year')['spread'].describe(percentiles=[.1,.5,.9])[['count','10%','50%','90%','max']]
q['as_bp_median'] = a.groupby('year').apply(lambda x:(x['spread']/x['close']).median()*1e4)
print(q.round(3).to_string())
print("\n"+"="*105); print("GOLD PRICE LEVEL vs COST IN BP (the structural story)"); print("="*105)
print((g[['price','spread_usd','cost_bp','drift_bp_per_sess','edge_ratio']]).round(2).to_string())
