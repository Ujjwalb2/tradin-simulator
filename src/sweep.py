#!/usr/bin/env python3
"""
Full parameter sweep across the seven open dimensions, split in-sample / out-of-sample.

Detection is the expensive step, so it runs once per structural variant (sweep mode x
reclaim depth) with all filters off. Penetration, space, the EMA check and the stop are
then applied to those cached setups as columns and masks, which makes 5,040 combinations
cheap enough to run exhaustively.

The headline "best combo" from a sweep this wide is close to meaningless on its own —
with 5,040 tries the top in-sample result is strongly positive whether or not any edge
exists. The numbers that matter are at the bottom of the report: how many combinations
survive BOTH samples, and whether in-sample rank predicts out-of-sample return at all.
"""
from __future__ import annotations

import itertools
import time
from pathlib import Path

import numpy as np
import pandas as pd

from backtest import DATA, ExecConfig, simulate, summarise
from strategy import Config, add_atr, run

OOS_START = pd.Timestamp("2025-01-01").date()
OUT = Path("out/sweep.csv")

SWEEP_MODES = ["close", "wick"]
RECLAIM_DEPTHS = [0.0, 0.38, 0.5]
PENS = [0.0, 0.20]
SPACES = [0.0, 0.25, 0.50]
EMAS = [False, True]
SLS = [("atr", 1.5), ("atr", 2.0), ("atr", 2.5), ("atr", 3.0), ("struct", 5)]
EXITS = [("trail", 3), ("trail", 5), ("trail", 8), ("trail", 12),
         ("fixed", 1.0), ("fixed", 1.5), ("fixed", 2.0)]
BES = [True, False]


def main() -> None:
    bars = pd.read_parquet(DATA)
    ist = bars.tz_convert("Asia/Kolkata").copy()
    ist["atr"] = add_atr(ist, 14)

    total = (len(SWEEP_MODES) * len(RECLAIM_DEPTHS) * len(PENS) * len(SPACES)
             * len(EMAS) * len(SLS) * len(EXITS) * len(BES))
    print(f"{total} combinations; {len(SWEEP_MODES) * len(RECLAIM_DEPTHS)} detection runs\n",
          flush=True)

    rows = []
    done = 0
    t0 = time.time()

    for mode, depth in itertools.product(SWEEP_MODES, RECLAIM_DEPTHS):
        # Detect with every filter off; the filters are applied below as masks.
        cfg = Config(sweep_mode=mode, reclaim_depth_r=depth,
                     min_pen_atr=0.0, min_space_atr=0.0)
        setups, _ = run(bars, cfg)
        print(f"[detect] sweep={mode} depth={depth}: {len(setups)} setups "
              f"({time.time() - t0:.0f}s)", flush=True)
        if setups.empty:
            continue
        setups = setups.copy()
        setups["ema_ok"] = setups["ema_ok"].astype(bool)

        for pen, space, ema in itertools.product(PENS, SPACES, EMAS):
            m = (setups["pen_atr"] >= pen) & (setups["space_atr"] >= space)
            if ema:
                m &= setups["ema_ok"]
            base = setups[m]
            if base.empty:
                done += len(SLS) * len(EXITS) * len(BES)
                continue

            for sl_mode, sl_val in SLS:
                st = base.copy()
                if sl_mode == "atr":
                    st["sl"] = np.where(st["side"] == "long",
                                        st["entry"] - sl_val * st["atr"],
                                        st["entry"] + sl_val * st["atr"])
                else:
                    st["sl"] = st[f"sl_struct_{sl_val}"]
                risk = np.where(st["side"] == "long",
                                st["entry"] - st["sl"], st["sl"] - st["entry"])
                st = st[risk > 0]
                st["status"] = "VALID"
                if st.empty:
                    done += len(EXITS) * len(BES)
                    continue

                for (ex_mode, ex_val), be in itertools.product(EXITS, BES):
                    xc = ExecConfig(
                        exit_mode=ex_mode,
                        trail_lookback=int(ex_val) if ex_mode == "trail" else 5,
                        target_r=float(ex_val) if ex_mode == "fixed" else 2.0,
                        use_be=be,
                    )
                    tr = simulate(ist, st, xc)
                    done += 1
                    if tr.empty:
                        continue
                    is_tr = tr[tr["date"] < OOS_START]
                    oos_tr = tr[tr["date"] >= OOS_START]
                    if len(is_tr) < 30 or len(oos_tr) < 30:
                        continue
                    a, b = summarise(is_tr), summarise(oos_tr)
                    rows.append({
                        "sweep": mode, "depth": depth, "pen": pen, "space": space,
                        "ema": ema, "sl": f"{sl_mode}{sl_val}",
                        "exit": f"{ex_mode}{ex_val}", "be": be,
                        "n_is": a["trades"], "avgR_is": a["avg_R"], "R_is": a["total_R"],
                        "win_is": a["win%"], "pf_is": a["pf"],
                        "n_oos": b["trades"], "avgR_oos": b["avg_R"], "R_oos": b["total_R"],
                        "win_oos": b["win%"], "pf_oos": b["pf"],
                    })
            print(f"    pen={pen} space={space} ema={ema}: {done}/{total} "
                  f"({time.time() - t0:.0f}s)", flush=True)

    df = pd.DataFrame(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"\n{len(df)} scored combinations -> {OUT}  ({time.time() - t0:.0f}s)")

    if df.empty:
        return
    d = df.sort_values("R_is", ascending=False)
    print("\n=== TOP 20 BY IN-SAMPLE, WITH THEIR OUT-OF-SAMPLE RESULT ===")
    cols = ["sweep", "depth", "pen", "space", "ema", "sl", "exit", "be",
            "n_is", "avgR_is", "R_is", "n_oos", "avgR_oos", "R_oos"]
    print(d[cols].head(20).to_string(index=False))

    print("\n=== DOES THE SWEEP GENERALISE? ===")
    print(f"  positive in-sample      : {(df['R_is'] > 0).sum()} / {len(df)}")
    print(f"  positive out-of-sample  : {(df['R_oos'] > 0).sum()} / {len(df)}")
    print(f"  positive in BOTH        : {((df['R_is'] > 0) & (df['R_oos'] > 0)).sum()} / {len(df)}")
    print(f"  IS/OOS avg-R correlation: {df['avgR_is'].corr(df['avgR_oos']):+.3f}")
    top = d.head(int(len(d) * 0.1))
    print(f"  best 10% by IS -> mean OOS avg R: {top['avgR_oos'].mean():+.4f}")
    print(f"  all combos     -> mean OOS avg R: {df['avgR_oos'].mean():+.4f}")


if __name__ == "__main__":
    main()
