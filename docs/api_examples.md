# API 请求与响应示例

本页给出可直接复制的 API 请求和典型响应。完整接口字段说明见 `docs/api.md`。

## 健康检查

```bash
curl http://127.0.0.1:8000/health
```

```json
{
  "status": "ok"
}
```

## 创建 HTML 表格任务

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "api-html-smoke",
    "document_type": "html_financial_table",
    "inputs": [
      {
        "path": "examples/inputs/html_financial_table.html",
        "role": "primary",
        "mime_type": "text/html"
      }
    ],
    "goal": "Extract the HTML financial table with evidence and validation logs.",
    "options": {}
  }'
```

```json
{
  "task_id": "2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77",
  "status": "queued",
  "document_type": "html_financial_table"
}
```

## 查询任务状态

```bash
curl http://127.0.0.1:8000/v1/tasks/2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77
```

```json
{
  "task_id": "2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77",
  "task_name": "api-html-smoke",
  "status": "succeeded",
  "document_type": "html_financial_table",
  "created_at": "2026-05-31T00:00:00Z",
  "updated_at": "2026-05-31T00:00:01Z"
}
```

## 获取结构化结果

```bash
curl http://127.0.0.1:8000/v1/tasks/2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77/result
```

```json
{
  "task_id": "2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77",
  "task_name": "api-html-smoke",
  "status": "succeeded",
  "document_type": "html_financial_table",
  "summary": "Parsed 1 tables with 2 rows. Validation pass rate: 100.00%. Warnings: 0; failures: 0; repairs: 0.",
  "tables": [
    {
      "name": "主要财务指标",
      "title": "主要财务指标",
      "unit": "人民币百万元",
      "table_type": "html_table",
      "periods": ["报告期 2025 Q2", "报告期 2024 Q2"],
      "rows": [
        {
          "item": "营业收入",
          "raw_values": ["1,250", "1,080"],
          "values": {
            "报告期 2025 Q2": 1250,
            "报告期 2024 Q2": 1080
          },
          "evidence": {
            "page": 0,
            "source": "html_table"
          }
        },
        {
          "item": "经营利润",
          "raw_values": ["（215）", "180"],
          "values": {
            "报告期 2025 Q2": -215,
            "报告期 2024 Q2": 180
          },
          "evidence": {
            "page": 0,
            "source": "html_table"
          }
        }
      ]
    }
  ],
  "quality": {
    "validation_pass_rate": 1.0,
    "failed_count": 0,
    "warning_count": 0,
    "diagnostics": {
      "risk_level": "low",
      "table_count": 1,
      "row_count": 2,
      "numeric_parse_coverage": 1.0,
      "evidence_coverage": 1.0,
      "financial_table_count": 1
    },
    "repairs": {
      "applied": false,
      "repair_count": 0,
      "repairs": []
    }
  },
  "trace_path": "runs/2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77/trace.jsonl",
  "plan_path": "runs/2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77/plan.json",
  "result_path": "runs/2f6b1aa4-9b70-4d1f-aec7-5f98406c4b77/result.json"
}
```

## 创建 PDF 页窗任务

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "api-public-aapl-pages",
    "document_type": "annual_report_pdf",
    "inputs": [
      {
        "path": "examples/inputs/public_benchmark/aapl_2024.pdf",
        "role": "primary",
        "mime_type": "application/pdf"
      }
    ],
    "goal": "Extract financial statement tables with evidence and validation logs.",
    "options": {
      "backend": "pipeline",
      "method": "txt",
      "lang": "en",
      "start_page": 31,
      "end_page": 36
    }
  }'
```

响应形态与 HTML 任务一致；任务完成后，`result.json` 会包含结构化财务表、质量诊断和 trace 路径。
