import sys; sys.path.insert(0,'research')
import rdata, pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',400)
df = rdata.build(); df['year']=df.index.year

print("="*100); print("A. WHERE IS THE DAILY BREAK? bars present per 5m slot, 20:00-00:00 UTC"); print("="*100)
w = df[(df['hour']>=20)|(df['hour']<=1)]
cnt = w.groupby(['hour','minute']).agg(n=('ret','size'), vol=('volume','mean'), spr=('spread','mean'), ret=('ret','sum'))
cnt['ret']*=100
print(cnt.round(3).to_string())
