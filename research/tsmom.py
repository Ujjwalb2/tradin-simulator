import sys; sys.path.insert(0,'research')
import rdata, sess as S, pandas as pd, numpy as np
pd.set_option('display.width',260)
df=rdata.build(); df=S.build_sessions(df)
sc=df.groupby('sess')['close'].last(); so=df.groupby('sess')['open'].first()
t0=df.groupby('sess').apply(lambda g:g.index[0])
sp=df.groupby('sess')['spread'].mean()
d=pd.DataFrame({'c':sc,'o':so,'t0':t0,'sp':sp}); d['IS']=d['t0']<=pd.Timestamp(rdata.IS_END,tz='UTC')
d['ret']=np.log(d['c']/d['c'].shift(1))
print("="*100); print("TIME-SERIES MOMENTUM on gold daily (signal at close, hold N sessions)"); print("="*100)
res=[]
for lb in (5,10,20,40,60,120):
    sig=np.sign(np.log(d['c']/d['c'].shift(lb))).shift(1)
    for hd in (1,5,10,20):
        fwd=np.log(d['c'].shift(-hd)/d['c'])
        pnl=(sig*fwd)/hd                       # per-session
        v=pd.DataFrame({'p':pnl,'IS':d['IS']}).dropna()
        i,o=v[v['IS']]['p'],v[~v['IS']]['p']
        res.append(dict(lb=lb,hold=hd,
            is_sh=i.mean()/i.std()*np.sqrt(252), is_sum=i.sum()*100*hd/hd,
            oos_sh=o.mean()/o.std()*np.sqrt(252), oos_sum=o.sum()*100,
            longfrac=(sig>0).mean()))
print(pd.DataFrame(res).round(3).to_string(index=False))
print("\nNOTE: gross of costs; daily rebalance cost ~2.3bp/turn.")
print("\nBuy&hold reference: IS sharpe %.2f  OOS sharpe %.2f"%(
    d[d['IS']]['ret'].mean()/d[d['IS']]['ret'].std()*np.sqrt(252),
    d[~d['IS']]['ret'].mean()/d[~d['IS']]['ret'].std()*np.sqrt(252)))
