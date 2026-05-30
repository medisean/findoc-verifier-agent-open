# Agent 规划与上下文修复证据

本说明记录两项关键能力补强：混合输入任务的动态 DAG 规划，以及基于文档级上下文的数值修复。
目标是把“Agent 自动规划”和“智能修复”从口头能力变成可测试、可复现的工程证据。

## 1. 混合输入动态 DAG

新增样例任务：

```yaml
id: mixed_financial_verification_pack
inputs:
  - annual_report.pdf                 # primary PDF
  - scanned_financial_statement.pdf   # scanned reference
  - financial_model.xlsx              # attachment
goal: 从 PDF 年报抽取营收和经营利润，解析扫描审计证据，并与 XLSX 明细模型做跨文件核验。
```

当任务包含多输入、多角色或跨文件核验目标时，`build_plan()` 会切换为
`mixed_document_dag`。该计划不再是单条固定流水线，而是按输入拆分为可并行分支：

1. 对每个输入做画像和路由决策。
2. 对 Office 附件展开内容单元。
3. 对扫描件做质量评估并选择 OCR 路径。
4. 按输入并行解析。
5. 按输入结构化表格、期间、单位和 evidence。
6. 推断共享财务上下文，包括单位继承、期间别名和指标别名。
7. 执行跨文件指标核验。
8. 再进入数值校验、恢复、上下文修复和结果输出。

`plan.json` 新增 `graph` 字段，记录：

- `step_count`
- `edge_count`
- `edges`
- `parallel_groups`
- `is_dag`

这样使用者可以直接看到计划不是线性说明，而是可检查的 DAG。
执行时，混合任务的 `trace.jsonl` 会使用对应的分支阶段名，例如 `parse_input_00_*`、
`parse_input_01_*` 和 `parse_input_02_*`，并额外记录：

- `infer_shared_financial_context`：输出 source role、单位、期间和 metric alias 摘要。
- `reconcile_cross_file_metrics`：按 metric、period 和 source role 做跨文件数值核验，输出 matched/conflict 统计。

## 2. 文档级上下文数值修复

`repair_numeric_cells()` 会为每个低置信数值单元构建上下文：

- 表格名称和标题。
- 表格单位和脚注。
- 当前 period header。
- 当前 row label。
- 行级和表级 evidence。
- 同行其他期间的 peer values。

修复记录新增：

- `reason`
- `confidence`
- `context_used`
- `context_evidence`

示例：当 OCR 把 `100百万元` 识别为 `1O0百万元` 时，修复器会：

1. 将 `O` 识别为可能的 `0`。
2. 从表格单位 `人民币百万元` 和脚注中确认 `百万元` 是上下文单位。
3. 去除与上下文一致的单位后得到 `100`。
4. 记录 `contextual_ocr_unit_suffix`，并保留 period、row、unit、peer value 和 evidence。

这比单纯正则替换更强，因为修复动作必须由表格上下文支持，并在修复后重新进入校验。

## 3. 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run python -m pytest tests/test_executor.py tests/test_repair.py -q
```

重点测试：

- `test_mixed_document_plan_builds_dynamic_dag`
- `test_mixed_executor_trace_follows_dynamic_plan`
- `test_contextual_repair_uses_unit_and_period_evidence`

当前结果：

```text
16 passed
```

## 4. 材料口径

这两项补强可在方案展示中表述为：

- Agent 规划不是固定链路；多输入任务会生成带并行分支、共享上下文和跨文件核验节点的 DAG。
- 数值修复不是孤立字符替换；修复记录包含单位、期间、行标签、同期间/同行上下文和 evidence，并且修复后复验。
