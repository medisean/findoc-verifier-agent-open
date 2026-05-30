# API 说明

## 概览

服务提供最小化异步任务接口：

- `GET /health`
- `POST /v1/tasks`
- `GET /v1/tasks/{task_id}`
- `GET /v1/tasks/{task_id}/result`

可复制的完整请求与响应示例见 `docs/api_examples.md`。

## `GET /health`

返回服务健康状态。

示例响应：

```json
{"status": "ok"}
```

## `POST /v1/tasks`

创建异步处理任务，并返回任务标识。

```json
{
  "task_name": "annual-report-smoke",
  "document_type": "annual_report_pdf",
  "inputs": [{"path": "examples/inputs/annual_report.pdf"}],
  "goal": "Extract financial statements with evidence and validation logs.",
  "options": {}
}
```

常用 MinerU 参数：

```json
{
  "backend": "pipeline",
  "method": "txt",
  "start_page": 48,
  "end_page": 52
}
```

- 文本层 PDF 使用 `method=txt`。
- 扫描 PDF 和图片输入使用 `method=ocr`。
- 远端验证可使用 `backend=hybrid-http-client` 或 `backend=vlm-http-client`，并传入 `server_url`。

示例响应：

```json
{
  "task_id": "annual-report-smoke",
  "status": "queued",
  "document_type": "annual_report_pdf"
}
```

字段说明：

- `task_name`：调用方定义的任务名，尽量用于运行目录命名。
- `document_type`：解析提示，例如 `annual_report_pdf`、`scanned_financial_statement_pdf`、
  `docx_management_report` 或 `ppt_xlsx_attachment_pack`。
- `inputs`：一个或多个文件，包含 `path`、可选 `role` 和可选 `mime_type`。
- `goal`：自然语言处理目标。
- `options`：backend、页码范围和运行时覆盖参数。

## `GET /v1/tasks/{task_id}`

返回任务状态和基础元数据。

示例响应：

```json
{
  "task_id": "annual-report-smoke",
  "task_name": "annual-report-smoke",
  "status": "succeeded",
  "document_type": "annual_report_pdf",
  "created_at": "2026-05-26T10:00:00Z",
  "updated_at": "2026-05-26T10:01:12Z"
}
```

## `GET /v1/tasks/{task_id}/result`

任务完成后返回最终结构化结果包。

```json
{
  "task_id": "annual-report-smoke",
  "status": "succeeded",
  "document_type": "annual_report_pdf",
  "summary": "Parsed 58 tables with 632 rows. Validation pass rate: 100.00%. Warnings: 53; failures: 0; repairs: 0.",
  "tables": [],
  "quality": {
    "validation_pass_rate": 1.0,
    "check_count": 94,
    "hard_check_count": 43,
    "passed_count": 43,
    "warning_count": 53,
    "failed_count": 0,
    "issue_count": 53,
    "checks": [],
    "warnings": [],
    "diagnostics": {
      "risk_level": "medium",
      "numeric_parse_coverage": 1.0,
      "evidence_coverage": 1.0,
      "financial_table_count": 27,
      "recommended_actions": []
    },
    "repairs": {
      "applied": false,
      "repair_count": 0,
      "repairs": []
    }
  },
  "trace_path": "runs/annual-report-smoke/trace.jsonl",
  "plan_path": "runs/annual-report-smoke/plan.json",
  "result_path": "runs/annual-report-smoke/result.json"
}
```

结果字段语义：

- `tables`：归一化后的表格对象，包含行、期间、证据和标签。
- `task_name`：调用方传入的业务任务名，可用于稳定评测 key。
- `quality.validation_pass_rate`：硬性数值校验通过率。
- `quality.warning_count`：非阻塞质量风险数量，例如单位缺失、期间缺失、疑似 OCR 数字问题。
- `quality.failed_count`：硬性数值一致性失败数量。
- `quality.diagnostics`：解析风险、证据覆盖和财务表数量摘要。
- `quality.repairs`：Agent 已应用的确定性数值修复记录。
- `plan_path`：文档画像和可解释执行计划路径，包含步骤依赖、成功条件和恢复动作。
- `trace_path`：阶段级执行日志路径，用于复盘和调试。

## 任务状态

常见状态：

- `queued`
- `running`
- `succeeded`
- `failed`

如果任务在结果打包前失败，应查看 `runs/<task_id>/trace.jsonl`，定位最后成功阶段和异常上下文。
