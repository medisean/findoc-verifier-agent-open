# Public Financial Report Benchmark Inputs

This directory contains public annual-report PDFs used by
`scripts/run_standard_benchmark.py` for local table extraction comparison.

| File | Source | Benchmark pages |
| --- | --- | ---: |
| `aapl_2024.pdf` | AnnualReports Apple 2024 Form 10-K | 31-36 |
| `wmt_2024.pdf` | AnnualReports Walmart 2024 Annual Report | 55-60 |
| `nvda_2024.pdf` | AnnualReports NVIDIA 2024 Form 10-K | 149-154 |
| `jpm_2024.pdf` | AnnualReports JPMorgan Chase 2024 Annual Report | 205-210 |

The benchmark uses page windows rather than full-document OCR so it can run on
local CPU environments and remain focused on table-structure quality.
