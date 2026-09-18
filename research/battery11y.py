import sys; sys.path.insert(0,'research')
import rdata, engine, pandas as pd, numpy as np
pd.set_option('display.width',260); pd.set_option('display.max_rows',300)
df = rdata.build()
HOLD_END=pd.Timestamp('2022-08-31',tz='UTC')
print(f"{len(df):,} bars {df.index[0]:%Y-%m-%d}..{df.index[-1]:%Y-%m-%d}")
c,h,l,o,a = df['close'],df['high'],df['low'],df['open'],df['atr14']
S={}
def orb(sm,ob,hv,nm):
    orh=pd.Series(np.nan,index=df.index); orl=pd.Series(np.nan,index=df.index)
    for _,g in df.groupby('session_day'):
        w=g[(g['tod']>=sm)&(g['tod']<sm+5*ob)]
        if len(w)<ob: continue
        after=g[(g['tod']>=sm+5*ob)&(g['tod']<sm+5*ob+60*hv)]
        orh.loc[after.index]=w['high'].max(); orl.loc[after.index]=w['low'].min()
    s=pd.Series(0,index=df.index)
    s[(c>orh)&(c.shift(1)<=orh)]=1; s[(c<orl)&(c.shift(1)>=orl)]=-1
    S[nm]=s
orb(12*60,6,4,'ORB 12:00'); orb(13*60+30,6,4,'ORB 13:30'); orb(7*60,6,5,'ORB 07:00')
asia=df[(df['hour']>=0)&(df['hour']<6)].groupby('session_day')
ah=df['session_day'].map(asia['high'].max()); al=df['session_day'].map(asia['low'].min())
v=(df['hour']>=6)&(df['hour']<14); s=pd.Series(0,index=df.index)
s[v&(c>ah)&(c.shift(1)<=ah)]=1; s[v&(c<al)&(c.shift(1)>=al)]=-1; S['asia brk->london']=s
for k in (1.5,2.5):
    rng=h-l; body=c-o; strong=(rng>k*a)&(body.abs()>0.6*rng)
    s=pd.Series(0,index=df.index); s[strong&(body>0)]=1; s[strong&(body<0)]=-1
    S[f'ignition {k}ATR']=s
for k in (2.0,3.0):
    m6=c-c.shift(6); s=pd.Series(0,index=df.index); s[m6>k*a]=-1; s[m6<-k*a]=1
    S[f'fade 30m {k}ATR']=s
e20,e200=c.ewm(span=20).mean(),c.ewm(span=200).mean()
s=pd.Series(0,index=df.index)
s[(c>e200)&(l<=e20)&(c>e20)&(c>o)]=1; s[(c<e200)&(h>=e20)&(c<e20)&(c<o)]=-1
S['ema20 pullback']=s
r20=h.rolling(20).max()-l.rolling(20).min(); sq=r20<r20.rolling(200).quantile(.25)
s=pd.Series(0,index=df.index)
s[sq.shift(1)&(c>h.rolling(20).max().shift(1))]=1
s[sq.shift(1)&(c<l.rolling(20).min().shift(1))]=-1; S['squeeze brk']=s

print("\n"+"="*112)
print("BATTERY on 11.7 YEARS — holds capped at 1h (12 bars) and 2h (24 bars)")
print("held = max_bars; tp/sl in ATR. avg_usd is the honest number: it must beat $0")
print("="*112)
res=[]
for nm,sig in S.items():
    for mb,sl,tp in [(12,1.5,2.0),(24,1.5,3.0),(24,2.0,None)]:
        tr=engine.run(df,sig,sl_atr=sl,tp_atr=tp,max_bars=mb,max_per_day=3)
        if len(tr)<200: continue
        st=engine.stats(tr,f"{nm} | hold<={mb*5}m sl{sl} tp{tp}")
        tr['era']=np.where(pd.to_datetime(tr['t_in'])<=HOLD_END,'holdout','recent')
        st['usd_holdout']=round(tr[tr['era']=='holdout']['pnl'].mean(),3)
        st['usd_recent']=round(tr[tr['era']=='recent']['pnl'].mean(),3)
        res.append(st)
r=pd.DataFrame(res).sort_values('avg_usd',ascending=False)
print(r[['label','n','win','avgR','t','pf','avg_usd','usd_holdout','usd_recent']].to_string(index=False))
print(f"\nstrategies with avg_usd > 0 over 11.7y: {(r['avg_usd']>0).sum()} / {len(r)}")
print(f"strategies profitable in BOTH eras       : {((r['usd_holdout']>0)&(r['usd_recent']>0)).sum()} / {len(r)}")
