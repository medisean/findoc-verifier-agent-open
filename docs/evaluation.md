# 评测与复现

项目内置轻量评测器，用于将 `runs/<task_id>/result.json` 与
`examples/evaluation_expectations.yaml` 中记录的期望值进行对比。评测目标不是只看抽取了多少表，
而是同时检查结构、质量阈值和必要输出。

## 1. 单任务评测

```bash
UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
  runs/scanned_financial_statement_pdf-ocr-fallback/result.json \
  examples/evaluation_expectations.yaml
```

评测器会按 `task_id` 选择对应期望值，并输出：

- `score`：通过检查数 / 总检查数。
- `checks`：表数量、行数量、失败阈值、必要表和必要指标的逐项结果。必要指标可同时检查数值、
  单位和 evidence。
- `status`：当前结果是否满足期望。

## 2. 质量字段

`result.json` 中的 `quality` 字段包含两类信号：

- `validation_pass_rate`、`failed_count`：硬性数值一致性校验。
- `warning_count`、`diagnostics`：非阻塞质量风险，例如单位缺失、期间缺失、证据覆盖不足或 OCR 歧义。
- `repairs`：修复数量、原始值、修复值和修复原因。

重要 `diagnostics` 字段：

- `risk_level`：`low`、`medium` 或 `high`。
- `numeric_parse_coverage`：疑似数值单元格的可解析比例。
- `evidence_coverage`：行级 page/bbox 证据覆盖比例。
- `financial_table_count`：疑似财务表数量。
- `recommended_actions`：后续运行建议。

当 `numeric_parse_coverage` 暴露确定性 OCR 数字混淆时，执行器会先尝试修复，再把修复日志和复验后的
质量状态写回 `result.json` 与 `trace.jsonl`。

## 3. Benchmark 矩阵

已验证的核心任务：

- `annual_report_pdf-full-local`
- `cross_page_table_pdf-full-local`
- `scanned_financial_statement_pdf-ocr-fallback`
- `docx_management_report-latest-smoke`
- `ppt_xlsx_attachment_pack-multi-smoke`
- `html_native_parse`
- `chart_reference_resolution`

已验证的公开样本任务：

- `public-aapl-2024-financials`
- `public-wmt-2024-financials`
- `public-nvda-2024-financials`
- `public-jpm-2024-financials`

已完成全量验证的中国公开年报任务：

- `cn_byd_2025_annual_report`
- `cn_catl_2025_annual_report`
- `cn_moutai_2025_annual_report`
- `cn_cmb_2025_annual_report`

上述核心任务和海外公开样本当前均满足记录好的期望值，评测结果为 `status: pass`。中国公开年报
全量验证的汇总结果见 `docs/public_benchmark_results.md`。

已完成本地标准横评：

- `pdfplumber_traditional`
- `mineru_pipeline_txt_direct`
- `findoc_agent`

横评使用 4 份公开英文年报的 24 页核心财务页窗。传统 baseline 平均期望通过率为 0.3750；
MinerU 直接解析和 FinDoc Agent 均为 1.0000。FinDoc Agent 相比传统 baseline 多结构化 15 张表、
469 行，并保留任务计划、质量诊断、修复和 trace 产物。详见 `docs/standard_benchmark_report.md` 和
`examples/benchmark_results/standard_table_benchmark_summary.json`。

已完成复杂版式定向 accuracy：

- HTML `rowspan/colspan` 多级表头展开。
- 跨页续表合并和单位继承。
- 密集数字、脚注和括号负数单元格。
- 手写批注噪声、多栏混排、嵌套/多行表头专项。

3 个 case 全部通过，header precision/recall、row precision/recall、numeric exact match、
cross-page merge accuracy 和 unit inheritance accuracy 均为 1.0000。详见
`docs/layout_accuracy_report.md` 和 `examples/benchmark_results/layout_accuracy_summary.json`。

Edge layout 专项 3 个 case 全部通过，7/7 required metrics 命中，批注噪声排除、多栏阅读顺序、
嵌套表头展开和合并单元格展开指标均为 1.0000。详见
`docs/edge_layout_benchmark_report.md` 和 `examples/benchmark_results/edge_layout_summary.json`。

已完成 100 任务本地 soak test：100/100 成功，plan/trace/result coverage 为 1.0000，输出结构一致性为
1.0000。详见 `docs/soak_test_report.md` 和 `examples/benchmark_results/soak_test_summary.json`。

## 4. 复现命令

批量运行所有记录任务的评测：

```bash
for task in \
  annual_report_pdf-full-local \
  cross_page_table_pdf-full-local \
  scanned_financial_statement_pdf-ocr-fallback \
  docx_management_report-latest-smoke \
  ppt_xlsx_attachment_pack-multi-smoke \
  public-aapl-2024-financials \
  public-wmt-2024-financials \
  public-nvda-2024-financials \
  public-jpm-2024-financials
do
  UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
    "runs/$task/result.json" \
    examples/evaluation_expectations.yaml
done
```

中国公开年报全量验证：

```bash
export MINERU_MODEL_SOURCE=local
export MINERU_MAX_CONCURRENCY=1
python3 scripts/run_cn_full_validation.py --poll-seconds 60 --continue-on-failure
```

GPU OCR 复核结果见 `docs/gpu_validation_report.md`。该报告记录 4 份中文公开年报的 Colab GPU
全量 OCR 任务，以及并发 2/3 的短页窗批量稳定性结果。

对已有中文年报结果执行 gold metrics 复评时，如果 `task_id` 是 UUID，可显式指定稳定任务 key：

```bash
UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
  runs/<task_id>/result.json \
  examples/evaluation_expectations.yaml \
  --task-key cn_byd_2025_annual_report
```

Agent 能力证据包：

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/run_capability_evidence.py --clean
```

标准横评：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_standard_benchmark.py --clean
```

复杂版式 accuracy、adversarial 汇总和 soak：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_layout_accuracy_benchmark.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_adversarial_evaluation.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_edge_layout_benchmark.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_soak_test.py --clean --task-count 100 --concurrency 8
```

## 极端样本回归

adversarial fixture 可用以下命令生成和复评：

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/build_adversarial_fixtures.py

for task in \
  adversarial_low_light_scan \
  adversarial_cross_page_unit \
  adversarial_dense_numeric_footnotes
do
  UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
    "examples/adversarial_results/$task.json" \
    examples/adversarial_expectations.yaml \
    --task-key "$task"
done
```

## 5. 建议保留的证据

每个 benchmark 建议保留：

- 输入文件来源。
- `result.json`。
- `trace.jsonl`。
- evaluator JSON 输出或 CLI 输出。

这些文件共同证明结构化结果、工具调用 trace、质量诊断、修复行为和评测可复现。
