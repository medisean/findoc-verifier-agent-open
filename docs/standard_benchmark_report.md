# 标准横评报告

本报告记录一次本地可复现的公开金融报表页窗横评。目标是把传统表格抽取工具、MinerU
直接解析结果和 FinDoc Agent 的结构化结果放在同一组任务上比较，验证 Agent 层在保留解析质量的同时，
提供规划、校验、修复、trace 和 API 化执行能力。

机器可读汇总见 `examples/benchmark_results/standard_table_benchmark_summary.json`。

## 样本

本轮使用 4 份公开英文年报的核心财务报表页窗，共 24 页：

| 样本 | 文件 | 页窗 |
| --- | --- | ---: |
| Apple 2024 | `examples/inputs/public_benchmark/aapl_2024.pdf` | 31-36 |
| Walmart 2024 | `examples/inputs/public_benchmark/wmt_2024.pdf` | 55-60 |
| NVIDIA 2024 | `examples/inputs/public_benchmark/nvda_2024.pdf` | 149-154 |
| JPMorgan Chase 2024 | `examples/inputs/public_benchmark/jpm_2024.pdf` | 205-210 |

## 对比方法

| 方法 | 说明 |
| --- | --- |
| `pdfplumber_traditional` | 传统 PDF 表格抽取 baseline，只做局部表格识别和单元格解析。 |
| `mineru_pipeline_txt_direct` | MinerU `pipeline/txt` 直接解析页窗，再做直接结构归一，不包含任务编排、恢复策略和 trace 打包。 |
| `findoc_agent` | FinDoc Agent 已保存结果，包含任务计划、工具路由、结构化归一、质量诊断、修复闭环和日志记录。 |

## 汇总结果

| 方法 | 任务数 | 成功 | 表 | 行 | hard fail | 期望通过率 | 数值解析覆盖 | 证据覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `pdfplumber_traditional` | 4 | 4 | 6 | 129 | 0 | 0.3750 | 1.0000 | 1.0000 |
| `mineru_pipeline_txt_direct` | 4 | 4 | 23 | 603 | 0 | 1.0000 | 0.9891 | 1.0000 |
| `findoc_agent` | 4 | 4 | 21 | 598 | 0 | 1.0000 | 0.9842 | 1.0000 |

FinDoc Agent 相比传统 baseline 多结构化 15 张表、469 行，期望检查平均提升 0.6250。
与 MinerU 直接解析相比，Agent 的纯抽取通过率保持一致，同时输出 `plan.json`、`trace.jsonl`、
`result.json`，并提供低质量恢复、数值修复和统一 API 生命周期。

## 分任务结果

| Task | pdfplumber 表/行/通过率 | MinerU direct 表/行/通过率 | FinDoc Agent 表/行/通过率 |
| --- | --- | --- | --- |
| `public-aapl-2024-financials` | 5 / 118 / 0.5000 | 5 / 136 / 1.0000 | 5 / 136 / 1.0000 |
| `public-wmt-2024-financials` | 0 / 0 / 0.3333 | 6 / 156 / 1.0000 | 5 / 154 / 1.0000 |
| `public-nvda-2024-financials` | 1 / 11 / 0.3333 | 5 / 134 / 1.0000 | 5 / 134 / 1.0000 |
| `public-jpm-2024-financials` | 0 / 0 / 0.3333 | 7 / 177 / 1.0000 | 6 / 174 / 1.0000 |

## 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_standard_benchmark.py --clean
```

脚本会输出：

- `examples/benchmark_results/standard_table_benchmark_summary.json`
- `runs/standard_benchmark/<task>/mineru_pipeline_txt/`

如果只想复核传统 baseline 和已保存 Agent 结果，可使用：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_standard_benchmark.py --skip-mineru
```
