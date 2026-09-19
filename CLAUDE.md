# Working in this repo

Read [`PROJECT.md`](PROJECT.md) first — it holds the project's state, the decisions already
made, the gotchas already paid for and what has already been verified. Then [`README.md`](README.md)
for how to run and rebuild things.

Two rules that save the most time here:

- Don't re-verify what `PROJECT.md` lists as verified, and don't reopen a decision it records
  without asking.
- The replay cursor is always a 5-minute bar, and every higher timeframe must be exactly the
  aggregate of its 5m bars. Anything that touches the data or the chart has to keep that true.

Python lives in `./.venv` (`./.venv/bin/python`). Raw downloads under `data/` are not committed;
`replay/data/` is, because the hosted site loads it.
