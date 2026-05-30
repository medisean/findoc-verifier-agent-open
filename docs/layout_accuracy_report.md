# 复杂版式 Accuracy 报告

本报告补充跨页合并、多级表头、合并单元格和密集数字场景的定向 accuracy 结果。完整机器可读结果见
`examples/benchmark_results/layout_accuracy_summary.json`，gold 配置见
`examples/layout_accuracy_expectations.json`。

## 覆盖场景

| Case | 难点 | 输入 |
| --- | --- | --- |
| `html_rowspan_colspan_header` | HTML 多级表头、`rowspan` / `colspan` 展开、括号负数 | `examples/inputs/html_financial_table.html` |
| `cross_page_unit_inheritance` | 跨页续表合并、单位继承、括号负数 | `examples/adversarial_results/adversarial_cross_page_unit.json` |
| `dense_numeric_footnote_cells` | 密集数字、脚注列、百分比和括号负数 | `examples/adversarial_results/adversarial_dense_numeric_footnotes.json` |

## 汇总指标

| 指标 | 结果 |
| --- | ---: |
| case count | 3 |
| passed count | 3 |
| header precision | 1.0000 |
| header recall | 1.0000 |
| row precision | 1.0000 |
| row recall | 1.0000 |
| numeric exact match | 1.0000 |
| cross-page merge accuracy | 1.0000 |
| unit inheritance accuracy | 1.0000 |

## 分项说明

- HTML 表格中 `报告期` 横向合并表头被展开为 `报告期 2025 Q2` 和 `报告期 2024 Q2`。
- 跨页现金流样本保留 `page_start=0`、`page_end=1`，单位继承为 `RMB thousand`。
- 密集数字样本正确解析 `6.5%`、`24.1%` 和 `(512)` 等单元格。

## 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_layout_accuracy_benchmark.py
```
