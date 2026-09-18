import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',400)
df = rdata.build(); df['year']=df.index.year
df = S.build_sessions(df)
st = S.session_table(df); P = S.path(df)
O, SP = P['open'], P['spread']
SLIP=0.10

K_IN, HOLD = 3, 36
entry, exitp = O[K_IN], O[K_IN+HOLD]
cost = SP[K_IN]/2 + SP[K_IN+HOLD]/2 + SLIP
st['gross'] = exitp-entry
st['net']   = st['gross']-cost
st['netbp'] = st['net']/entry*1e4
st['cost']  = cost
st = st.dropna(subset=['netbp'])
IS = st[st['t0']<=pd.Timestamp(rdata.IS_END,tz='UTC')]
print(f"IS sessions {len(IS)}   OOS {len(st)-len(IS)}")
print(f"IS base: mean netbp {IS['netbp'].mean():.2f}  t={IS['netbp'].mean()/IS['netbp'].std()*np.sqrt(len(IS)):.2f}  sum%={IS['netbp'].sum()/100:.1f}")

def buckets(name, x, n=5, data=IS):
    v = data[x] if isinstance(x,str) else x.reindex(data.index)
    q = pd.qcut(v, n, duplicates='drop')
    r = data.groupby(q, observed=True)['netbp'].agg(['size','mean','sum'])
    r['t'] = data.groupby(q, observed=True)['netbp'].apply(lambda s: s.mean()/s.std()*np.sqrt(len(s)))
    r['sum%'] = r['sum']/100
    print(f"\n--- {name} ---"); print(r.round(2).to_string())

for f in ['prev_ret','prev_ny','prev_clspos','gap','mom5d','mom20d','mom60d','vol20','vol_z','atr_pct','prev_range']:
    buckets(f, f)

print("\n--- dow (0=Mon) ---")
r = IS.groupby('dow')['netbp'].agg(['size','mean','sum'])
r['t']=IS.groupby('dow')['netbp'].apply(lambda s: s.mean()/s.std()*np.sqrt(len(s)))
print(r.round(2).to_string())
print("\n--- above_ma20 / ma50 ---")
for f in ['above_ma20','above_ma50']:
    r=IS.groupby(f)['netbp'].agg(['size','mean','sum']); r['t']=IS.groupby(f)['netbp'].apply(lambda s:s.mean()/s.std()*np.sqrt(len(s)))
    print(f); print(r.round(2).to_string())
