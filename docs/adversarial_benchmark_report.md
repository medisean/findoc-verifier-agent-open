# Adversarial Benchmark Report

## 目标

adversarial benchmark 用于补充真实公开年报之外的小型极端样本。样本由脚本确定性生成，
不依赖外部版权数据，适合快速验证低质量扫描、跨页续表、密集数字和脚注干扰等边界情况。

## 生成样本

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/build_adversarial_fixtures.py
```

输出：

- `examples/inputs/adversarial/*.pdf`
- `examples/adversarial_results/*.json`
- `examples/adversarial_manifest.json`
- `examples/adversarial_expectations.yaml`

## 样本清单

| Task | 输入 | 难点 | Gold 指标 |
| --- | --- | --- | --- |
| `adversarial_low_light_scan` | `low_light_blurred_scan.pdf` | 模糊、轻微倾斜、亮度不均、OCR 数字风险 | Revenue 2025 = 2450；Operating income 2025 = 610 |
| `adversarial_cross_page_unit` | `cross_page_unit_header_shift.pdf` | 跨页续表、单位继承、括号负数 | Operating cash flow 2025 = 183200；Ending cash 2025 = 271900 |
| `adversarial_dense_numeric_footnotes` | `dense_numeric_footnote_table.pdf` | 密集金额、百分比、脚注符号、括号负数 | Revenue 2025 = 12567；Net income 2024 = -512 |

## 快速评测

gold result fixture 可用于不启动 MinerU 的快速 evaluator 回归：

```bash
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

预期 3 个任务均为 `score=1.0`。

## 结果表

结构化汇总见 `examples/benchmark_results/adversarial_summary.json`。

| Task | status | score | 表 | 行 | required metrics | hard fail | 数值解析覆盖 | 证据覆盖 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `adversarial_low_light_scan` | pass | 1.0000 | 1 | 3 | 2/2 | 0 | 1.0000 | 1.0000 |
| `adversarial_cross_page_unit` | pass | 1.0000 | 1 | 3 | 2/2 | 0 | 1.0000 | 1.0000 |
| `adversarial_dense_numeric_footnotes` | pass | 1.0000 | 1 | 3 | 2/2 | 0 | 1.0000 | 1.0000 |

汇总：3 个任务全部通过，6 个 required metrics 全部命中，硬失败为 0。

## 真实解析验证

需要验证 MinerU 真实解析时，可通过 API 提交样本：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "adversarial_low_light_scan",
    "document_type": "scanned_financial_statement_pdf",
    "inputs": [{"path": "examples/inputs/adversarial/low_light_blurred_scan.pdf"}],
    "goal": "Extract financial metrics with evidence and validation logs.",
    "options": {"backend": "pipeline", "method": "ocr", "lang": "en"}
  }'
```

跨页和密集数字样本可将 `document_type` 分别设为 `cross_page_table_pdf` 和 `annual_report_pdf`。

## 结论

该小型 suite 与中文年报全量验证互补：中文年报证明真实复杂大文档吞吐与准确性，
adversarial 样本证明边界场景的可验证性和回归测试能力。
