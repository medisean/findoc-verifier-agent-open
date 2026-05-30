# 公开金融样本测试结果

本组测试新增 4 份来自 AnnualReports 的公开年报 PDF。本地环境使用 CPU 可承受的页码范围，
重点覆盖核心财务报表页，用于验证跨公司、跨版式的泛化能力。

## 样本和页码范围

| 样本 | 文件 | 页数 | 测试页段 | 说明 |
| --- | --- | ---: | --- | --- |
| Apple 2024 Form 10-K | `aapl_2024.pdf` | 121 | 31-36 | 核心财务报表 |
| Walmart 2024 Annual Report | `wmt_2024.pdf` | 97 | 55-60 | 核心财务报表 |
| NVIDIA 2024 Form 10-K | `nvda_2024.pdf` | 187 | 149-154 | 核心财务报表 |
| JPMorgan Chase 2024 Annual Report | `jpm_2024.pdf` | 372 | 205-210 | 核心财务报表 |

本地文件位于 `examples/inputs/public_benchmark/`，不纳入版本控制。

## 结果汇总

| Task | 表 | 行 | warning | 硬失败 | 风险 | 数值解析覆盖 | 财务表 |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `public-aapl-2024-financials` | 5 | 136 | 3 | 0 | medium | 0.9926 | 5 |
| `public-wmt-2024-financials` | 5 | 154 | 4 | 0 | medium | 0.9896 | 5 |
| `public-nvda-2024-financials` | 5 | 134 | 10 | 0 | medium | 0.9660 | 5 |
| `public-jpm-2024-financials` | 6 | 174 | 4 | 0 | medium | 0.9887 | 6 |

四个样本均成功解析，硬性数值一致性失败为 0。NVIDIA 的 warning 较多，主要原因是多个数值被合并到
同一单元格，以及部分括号负数需要恢复。

## 本地横评

同一组海外公开样本的核心页窗已完成三组方法横评：传统 `pdfplumber` baseline、MinerU
`pipeline/txt` 直接解析和 FinDoc Agent。横评共覆盖 4 个任务、24 页，机器可读结果见
`examples/benchmark_results/standard_table_benchmark_summary.json`。

| 方法 | 表 | 行 | 期望通过率 | 数值解析覆盖 | 证据覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `pdfplumber_traditional` | 6 | 129 | 0.3750 | 1.0000 | 1.0000 |
| `mineru_pipeline_txt_direct` | 23 | 603 | 1.0000 | 0.9891 | 1.0000 |
| `findoc_agent` | 21 | 598 | 1.0000 | 0.9842 | 1.0000 |

FinDoc Agent 相比传统 baseline 多结构化 15 张表、469 行；相比 MinerU 直接解析保持同等期望通过率，
并补充任务计划、质量诊断、修复闭环和 trace 产物。

## 发现和修复效果

新增样本暴露了混合括号负数问题，例如 `（160)`、`（48)`。当前 `parse_number()` 已支持全角/半角
括号混用，并能处理缺失右括号的负数。

解析增强后的 warning 变化：

| 样本 | 修复前 | 修复后 |
| --- | ---: | ---: |
| Apple | 4 | 3 |
| Walmart | 5 | 4 |
| NVIDIA | 16 | 10 |
| JPMorgan Chase | 5 | 4 |

## 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
  runs/public-aapl-2024-financials/result.json \
  examples/evaluation_expectations.yaml
```

替换 `task_id` 即可评测 Walmart、NVIDIA 或 JPMorgan Chase 样本。

## 中国公开年报扩展样本

新增中国上市公司公开年报样本分析，见 `docs/china_public_annual_report_analysis.md`。仓库已包含
比亚迪、宁德时代、贵州茅台和招商银行 2025 年年度报告 PDF，并记录公开披露入口、关键指标、推荐
任务 ID、页数、SHA256 和解析风险点。

本地 macOS CPU 环境已完成 4 份中文年报全量 PDF 验证，MinerU 使用本地 ModelScope pipeline
模型缓存，服务端任务并发限制为 1。

| Task | 页数 | 表 | 行 | warning | 硬失败 | 数值解析覆盖 | 证据覆盖 | 财务相关表 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cn_byd_2025_annual_report` | 268 | 278 | 2540 | 107 | 0 | 0.9660 | 1.0000 | 68 |
| `cn_catl_2025_annual_report` | 232 | 344 | 2397 | 63 | 0 | 0.9799 | 1.0000 | 62 |
| `cn_moutai_2025_annual_report` | 143 | 253 | 2185 | 33 | 0 | 0.9913 | 1.0000 | 51 |
| `cn_cmb_2025_annual_report` | 350 | 262 | 3942 | 183 | 0 | 0.9800 | 1.0000 | 78 |

4 份样本均全量成功，硬性一致性失败为 0。warning 主要来自电话号码、技术参数、百分比说明、
多数值合并单元格和部分单位/期间需要从邻近文本补全；这些 warning 不影响硬性数值校验通过率。

## Colab GPU OCR 复核

同一组中文公开年报已在 Colab GPU 环境中使用 MinerU pipeline OCR 全量复核。4 份样本均成功完成，
硬性一致性失败为 0，证据覆盖均为 1.0。结构化摘要见
`examples/gpu_validation_evidence_report.json`。

| Task | 表 | 行 | warning | 硬失败 | 数值解析覆盖 | 证据覆盖 | 财务相关表 | 耗时秒 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cn_byd_2025_annual_report_gpu_ocr` | 281 | 2553 | 121 | 0 | 0.9621 | 1.0000 | 69 | 1263.711 |
| `cn_catl_2025_annual_report_gpu_ocr` | 345 | 2402 | 67 | 0 | 0.9797 | 1.0000 | 61 | 648.769 |
| `cn_moutai_2025_annual_report_gpu_ocr` | 251 | 2182 | 33 | 0 | 0.9913 | 1.0000 | 49 | 422.913 |
| `cn_cmb_2025_annual_report_gpu_ocr` | 291 | 3940 | 180 | 0 | 0.9802 | 1.0000 | 82 | 2130.440 |

并发 2 和并发 3 的短页窗 OCR 压测各提交 12 个任务，均为 12/12 成功。详见
`docs/gpu_validation_report.md`。

复现命令：

```bash
export MINERU_MODEL_SOURCE=local
export MINERU_MAX_CONCURRENCY=1
UV_CACHE_DIR=.uv-cache uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
python3 scripts/run_cn_full_validation.py --poll-seconds 60 --continue-on-failure
```
