import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',500)
df = rdata.build(); df['year']=df.index.year
df = S.build_sessions(df)
P=S.path(df); O,SP=P['open'],P['spread']
t0 = df.groupby('sess').apply(lambda g: g.index[0])
ISm = (t0<=pd.Timestamp(rdata.IS_END,tz='UTC'))
SLIP=0.10
maxk = O.columns.max()

rows=[]
for k_in in range(1, 265, 3):
    for hold in (12,24,36,48,72):
        k_out=k_in+hold
        if k_out>min(276,maxk): continue
        if k_in not in O.columns or k_out not in O.columns: continue
        e,x = O[k_in], O[k_out]
        cost = SP[k_in]/2+SP[k_out]/2+SLIP
        bp = ((x-e)-cost)/e*1e4                    # long, net
        bp = bp.dropna()
        if len(bp)<800: continue
        i,oo = bp[ISm.reindex(bp.index).fillna(False)], bp[~ISm.reindex(bp.index).fillna(False)]
        if len(i)<500 or len(oo)<200: continue
        rows.append(dict(k_in=k_in, hold=hold,
            is_mean=i.mean(), is_t=i.mean()/i.std()*np.sqrt(len(i)), is_sum=i.sum()/100,
            oos_mean=oo.mean(), oos_t=oo.mean()/oo.std()*np.sqrt(len(oo)), oos_sum=oo.sum()/100))
r=pd.DataFrame(rows)
r['agree'] = np.sign(r['is_mean'])==np.sign(r['oos_mean'])
print("="*110)
print("WINDOW SCAN: long from bar k_in to k_in+hold after daily reopen, net of costs.")
print("Sorted by IS t-stat. 'agree' = OOS has same sign as IS (the honest check).")
print("="*110)
print("--- TOP 12 by IS t (long side) ---")
print(r.nlargest(12,'is_t').round(2).to_string(index=False))
print("\n--- BOTTOM 12 by IS t (i.e. best SHORT candidates) ---")
print(r.nsmallest(12,'is_t').round(2).to_string(index=False))
print(f"\nsign-agreement rate across all {len(r)} windows: {r['agree'].mean()*100:.0f}%")
print("\n--- how often does a strong IS window survive OOS? ---")
strong = r[r['is_t'].abs()>1.5]
print(f"windows with |IS t|>1.5: {len(strong)}, of which sign-agree in OOS: {strong['agree'].mean()*100:.0f}%")
