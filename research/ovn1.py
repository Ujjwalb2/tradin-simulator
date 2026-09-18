import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',400)
df = rdata.build(); df['year']=df.index.year
gapm = df.index.to_series().diff().dt.total_seconds()/60
df['reopen'] = gapm > 10

# label each session: bars indexed from the reopen bar (=0)
sess = df['reopen'].cumsum()
df['sess'] = sess
df['k'] = df.groupby('sess').cumcount()      # bars since reopen
n = df.groupby('sess').size()
df['sess_len'] = df['sess'].map(n)
print("sessions:", df['sess'].nunique(), " median len:", n.median(), " len quantiles:", n.quantile([.01,.05,.5,.95]).values)

# keep normal-length sessions only (a full trading day ~ 288 bars)
good = df[df['sess_len']>=200].copy()
print("kept sessions:", good['sess'].nunique())
print("\nreopen clock-time distribution:"); print(good.loc[good['k']==0].index.hour.value_counts().sort_index().to_string())

# ---- ENTRY/EXIT GRID: enter at bar k_in (open), exit at bar k_out (open) ------
o = good.pivot_table(index='sess', columns='k', values='open', aggfunc='first')
sp = good.pivot_table(index='sess', columns='k', values='spread', aggfunc='first')
yr = good.groupby('sess')['year'].first()
ts0 = good[good['k']==0].set_index('sess').index.to_series()
first_ts = good.groupby('sess').apply(lambda g: g.index[0])
is_mask = first_ts <= pd.Timestamp(rdata.IS_END, tz='UTC')

SLIP = 0.10
rows=[]
for k_in in [1,2,3,6,12,18,24,36]:
    for hold in [6,12,18,24,30,36,48,60]:
        k_out = k_in+hold
        if k_out not in o.columns or k_in not in o.columns: continue
        entry, exitp = o[k_in], o[k_out]
        cost = sp[k_in]/2 + sp[k_out]/2 + SLIP     # cross half-spread each side
        pnl = (exitp-entry) - cost                 # long, $ per unit
        pnl = pnl.dropna()
        if len(pnl)<600: continue
        # normalise to % of price so eras are comparable
        pct = (pnl/entry.reindex(pnl.index))*100
        m=pnl.mean(); t=pct.mean()/pct.std()*np.sqrt(len(pct))
        rows.append(dict(k_in=k_in, hold=hold, n=len(pnl),
                         gross=((exitp-entry).reindex(pnl.index)).mean(),
                         cost=cost.reindex(pnl.index).mean(),
                         net_usd=m, net_pct=pct.mean()*100, t=t,
                         win=(pnl>0).mean()*100,
                         is_pct=pct[is_mask.reindex(pct.index).fillna(False)].sum(),
                         oos_pct=pct[~is_mask.reindex(pct.index).fillna(False)].sum()))
r = pd.DataFrame(rows).sort_values('t',ascending=False)
print("\n"+"="*110)
print("LONG THE ASIA-OPEN WINDOW: enter k_in bars after reopen, hold H bars. NET of spread+slippage.")
print("net_pct = mean per-trade return in bp;  is/oos_pct = summed % return in each period")
print("="*110)
print(r.head(30).round(3).to_string(index=False))
