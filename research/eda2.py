import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',400)

df = rdata.build()
df['year'] = df.index.year

print("="*100)
print("TIME-OF-DAY RETURN DECOMPOSITION — total $ move captured by being long only in hour H")
print("Full sample shown for structure; IS/OOS split marked. NO costs here, gross drift only.")
print("="*100)
df['dmove'] = df['close'].diff()          # $ change attributed to the bar
piv = df.pivot_table(index='hour', columns='year', values='dmove', aggfunc='sum')
piv['TOTAL'] = piv.sum(axis=1)
print(piv.round(0).to_string())
print("\ncolumn sums (= total $ move of gold that year):")
print(piv.sum().round(0).to_string())

print("\n"+"="*100)
print("SAME, in log-return terms (scale-free) — this is the honest version")
print("="*100)
piv2 = df.pivot_table(index='hour', columns='year', values='ret', aggfunc='sum')
piv2['TOTAL'] = piv2.sum(axis=1)
piv2['IS'] = df[df.index<=rdata.IS_END].groupby('hour')['ret'].sum()
piv2['OOS'] = df[df.index>=rdata.OOS_START].groupby('hour')['ret'].sum()
print((piv2*100).round(2).to_string())

print("\n"+"="*100)
print("HOUR BLOCKS: log-return sum per year  (is the overnight drift stable?)")
print("="*100)
def blk(h):
    if 22<=h or h<=1: return 'A 22-01 late/asia-open'
    if 2<=h<=6:        return 'B 02-06 asia'
    if 7<=h<=11:       return 'C 07-11 london'
    if 12<=h<=16:      return 'D 12-16 ny overlap'
    return                'E 17-21 ny pm'
df['blk'] = df['hour'].map(blk)
pb = df.pivot_table(index='blk', columns='year', values='ret', aggfunc='sum')*100
pb['TOTAL'] = pb.sum(axis=1)
pb['bars'] = df.groupby('blk').size()
print(pb.round(2).to_string())
print("\nGold total log return per year (%):")
print((df.groupby('year')['ret'].sum()*100).round(2).to_string())
