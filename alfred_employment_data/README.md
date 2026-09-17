# ALFRED Employment Revision Events

This script collects initial releases and revision events for:

- `PAYEMS_monthly_change_thousands`: nonfarm payroll monthly change, in thousands
- `ADP_monthly_change_thousands`: ADP private payroll monthly change, in thousands
- `ICSA_weekly_level_count`: weekly initial claims level, in claims

It writes two CSV files only.

## Run

From the project root:

```powershell
python alfred_employment_data\fetch_alfred_employment_data.py --start-year 2022
```

From this folder:

```powershell
cd alfred_employment_data
python fetch_alfred_employment_data.py --start-year 2022
```

Default outputs:

```text
alfred_employment_data\data\employment_events_2022_2026\initial_releases.csv
alfred_employment_data\data\employment_events_2022_2026\revision_events.csv
```

## Initial Correlation Analysis

```powershell
python alfred_employment_data\analyze_initial_correlations.py
```

Default outputs:

```text
alfred_employment_data\data\initial_correlation_analysis_2022-09_2026-06\initial_monthly_panel.csv
alfred_employment_data\data\initial_correlation_analysis_2022-09_2026-06\initial_correlations.csv
```

## NFP Multivariate Regression

```powershell
python alfred_employment_data\run_nfp_multivariate_regression.py
```

Default outputs:

```text
alfred_employment_data\data\nfp_multivariate_model_2023-01_2026-06\model_panel.csv
alfred_employment_data\data\nfp_multivariate_model_2023-01_2026-06\regression_coefficients.csv
alfred_employment_data\data\nfp_multivariate_model_2023-01_2026-06\predictions.csv
```

## NFP Two-Factor Regression

```powershell
python alfred_employment_data\run_nfp_twofactor_regression.py
```

Default split:

```text
Train: 2023-01 through 2024-12
Test:  2025-01 through 2026-06
```

Default outputs:

```text
alfred_employment_data\data\nfp_twofactor_model_2023-01_2026-06_train2023-2024\model_panel.csv
alfred_employment_data\data\nfp_twofactor_model_2023-01_2026-06_train2023-2024\regression_coefficients.csv
alfred_employment_data\data\nfp_twofactor_model_2023-01_2026-06_train2023-2024\predictions.csv
```

## Initial Release Columns

- `indicator`: indicator and unit basis
- `release_date`: date when the initial value was published in ALFRED/FRED vintage data
- `target_date`: observation month or week
- `published_value`: first released value. `PAYEMS` and ADP are monthly changes in thousands; `ICSA` is weekly claims level.

## Revision Event Columns

- `indicator`: indicator and unit basis
- `release_date`: date when the revision was published in ALFRED/FRED vintage data
- `target_date`: observation month or week being revised
- `published_value`: previously published value
- `revised_value`: revised value
- `change`: revised value minus previously published value
