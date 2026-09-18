import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',400)
df = rdata.build(); df['year']=df.index.year

# ---- identify session breaks -------------------------------------------------
gap = df.index.to_series().diff()
df['gap_min'] = gap.dt.total_seconds()/60
df['reopen'] = df['gap_min'] > 10          # first bar after any halt
print("break-size histogram (minutes), gaps > 5:")
print(df.loc[df['gap_min']>5,'gap_min'].value_counts().head(12).to_string())
print("\nreopen bars:", df['reopen'].sum())
print("\nreopen bar hour distribution:")
print(df.loc[df['reopen'],'hour'].value_counts().sort_index().to_string())

# how much return lives in reopen (gap) bars vs continuous bars
print("\n"+"="*100)
print("GAP vs CONTINUOUS return, per year (log-ret %, whole day)")
print("="*100)
t = df.pivot_table(index='reopen', columns='year', values='ret', aggfunc='sum')*100
t['TOTAL']=t.sum(axis=1); print(t.round(2).to_string())

# ---- redo block decomposition EXCLUDING reopen bars ---------------------------
def blk(h):
    if 22<=h or h<=1: return 'A 22-01 asia-open'
    if 2<=h<=6:        return 'B 02-06 asia'
    if 7<=h<=11:       return 'C 07-11 london'
    if 12<=h<=16:      return 'D 12-16 ny overlap'
    return                'E 17-21 ny pm'
df['blk']=df['hour'].map(blk)
cont = df[~df['reopen']]
print("\n"+"="*100)
print("BLOCK DECOMPOSITION — CONTINUOUS BARS ONLY (gap bars removed). log-ret % per year")
print("="*100)
pb = cont.pivot_table(index='blk', columns='year', values='ret', aggfunc='sum')*100
pb['TOTAL']=pb.sum(axis=1); pb['bars']=cont.groupby('blk').size()
pb['IS']  = cont[cont.index<=rdata.IS_END].groupby('blk')['ret'].sum()*100
pb['OOS'] = cont[cont.index>=rdata.OOS_START].groupby('blk')['ret'].sum()*100
print(pb.round(2).to_string())

print("\n"+"="*100)
print("HOUR-LEVEL, CONTINUOUS BARS ONLY, log-ret % per year")
print("="*100)
ph = cont.pivot_table(index='hour', columns='year', values='ret', aggfunc='sum')*100
ph['TOTAL']=ph.sum(axis=1)
ph['pos_yrs']=(ph[[2023,2024,2025,2026]]>0).sum(axis=1)
print(ph.round(2).to_string())
