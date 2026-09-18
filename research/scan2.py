import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',500)
df = rdata.build(); df['year']=df.index.year
df = S.build_sessions(df)
P=S.path(df); O,SP=P['open'],P['spread']
t0=df.groupby('sess').apply(lambda g:g.index[0]); ISm=(t0<=pd.Timestamp(rdata.IS_END,tz='UTC'))
rows=[]
for k_in in range(1,265,3):
    for hold in (12,24,36,48,72):
        k_out=k_in+hold
        if k_out>276 or k_in not in O.columns or k_out not in O.columns: continue
        e,x=O[k_in],O[k_out]
        gross=((x-e)/e*1e4).dropna()                     # GROSS drift in bp
        hurdle=((SP[k_in]/2+SP[k_out]/2+0.10)/e*1e4).reindex(gross.index)
        if len(gross)<800: continue
        i,oo=gross[ISm.reindex(gross.index).fillna(False)],gross[~ISm.reindex(gross.index).fillna(False)]
        if len(i)<500 or len(oo)<200: continue
        rows.append(dict(k_in=k_in,hold=hold,hurdle=hurdle.mean(),
            is_g=i.mean(), is_t=i.mean()/i.std()*np.sqrt(len(i)),
            oos_g=oo.mean(), oos_t=oo.mean()/oo.std()*np.sqrt(len(oo))))
r=pd.DataFrame(rows)
r['net_is']=r['is_g']-r['hurdle']; r['net_oos']=r['oos_g']-r['hurdle']
print("="*105); print("GROSS drift scan (bp). A SHORT needs gross < -hurdle; a LONG needs gross > +hurdle."); print("="*105)
print("--- most positive GROSS drift, IS ---")
print(r.nlargest(10,'is_g').round(2).to_string(index=False))
print("\n--- most negative GROSS drift, IS (true short candidates) ---")
print(r.nsmallest(10,'is_g').round(2).to_string(index=False))
print(f"\nwindows where IS gross beats hurdle: {(r['net_is']>0).sum()}/{len(r)}")
print(f"windows where IS gross < -hurdle (shortable): {(r['is_g']+r['hurdle']<0).sum()}/{len(r)}")
