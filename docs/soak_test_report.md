# 100 任务 Soak 报告

本报告记录一次本地 control-plane soak test。该测试不调用 MinerU OCR，使用 HTML 原生解析路径，
重点验证任务规划、并发执行、结果一致性、`plan.json` / `trace.jsonl` / `result.json` 产物写出。
GPU OCR 和大文档吞吐证据见 `docs/gpu_validation_report.md`。

机器可读结果见 `examples/benchmark_results/soak_test_summary.json`。

## 配置

| 项 | 值 |
| --- | ---: |
| 任务数 | 100 |
| 并发 | 8 |
| 输入 | `examples/inputs/html_financial_table.html` |
| 执行路径 | Native HTML parser + Agent plan/verify/package |
| 产物目录 | `runs/soak_test/` |

## 结果

| 指标 | 结果 |
| --- | ---: |
| succeeded | 100 |
| failed | 0 |
| success rate | 1.0000 |
| wall seconds | 0.267 |
| p50 seconds | 0.0119 |
| p95 seconds | 0.0186 |
| max seconds | 0.0234 |
| plan/trace/result coverage | 1.0000 |
| output shape consistency | 1.0000 |
| total tables | 100 |
| total rows | 200 |
| hard failures | 0 |

## 结论

100 个并发调度任务全部成功，且每个任务都写出 `plan.json`、`trace.jsonl` 和 `result.json`。
输出结构保持一致：每个任务 1 张表、2 行、硬失败 0、数值解析覆盖 1.0、证据覆盖 1.0。

## 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_soak_test.py --clean --task-count 100 --concurrency 8
```
