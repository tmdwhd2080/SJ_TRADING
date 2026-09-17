# Theme Trading

Self-contained copy of the existing intraday theme portfolio pipeline and local
backtest. The strategy code is unchanged. Python 3.12 is the tested version.

## Contents

```text
Theme_Trading/
  RUN_theme_intraday_stock_ga.py
  RUN_theme_data_backtest.py
  requirements.txt
  Theme_intraday_stock_ga/
    __init__.py
    pipeline.py
    backtest_theme_data.py
  theme_data/                 # Copied historical input files
  theme_intraday_ga_data/     # Copied snapshots and new run outputs
    backtest/                # Backtest outputs
```

The original files outside this folder remain in place. The copies are independent
and do not synchronize. Use the runners in this folder for subsequent runs.
Default data paths resolve relative to this folder, regardless of the terminal's
working directory. No Theme_real or Theme_model source files are required.

## Setup and Run (PowerShell)

```powershell
cd "C:\Users\tmdwhd2080\Desktop\blank-app-1\Theme_Trading"
python -m pip install -r .\requirements.txt
python .\RUN_theme_intraday_stock_ga.py
```

Run the local historical backtest:

```powershell
python .\RUN_theme_data_backtest.py
```

Show optional arguments:

```powershell
python .\RUN_theme_intraday_stock_ga.py --help
python .\RUN_theme_data_backtest.py --help
```

## Data and Results

Live execution requires internet access to Naver. This program produces a
portfolio file; it does not submit buy orders.

The live runner reads historical inputs from `theme_data/` and prior snapshots
from `theme_intraday_ga_data/`. New snapshots and portfolio outputs are saved in
`theme_intraday_ga_data/`. Repeated runs overwrite that day's files and the
`latest_*.csv` / `latest_run_summary.json` files as each stage completes.
Other dates are retained. Always check `latest_run_summary.json` for the run's
status and timestamp before using a portfolio: a stopped run may leave an older
portfolio file in place.

Existing copied summaries describe their original runs and may contain original
absolute paths. They are records, not path configuration for future runs.

The current business-day rule excludes weekends only, not Korean exchange
holidays. The live filter requires the previous two business-day snapshots;
missing history can stop portfolio formation after saving the current theme
snapshot. `--allow-stale-history` is intended only for testing.

The backtest writes results under `theme_intraday_ga_data/backtest/`. Its main
return metric is a theme-return proxy. Available next-day stock observations are
partial, so these outputs are not a complete stock-level execution backtest.
