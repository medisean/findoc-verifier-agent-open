# 稳定性与恢复专项报告

## 目标

本报告记录 Agent 在本地单节点环境中的任务持久化、失败隔离、错误分类和恢复证据。
这些检查不依赖 GPU 或 MinerU 模型，适合在每次发布前快速复核工程边界。

## 快速复现

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/run_stability_smoke.py --clean
```

脚本会生成：

- `runs/stability_smoke/report.json`
- `runs/stability_smoke/stability-missing-*/plan.json`
- `runs/stability_smoke/stability-missing-*/trace.jsonl`
- `runs/stability_smoke/stability-missing-*/result.json`

## 覆盖场景

| 场景 | 检查点 | 预期 |
| --- | --- | --- |
| 任务状态持久化 | 创建任务、保存 running 状态、保存失败结果、重新打开存储 | 请求、状态和结果均可恢复 |
| 并发失败隔离 | 3 个缺失输入任务并发执行 | 每个任务独立失败，并产生独立产物 |
| 计划与日志完整性 | 检查 `plan.json`、`trace.jsonl`、`result.json` | 每个任务均完整写出 |
| 错误分类矩阵 | missing input、模型缓存缺失、模型配置缺失、远端不可用、资源不足、超时 | 分类结果与恢复策略一致 |

## 错误分类与恢复动作

| 类型 | 触发信号 | 恢复动作 |
| --- | --- | --- |
| `missing_input` | 本地文件不存在 | 终止当前任务，保留失败结果和 trace |
| `model_cache_unavailable` | 模型 snapshot 不存在或下载失败 | 检查本地模型缓存，或切换可用模型源 |
| `model_config_missing` | `mineru.json` 模型映射缺失 | 创建本地模型映射，或切远端 hybrid backend |
| `remote_backend_unavailable` | 远端连接失败 | 回退本地 pipeline，或检查远端健康状态 |
| `resource_exhausted` | OOM 或资源不足 | 缩小页窗、降低并发、切远端服务 |
| `timeout` | 工具调用超时 | 缩小页窗或增加 worker 超时 |

## 全量验证证据

最新本地 macOS CPU 全量验证已完成 4 份中文公开年报：

| Task | 表 | 行 | 硬失败 | 数值解析覆盖 | 证据覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: |
| `cn_byd_2025_annual_report` | 278 | 2540 | 0 | 0.9660 | 1.0 |
| `cn_catl_2025_annual_report` | 344 | 2397 | 0 | 0.9799 | 1.0 |
| `cn_moutai_2025_annual_report` | 253 | 2185 | 0 | 0.9913 | 1.0 |
| `cn_cmb_2025_annual_report` | 262 | 3942 | 0 | 0.9800 | 1.0 |

4 份结果均通过 gold metrics evaluator，关键表、关键指标和证据要求均满足。

## 结论

当前版本已经覆盖本地持久化、异常隔离、错误分类、可解释计划和全量结果复核。
生产多进程环境建议继续使用 PostgreSQL/MySQL + Redis/Celery/RQ 或云队列替换本地 SQLite 边界。
