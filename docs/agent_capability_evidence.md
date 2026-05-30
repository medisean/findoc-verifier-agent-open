# Agent 能力证据包

本说明记录四项可本地复验的能力证据，覆盖混合任务规划、HTML 结构化、上下文数值修复、
复杂图表结构化和全局指代消解。
这些检查不依赖 GPU 或 MinerU 模型，适合作为快速回归和外部复核入口。

## 1. 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/run_capability_evidence.py --clean
```

如需生成仓库内的示例报告：

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/run_capability_evidence.py \
  --clean \
  --report-path examples/capability_evidence_report.json
```

## 2. 覆盖能力

| 场景 | 证明点 | 输出 |
| --- | --- | --- |
| `html_native_parse` | HTML 输入不调用 MinerU，直接解析网页 table、caption、单位、期间和 evidence | `native_html_tool_events`、表格质量诊断 |
| `mixed_dag_execution` | PDF、扫描件、XLSX 混合输入生成 DAG，并在 trace 中落到 `parse_input_*` 分支 | `graph.is_dag`、`parse_stages`、共享上下文和跨文件核验 |
| `contextual_numeric_repair` | 低置信数字通过单位、期间、行标签、evidence 和 peer values 修复 | `contextual_ocr_unit_suffix`、`context_evidence` |
| `chart_reference_resolution` | 堆叠柱状图、折线图、瀑布图转为结构化指标，并把正文指代回指到图表指标 | `chart_types`、`resolved_metric_kinds`、`min_reference_confidence` |

## 3. 当前示例报告

当前仓库内保留一份示例输出：

```text
examples/capability_evidence_report.json
```

摘要：

- `scenario_count = 4`
- `html_native_parse.status = pass`
- `mixed_dag_execution.graph.is_dag = true`
- `mixed_dag_execution.cross_file_checks.conflict_count = 0`
- `contextual_numeric_repair.repair_summary.applied = true`
- `chart_reference_resolution.chart_types = line_chart, stacked_bar, waterfall`
- `chart_reference_resolution.resolved_reference_count = 5`

## 4. 工程意义

这组证据把三类能力从说明文本变成可执行检查：

- HTML/网页表格走 Agent 原生结构化路径，补齐 PDF/Office/扫描件之外的网页输入。
- 混合输入任务不只是固定流水线，计划图和 trace 阶段名能相互印证。
- 修复动作不是孤立正则替换，而是带上下文证据的可复验修复。
- 图表不是只作为图片保留，而是进入统一表格 schema；正文中的跨页指代会保留目标行、期间、
  单位、页码和置信度。
