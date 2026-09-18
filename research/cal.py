import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',400)
df = rdata.build(); df['year']=df.index.year
df = S.build_sessions(df)
P=S.path(df); O,SP=P['open'],P['spread']; A=S.path(df,('atr14',))['atr14']
t0 = df.groupby('sess').apply(lambda g: g.index[0])
meta = pd.DataFrame({'t0':t0}); meta['dow']=t0.dt.dayofweek; meta['year']=t0.dt.year
meta['IS'] = t0<=pd.Timestamp(rdata.IS_END,tz='UTC')
# session-level vol context
sc = df.groupby('sess')['close'].last()
dret = np.log(sc/sc.shift(1))
meta['vol20'] = dret.rolling(20).std().shift(1)
meta['volq']  = meta['vol20'].rolling(250).rank(pct=True)
meta['dom']   = t0.dt.day
meta['turn']  = ((t0.dt.day>=26)|(t0.dt.day<=3)).astype(int)

K_IN, K_OUT = 1, 48
ent = O[K_IN]+SP[K_IN]/2+0.10
ex  = O[K_OUT]-SP[K_OUT]/2-0.10
meta['bp'] = (ex-ent)/ent*1e4
meta['atrbp'] = A[K_IN]/O[K_IN]*1e4
d = meta.dropna(subset=['bp'])
IS = d[d['IS']]

def show(name, key, data=IS):
    g=data.groupby(key)['bp']
    r=g.agg(['size','mean','sum']); r['t']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
    r['sum%']=r['sum']/100
    print(f"\n--- {name} ---"); print(r.round(2).to_string())

print("="*100); print("OVERNIGHT (asia-open window, bar1->bar48) NET bp — IS ONLY"); print("="*100)
print(f"ALL: n={len(IS)} mean={IS['bp'].mean():.2f}bp t={IS['bp'].mean()/IS['bp'].std()*np.sqrt(len(IS)):.2f} sum={IS['bp'].sum()/100:.1f}%")
show("day of week of reopen (6=Sun night)", 'dow')
show("turn of month", 'turn')
show("vol quintile (prior 20d realised, pct-rank)", pd.qcut(IS['volq'],5,duplicates='drop'))
show("ATR at entry (bp of price)", pd.qcut(IS['atrbp'],5,duplicates='drop'))

print("\n"+"="*100); print("EX-SUNDAY, by year, IS and OOS"); print("="*100)
ex_sun = d[d['dow']!=6]
g=ex_sun.groupby('year')['bp']; r=g.agg(['size','mean','sum']); r['sum%']=r['sum']/100
r['t']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
print(r.round(2).to_string())
for lab,sub in [('IS',ex_sun[ex_sun['IS']]),('OOS',ex_sun[~ex_sun['IS']])]:
    print(f"{lab}: n={len(sub)} mean={sub['bp'].mean():.2f} t={sub['bp'].mean()/sub['bp'].std()*np.sqrt(len(sub)):.2f} sum={sub['bp'].sum()/100:.1f}%")

print("\n"+"="*100); print("SUNDAY SESSION ALONE (is the short side real?) by year"); print("="*100)
sun=d[d['dow']==6]; g=sun.groupby('year')['bp']; r=g.agg(['size','mean','sum']); r['sum%']=r['sum']/100
r['t']=g.apply(lambda s:s.mean()/s.std()*np.sqrt(len(s))); print(r.round(2).to_string())
for lab,sub in [('IS',sun[sun['IS']]),('OOS',sun[~sun['IS']])]:
    print(f"{lab}: n={len(sub)} mean={sub['bp'].mean():.2f} t={sub['bp'].mean()/sub['bp'].std()*np.sqrt(len(sub)):.2f} sum={sub['bp'].sum()/100:.1f}%")
