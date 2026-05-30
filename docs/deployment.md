# 部署说明

本文档说明如何在新环境中复现 FinDoc Verifier Agent：安装依赖、下载 MinerU 模型、启动 API、
运行样例任务并查看日志。

## 1. 环境要求

- Python 3.10+，推荐 Python 3.11。
- macOS、Linux 或标准 Python 服务器环境。
- 本地 CPU 可运行 Office 文档测试和小页段 PDF 测试。
- 大批量 OCR 或超长 PDF 建议使用 GPU 或远端 MinerU 服务。
- 推荐使用 `uv` 管理依赖和命令。

## 2. 安装依赖

```bash
uv sync --extra dev --extra mineru
```

如果只运行 API skeleton 和单元测试，可以不安装 `--extra mineru`。如果要解析真实 PDF、图片、
DOCX、PPTX 或 XLSX，应安装 MinerU extra。

## 3. 下载 MinerU 模型

本地默认 backend 是 MinerU pipeline：

```bash
uv run mineru-models-download -s huggingface -m pipeline
```

如果服务器无法访问 HuggingFace，使用 ModelScope 下载：

```bash
export MINERU_MODEL_SOURCE=modelscope
uv run mineru-models-download -s modelscope -m pipeline
export MINERU_MODEL_SOURCE=local
```

下载后确认 `~/mineru.json` 指向 pipeline 模型目录。检测到本地模型后，`MinerUClient` 会自动设置
`MINERU_MODEL_SOURCE=local`，一般不需要逐任务配置。

参考资料：

- <https://opendatalab.github.io/MinerU/usage/model_source/>
- <https://opendatalab.github.io/MinerU/usage/quick_usage/>

## 4. 启动 API

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://localhost:8000/health
```

任务状态默认持久化到 `runs/tasks.sqlite3`。这是本地开发和单节点复现的零依赖后端；生产多进程或
多副本部署建议将 `TaskStore` 边界替换为 PostgreSQL/MySQL，并配合 Redis、Celery、RQ 或云队列
承载后台任务。可以用 `TASK_STORE_PATH=/path/to/tasks.sqlite3` 改变本地存储位置。

每个任务会额外写出 `runs/<task_id>/plan.json`，其中包含文档画像、推荐解析路径、步骤依赖、
成功条件和失败恢复动作。`trace.jsonl` 继续记录实际工具调用、耗时、错误分类和质量恢复决策。

创建任务：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "annual-report-smoke",
    "document_type": "annual_report_pdf",
    "inputs": [{"path": "examples/inputs/annual_report.pdf"}],
    "goal": "Extract financial statements with evidence and validation logs.",
    "options": {"backend": "pipeline", "method": "txt", "start_page": 48, "end_page": 52}
  }'
```

查询状态和结果：

```bash
curl http://localhost:8000/v1/tasks/{task_id}
curl http://localhost:8000/v1/tasks/{task_id}/result
```

## 5. Docker 一键生产部署

仓库提供 `Dockerfile`、`docker-compose.yml` 和 `.env.docker.example`。单节点生产参考部署：

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build -d
curl http://127.0.0.1:8000/health
```

默认会将宿主机 `./runs` 挂载到容器 `/data/runs`，保留任务状态和 `plan.json` / `trace.jsonl` /
`result.json`。如果本机 `8000` 已被占用，可把 `.env.docker` 中的 `PORT` 改为其他宿主机端口；
容器内 API 固定监听 `8000`。本地 Docker smoke 记录见 `docs/docker_smoke_report.md`。
如需接入远端 MinerU，在 `.env.docker` 中设置：

```bash
MINERU_ENDPOINT=http://your-mineru-server:30000
MINERU_MAX_CONCURRENCY=1
```

完整生产部署说明见 `docs/production_deployment.md`。

## 6. MinerU 路由策略

- 文本层 PDF 默认 `backend=pipeline`、`method=txt`。
- 扫描 PDF 和图片默认 `backend=pipeline`、`method=ocr`。
- DOCX、PPTX、XLSX 走 Office 文档解析路径。
- 多输入任务会处理所有本地 `path` 输入，包括 primary、attachment 和 reference。
- 显式 `options` 始终优先于自动路由。
- 默认开启自动恢复：pipeline/text 失败会尝试 OCR；配置远端 `server_url` 或 `MINERU_ENDPOINT`
  后会尝试 hybrid HTTP backend；高风险低质量结果可触发备用解析并只接受更优结果。
- 默认 `MINERU_MAX_CONCURRENCY=1`，同一服务进程串行调用 MinerU，避免大 PDF 并发压垮 GPU 或远端服务。

如需远端验证，可切换 HTTP backend：

```json
{
  "backend": "hybrid-http-client",
  "server_url": "http://your-mineru-server:30000"
}
```

也可以通过环境变量提供默认服务：

```bash
export MINERU_ENDPOINT=http://your-mineru-server:30000
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 7. 日志和产物

每个任务会写入独立目录：

```text
runs/<task_id>/
  trace.jsonl
  result.json
  mineru/
```

`trace.jsonl` 包含任务输入、执行阶段、工具参数、MinerU 输出、耗时和错误信息。
`result.json` 包含结构化表格、证据引用、质量指标、修复记录和最终摘要。

## 8. 验证命令

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q
```

当前本地验证覆盖 MinerU 路由、表格归一、OCR 兜底、评测器和自动修复逻辑。

代表性评测命令：

```bash
UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
  runs/annual_report_pdf-full-local/result.json \
  examples/evaluation_expectations.yaml

UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
  runs/public-aapl-2024-financials/result.json \
  examples/evaluation_expectations.yaml
```

中国公开年报全量验证可以使用可恢复脚本：

```bash
python3 scripts/run_cn_full_validation.py
```

脚本会读取 `runs/cn_full_validation_task_map.json`，已经成功生成 `result.json` 的文档不会重复提交；
失败或缺少结果的文档默认会重新提交。远端 MinerU 可传入：

```bash
python3 scripts/run_cn_full_validation.py --server-url http://your-mineru-server:30000
```

本地稳定性 smoke 不依赖 MinerU 模型，适合在提交前快速验证任务持久化、并发执行边界、
计划写出和失败结果落盘：

```bash
UV_CACHE_DIR=.uv-cache uv run python scripts/run_stability_smoke.py --clean
```

## 9. 常见问题

- 首次解析 PDF 慢：模型加载和下载需要时间，可先用较小 `start_page/end_page` 预热。
- `LocalEntryNotFoundError` 且日志包含 `opendatalab/PDF-Extract-Kit-1.0`：说明模型没有下载完整，
  或当前机器访问 HuggingFace 失败。优先用 `mineru-models-download -s modelscope -m pipeline`
  下载模型，再设置 `MINERU_MODEL_SOURCE=local` 后重跑。
- 扫描件没有表格块：系统会回退到 OCR 叙述型指标抽取，并保留 page/bbox 证据。
- 大 PDF 有 warning：warning 表示单位缺失、OCR 歧义或证据风险等非阻塞问题，不等于硬性数值失败。
- 远端验证失败：检查 `server_url`、`MINERU_ENDPOINT`、网络连通性和 MinerU 服务版本。
