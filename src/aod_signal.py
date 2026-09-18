"""Live daily signal for AOD. Prints today's entry/exit times and the state of the clock.

    ./.venv/bin/python src/aod_signal.py            # next session's plan
    ./.venv/bin/python src/aod_signal.py --last 10  # audit the last 10 sessions
"""
import argparse, sys, os
sys.path.insert(0, os.path.dirname(__file__))
import pandas as pd, numpy as np, aod

IST = "Asia/Kolkata"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/processed/XAUUSD_5m.parquet")
    ap.add_argument("--last", type=int, default=0)
    a = ap.parse_args()

    df = pd.read_parquet(a.data).sort_index()
    d = aod.mark_sessions(df)
    last_sess = d["sess"].max()
    g = d[d["sess"] == last_sess]
    t0 = g.index[0]

    print(f"data ends        : {df.index[-1]}  ({df.index[-1].tz_convert(IST):%Y-%m-%d %H:%M} IST)")
    print(f"last reopen seen : {t0}  ({t0.tz_convert(IST):%Y-%m-%d %H:%M} IST)   bars so far: {len(g)}")
    print()
    if a.last:
        p = aod.portfolio(df).tail(a.last)
        print(f"last {a.last} sessions:")
        print(p[["bp", "pnl", "entry", "legs"]].round(3).to_string())
        print(f"\nsum {p['bp'].sum()/100:+.2f}%   mean {p['bp'].mean():+.2f} bp   "
              f"win {(p['bp']>0).mean()*100:.0f}%")
        return

    dow = t0.dayofweek
    print("PLAN FOR THE CURRENT / NEXT SESSION")
    print("-"*64)
    if dow in aod.SKIP_DOW:
        print("  Sunday-night reopen -> NO TRADE (skipped by rule).")
        return
    for ki in aod.K_IN_SET:
        for ko in aod.K_OUT_SET:
            t_in = t0 + pd.Timedelta(minutes=5*ki)
            t_out = t0 + pd.Timedelta(minutes=5*ko)
            print(f"  leg k={ki:>2}->{ko:<2}  BUY {t_in.tz_convert(IST):%H:%M} IST"
                  f"   SELL {t_out.tz_convert(IST):%H:%M} IST"
                  f"   ({t_in:%H:%M}->{t_out:%H:%M} UTC)")
    print("-"*64)
    print("  side: LONG only.  no stop-loss.  exit is time-based and unconditional.")
    print("  size: fixed fraction; see AOD_RULEBOOK.md for leverage guidance.")

if __name__ == "__main__":
    main()
