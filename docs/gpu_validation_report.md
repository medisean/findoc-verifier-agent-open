# GPU 验证报告

本报告记录一次干净 Colab GPU 环境中的 MinerU pipeline OCR 验证。运行目标是复核真实中文年报全量 OCR
能力，以及短页窗批量任务在并发 2 和并发 3 下的稳定性。

结构化摘要见 `examples/gpu_validation_evidence_report.json`。完整材料包中还保留以下轻量 evidence
压缩包：

- `annuals_and_stress_evidence-2.tgz`
- `annuals_and_stress_evidence-3.tgz`

包内保留每个任务的 `plan.json`、`trace.jsonl`、`result.json` 和服务日志，未包含体积较大的 MinerU
原始中间目录。

## 环境

| 项 | 配置 |
| --- | --- |
| Runtime | Google Colab GPU runtime |
| GPU 观测 | 15 GB 显存；并发 1 时约 3 GB 显存占用 |
| 解析后端 | MinerU pipeline OCR |
| 模型来源 | ModelScope 本地缓存，`MINERU_MODEL_SOURCE=local` |
| 服务入口 | FastAPI + 后台任务执行器 |
| 状态存储 | SQLite task store |
| 产物目录 | `runs/` |

干净环境初始 smoke 暴露了两个复现问题：MinerU CLI 未装入 `.venv`，以及 OCR 路径缺少 `six`。
随后将 `six>=1.16.0` 固化到 `mineru` 可选依赖和 lock 文件，重新安装后 smoke 任务成功。

## 中文年报 GPU OCR 全量结果

4 份中文公开年报均使用 OCR 全量跑通，硬性一致性失败为 0，证据覆盖均为 1.0。

| Task | Task ID | 表 | 行 | warning | 硬失败 | 数值解析覆盖 | 证据覆盖 | 财务相关表 | 耗时秒 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `cn_byd_2025_annual_report_gpu_ocr` | `97682b5f-a408-453a-b1b0-3da293ad1088` | 281 | 2553 | 121 | 0 | 0.9621 | 1.0000 | 69 | 1263.711 |
| `cn_catl_2025_annual_report_gpu_ocr` | `52d2f30c-58a9-4c0f-8e35-f86ef9ceffbb` | 345 | 2402 | 67 | 0 | 0.9797 | 1.0000 | 61 | 648.769 |
| `cn_moutai_2025_annual_report_gpu_ocr` | `3a87e887-46f1-4dbc-b4bc-4e7fab70fe86` | 251 | 2182 | 33 | 0 | 0.9913 | 1.0000 | 49 | 422.913 |
| `cn_cmb_2025_annual_report_gpu_ocr` | `83c86a18-7927-4438-8d13-a91de7117255` | 291 | 3940 | 180 | 0 | 0.9802 | 1.0000 | 82 | 2130.440 |

warning 主要来自电话号码、技术参数、百分比说明、合并单元格和单位/期间需要上下文补全的情形；
这些 warning 没有触发硬性数值失败。

## 批量稳定性结果

压测使用 4 份中文年报的 0-1 页 OCR 短页窗任务。每轮提交 12 个任务，保留独立 `plan.json`、
`trace.jsonl` 和 `result.json`。

| 并发 | 任务数 | 成功 | 失败 | 成功率 | 总墙钟秒 | 单任务耗时最小 | 单任务耗时均值 | 单任务耗时最大 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2 | 12 | 12 | 0 | 100% | 317.988 | 55.607 | 186.456 | 317.720 |
| 3 | 12 | 12 | 0 | 100% | 301.488 | 71.784 | 185.760 | 301.152 |

结论：在该 Colab GPU 环境中，短页窗 OCR 任务在并发 2 和并发 3 下均保持 100% 成功率。
全量年报建议保守使用并发 1，以减少长文档任务之间的显存和中间文件峰值干扰；短页窗批量任务可以按
2-3 并发运行。
