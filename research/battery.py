import sys; sys.path.insert(0,'research')
import rdata, engine, pandas as pd, numpy as np
pd.set_option('display.width',250); pd.set_option('display.max_rows',300)

df = rdata.build()
gapm = df.index.to_series().diff().dt.total_seconds()/60
df['reopen']=gapm>10; df.loc[df.index[0],'reopen']=True
df['sess']=df['reopen'].cumsum(); df['k']=df.groupby('sess').cumcount()
IS = df[df.index<=rdata.IS_END].copy()
c,h,l,o,a = IS['close'],IS['high'],IS['low'],IS['open'],IS['atr14']
hour, tod = IS['hour'], IS['tod']

S = {}
# ---------- 1. opening-range breakout, several windows ----------
def orb(start_min, or_bars, hrs_valid, name):
    d = IS.copy()
    inwin = d['tod']>=start_min
    day = d['session_day']
    # OR = high/low of the or_bars bars starting at start_min
    orh = pd.Series(np.nan, index=d.index); orl = pd.Series(np.nan, index=d.index)
    grp = d.groupby('session_day')
    for _, g in grp:
        w = g[(g['tod']>=start_min)&(g['tod']<start_min+5*or_bars)]
        if len(w)<or_bars: continue
        hi,lo = w['high'].max(), w['low'].min()
        after = g[(g['tod']>=start_min+5*or_bars)&(g['tod']<start_min+5*or_bars+60*hrs_valid)]
        orh.loc[after.index]=hi; orl.loc[after.index]=lo
    sig = pd.Series(0,index=d.index)
    sig[(d['close']>orh)&(d['close'].shift(1)<=orh)] = 1
    sig[(d['close']<orl)&(d['close'].shift(1)>=orl)] = -1
    S[name]=sig
for (sm,ob,hv,nm) in [(12*60,6,4,'ORB nyopen12:00 30m'),(13*60+30,6,4,'ORB nydata13:30 30m'),
                      (7*60,6,5,'ORB london07:00 30m'),(8*60,12,5,'ORB london08:00 60m')]:
    orb(sm,ob,hv,nm)

# ---------- 2. asia-range breakout into london ----------
d=IS
asia = d[(d['hour']>=0)&(d['hour']<6)].groupby('session_day')['high'].max()
asial= d[(d['hour']>=0)&(d['hour']<6)].groupby('session_day')['low'].min()
ah = d['session_day'].map(asia); al = d['session_day'].map(asial)
valid = (d['hour']>=6)&(d['hour']<14)
sig=pd.Series(0,index=d.index)
sig[valid&(c>ah)&(c.shift(1)<=ah)]=1; sig[valid&(c<al)&(c.shift(1)>=al)]=-1
S['asia range brk -> london']=sig

# ---------- 3. momentum ignition ----------
for k in (1.5,2.5):
    rng=(h-l); body=(c-o)
    strong = (rng>k*a)&(body.abs()>0.6*rng)
    sig=pd.Series(0,index=d.index); sig[strong&(body>0)]=1; sig[strong&(body<0)]=-1
    S[f'ignition rng>{k}ATR']=sig

# ---------- 4. mean reversion on extreme move ----------
for k in (2.0,3.0):
    m6 = c-c.shift(6)
    sig=pd.Series(0,index=d.index); sig[m6>k*a]=-1; sig[m6<-k*a]=1
    S[f'fade 30m move>{k}ATR']=sig

# ---------- 5. trend pullback ----------
e20,e200 = c.ewm(span=20).mean(), c.ewm(span=200).mean()
up = c>e200; dn=c<e200
pull_up = up & (l<=e20) & (c>e20) & (c>o)
pull_dn = dn & (h>=e20) & (c<e20) & (c<o)
sig=pd.Series(0,index=d.index); sig[pull_up]=1; sig[pull_dn]=-1
S['ema20 pullback in ema200 trend']=sig

# ---------- 6. volatility squeeze breakout ----------
rng20 = (h.rolling(20).max()-l.rolling(20).min())
squeeze = rng20 < rng20.rolling(200).quantile(0.25)
brk_u = squeeze.shift(1)&(c>h.rolling(20).max().shift(1))
brk_d = squeeze.shift(1)&(c<l.rolling(20).min().shift(1))
sig=pd.Series(0,index=d.index); sig[brk_u]=1; sig[brk_d]=-1
S['squeeze breakout']=sig

# ---------- 7. overnight drift, structured ----------
sig=pd.Series(0,index=d.index)
ent = (d['k']==3)&(d.index.dayofweek!=6)
sig[ent]=1
S['asia-open long (skip Sun)']=sig

res=[]
for nm,sig in S.items():
    for sl,tp,mb in [(1.5,3.0,72),(2.0,4.0,72),(1.5,None,48)]:
        tr = engine.run(IS, sig, sl_atr=sl, tp_atr=tp, max_bars=mb, max_per_day=2)
        st = engine.stats(tr, f"{nm} | sl{sl} tp{tp} mb{mb}")
        res.append(st)
r=pd.DataFrame(res)
r=r[r['n']>60].sort_values('t',ascending=False)
print(r.to_string(index=False))
