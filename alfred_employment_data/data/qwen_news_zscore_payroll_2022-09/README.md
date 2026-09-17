# Qwen News Z-score Payroll Project

## Fixed Setup

- Start sample: `target_date >= 2022-09-01`
- Target: BLS initial release components
  - private: `USPRIV_initial_change_k`
  - government: `USGOVT_initial_change_k`
- Final identity: `PAYEMS_initial = USPRIV_initial + USGOVT_initial`
- Validation: first 24 complete months are training only, then expanding-window OOS.

## Models

Private component:

```text
Z_USPRIV_initial_t = alpha + beta1 * Z_ADP_t + beta2 * QwenPrivateScore_t
```

Government component:

```text
Z_USGOVT_initial_t = alpha + gamma1 * Z_ICSA_avg_t
                         + gamma2 * Z_USGOVT_lag1_t
                         + gamma3 * QwenGovernmentScore_t
```

Predicted Z-scores are converted back to K values using only the expanding
training window mean and standard deviation, then summed:

```text
PAYEMS_pred_k = USPRIV_pred_k + USGOVT_pred_k
```

## Look-Ahead Control

Every Qwen prompt includes these hard constraints:

- Use only numerical inputs and articles inside the prompt.
- Do not use the actual BLS Employment Situation result.
- Do not use information published after the BLS pre-release cutoff.
- For release month `N`, do not use any future calendar-month information after
  release month `N`, even if the model knows it from training/general knowledge.
- Ignore articles that appear to contain post-release results, revisions, or
  later analysis.

Example:

```text
target_date = 2026-07-01
release month N = 2026-08
cutoff = 2026-08-07 08:29:00 ET
```

The prompt forbids anything after `2026-08-07 08:29 ET` and also forbids any
future calendar-month information after release month `2026-08`.

## Commands

Initialize folders and score template:

```powershell
python alfred_employment_data\run_qwen_news_zscore_payroll_project.py init
```

Collect a small sample for a target month:

```powershell
python alfred_employment_data\run_qwen_news_zscore_payroll_project.py collect-sample --target-date 2026-07-01 --release-date 2026-08-07 --max-records 2
```

Include GDELT as an additional source when rate limits are acceptable:

```powershell
python alfred_employment_data\run_qwen_news_zscore_payroll_project.py collect-sample --target-date 2026-07-01 --release-date 2026-08-07 --max-records 2 --include-gdelt
```

Build Qwen prompt JSON files:

```powershell
python alfred_employment_data\run_qwen_news_zscore_payroll_project.py build-prompts
```

After filling `scores\qwen_scores.csv`, run expanding regressions:

```powershell
python alfred_employment_data\run_qwen_news_zscore_payroll_project.py run-regression
```
