# ADP-PAYEMS Sign Mismatch Macro Context

Source files:
- `C:\Users\tmdwhd2080\Desktop\ADP.csv`
- `C:\Users\tmdwhd2080\Desktop\PAYEMS.xlsx`

Criterion:
- Same `target_date`
- `ADP.csv` `Real_value` and `PAYEMS.xlsx` `Real_value`
- Opposite signs only; zero values are not counted

Mismatch months:

| Target month | ADP actual | PAYEMS actual | Main macro/labor explanation |
|---|---:|---:|---|
| 2025-06 | -33 | +147 | ADP captured private-sector service weakness, while BLS headline was supported by government and health care. The initial BLS gain was later revised sharply lower. |
| 2025-09 | -32 | +119 | ADP showed private payroll contraction, while BLS showed gains in health care, food services, social assistance, and private payrolls. The 2025 federal shutdown delayed release and affected BLS operations. |
| 2025-10 | +42 | -105 | The cleanest coverage mismatch: ADP private payrolls rose, and BLS private payrolls also rose, but total PAYEMS fell because government payrolls dropped sharply, led by federal employment. |
| 2025-11 | -32 | +64 | ADP showed broad small-business/private pullback, while BLS headline was held positive by health care and construction. Shutdown-related survey disruptions were still relevant. |
| 2026-02 | +63 | -92 | ADP showed private hiring concentrated in construction and education/health, but BLS headline fell due to health care strike activity, information weakness, federal government decline, and weather/strike disruptions. |

Useful source links:
- BLS June 2025 Employment Situation: https://www.bls.gov/news.release/archives/empsit_07032025.htm
- BLS July 2025 Employment Situation, May/June revision discussion: https://www.bls.gov/news.release/archives/empsit_08012025.htm
- BLS September 2025 Employment Situation: https://www.bls.gov/news.release/archives/empsit_11202025.htm
- BLS November 2025 Employment Situation, including October/November shutdown notes: https://www.bls.gov/news.release/archives/empsit_12162025.htm
- BLS February 2026 Employment Situation: https://www.bls.gov/news.release/archives/empsit_03062026.htm
- ADP June 2025 report: https://mediacenter.adp.com/2025-07-02-ADP-National-Employment-Report-Private-Sector-Employment-Shed-33%2C000-Jobs-in-June-Annual-Pay-was-Up-4-4
- ADP September 2025 report: https://www.prnewswire.com/news-releases/adp-national-employment-report-private-sector-employment-shed-32-000-jobs-in-september-annual-pay-was-up-4-5-302572337.html
- ADP October 2025 report: https://mediacenter.adp.com/2025-11-05-ADP-National-Employment-Report-Private-Sector-Employment-Increased-by-42%2C000-Jobs-in-October-Annual-Pay-Was-Up-4-5
- ADP November 2025 report: https://mediacenter.adp.com/2025-12-03-ADP-National-Employment-Report-Private-Sector-Employment-Shed-32%2C000-Jobs-in-November-Annual-Pay-Was-Up-4-4
- ADP February 2026 report: https://mediacenter.adp.com/2026-03-04-ADP-National-Employment-Report-Private-Sector-Employment-Increased-by-63%2C000-Jobs-in-February-Annual-Pay-Was-Up-4-5
