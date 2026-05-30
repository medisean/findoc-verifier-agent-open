# FinDoc Verifier Agent

面向金融文档可靠结构化的 Data Agent，使用 MinerU 作为主要解析工具，并在其上补充任务规划、
工具路由、结构化归一、质量诊断、数值校验、自动修复和可追溯日志。

## 项目目标

FinDoc Verifier Agent 面向年报、审计材料、招股书、扫描件、跨页表格、DOCX 报告以及
PPT/XLSX 附件包等高密度金融文档。系统将 MinerU 作为文档解析工具，再由 Agent 层完成：

- 任务理解与执行计划生成。
- 按输入类型选择本地或远端解析路径。
- 表格、期间、单位、证据字段的结构化归一。
- 数值一致性校验与质量诊断。
- MinerU 失败或低质量结果的自动恢复与复验。
- OCR 数字混淆等低置信问题的确定性修复。
- 修复后的复验、结果打包和 trace 记录。

本项目不是通用聊天机器人，核心场景是把金融报表转成可验证、可复现、可入库的结构化数据。

## 当前能力

- FastAPI 异步任务接口。
- 本地任务状态持久化；生产环境可替换为 PostgreSQL/MySQL 与任务队列。
- 统一的任务、结果和 trace schema。
- Agent planner 与 executor。
- MinerU CLI/API 包装，支持本地 pipeline 和远端 HTTP backend。
- MinerU 失败和低质量结果的自动恢复策略。
- HTML/网页表格原生解析，支持 caption、rowspan / colspan、单位继承和 evidence。
- 复杂图表指标结构化，支持堆叠柱状图、折线图、瀑布图和 annotation 数值。
- 全局指代消解，可将“上述收入”“该增幅”“该比率”“该金额”等叙述引用回指到来源图表指标。
- 扫描件无表格块时的 OCR 叙述型财务指标兜底抽取。
- 低置信数值上下文修复与复验。
- 混合输入任务的动态 DAG 规划，支持 PDF、扫描件和 XLSX/PPT 附件跨文件核验。
- 中文年报关键指标 gold metrics 评测，覆盖数值、单位和证据。
- 6 类核心样例任务、4 份海外公开年报样本和 4 份中国公开年报 PDF。
- 本地标准横评，覆盖传统 PDF 表格 baseline、MinerU 直接解析和 FinDoc Agent 三组方法。
- 复杂版式定向 accuracy，覆盖跨页合并、多级表头、合并单元格展开和密集数字。
- Edge layout 专项，覆盖手写批注噪声、多栏混排、嵌套/多行表头。
- 100 任务本地 soak test，验证并发计划执行、trace/result 写出和输出结构一致性。
- Docker 一键启动 smoke，验证镜像构建、健康检查、API 任务流和持久化产物写出。
- 中国知名上市公司公开年报扩展样本分析与 SHA256 校验。
- 轻量评测器，用于复现 benchmark 结果。

## 架构

```text
Client
  -> FastAPI Task API
  -> Task Planner
  -> Tool Router / MinerU Client
  -> Structure Builder
  -> Financial Verifier
  -> Repair Loop
  -> Result Pack + Trace Logs
```

## 快速启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

推荐 Python 3.11；Python 3.10+ 可运行基础功能。

提交一个任务：

```bash
curl -X POST http://localhost:8000/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "annual-report-smoke",
    "document_type": "annual_report_pdf",
    "inputs": [{"path": "examples/inputs/annual_report.pdf"}],
    "goal": "Extract financial statements with evidence and validation logs."
  }'
```

查询任务：

```bash
curl http://localhost:8000/v1/tasks/{task_id}
curl http://localhost:8000/v1/tasks/{task_id}/result
```

任务产物写入：

- `runs/{task_id}/plan.json`：文档画像、执行计划、步骤依赖、成功条件和恢复动作。
- `runs/{task_id}/trace.jsonl`：阶段级执行日志。
- `runs/{task_id}/result.json`：结构化结果包。

## Docker 一键启动

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build -d
curl http://127.0.0.1:8000/health
```

该方式默认持久化 `./runs`，并通过容器健康检查确认 API 可用。`.env.docker` 中的 `PORT`
表示宿主机端口，容器内 API 固定监听 `8000`。生产 OCR/GPU 负载建议在 `.env.docker`
中配置 `MINERU_ENDPOINT` 指向远端 MinerU 服务。完整说明见
`docs/production_deployment.md`。

## MinerU 运行说明

安装依赖：

```bash
uv sync --extra dev --extra mineru
```

首次下载模型：

```bash
uv run mineru-models-download -s huggingface -m pipeline
```

如果服务器无法访问 HuggingFace，切换到 ModelScope：

```bash
export MINERU_MODEL_SOURCE=modelscope
uv run mineru-models-download -s modelscope -m pipeline
export MINERU_MODEL_SOURCE=local
```

PDF 和图片默认走 MinerU `pipeline`。文本层 PDF 默认 `method=txt`；扫描 PDF 或图片默认
`method=ocr`。任务中的显式 `options` 会覆盖默认值。

本地无 GPU 也可以跑 DOCX/PPTX/XLSX 和小页段 PDF。CPU 跑大 PDF 时建议先限制页码范围：

```json
{"backend": "pipeline", "method": "txt", "start_page": 48, "end_page": 52}
```

如需远端验证，可设置 `MINERU_ENDPOINT`，或在任务 `options` 中传入
`backend=hybrid-http-client` / `backend=vlm-http-client` 和 `server_url`。

完整部署说明见 `docs/deployment.md`。

## 样例任务

核心样例覆盖：

1. 年报 PDF。
2. 扫描财务报表 PDF。
3. 跨页财务表 PDF。
4. DOCX 管理或审计报告。
5. PPT/XLSX 附件包。
6. HTML 财务表格。
7. 复杂图表与全局指代消解样本。

样例清单见 `examples/sample_tasks.yaml` 和 `examples/inputs/README.md`。
中国公开年报样本位于 `examples/inputs/public_benchmark_cn/`。
稳定性恢复证据见 `docs/stability_recovery_report.md`；低质量扫描、跨页续表和密集数字脚注样本见
`docs/adversarial_benchmark_report.md`。

本地或服务器全量验证中国公开年报：

```bash
python3 scripts/run_cn_full_validation.py
```

本地横评传统 baseline、MinerU 直接解析和 FinDoc Agent：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_standard_benchmark.py --clean
```

复杂版式 accuracy、adversarial 汇总和本地 soak：

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_layout_accuracy_benchmark.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_adversarial_evaluation.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_edge_layout_benchmark.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_soak_test.py --clean --task-count 100 --concurrency 8
```

## 项目文档

- 代码与测试：`app/`、`tests/`。
- 部署说明：`docs/deployment.md`。
- Docker 一键生产部署：`docs/production_deployment.md`。
- Docker smoke 验证：`docs/docker_smoke_report.md`。
- API 说明：`docs/api.md`。
- API 请求与响应示例：`docs/api_examples.md`。
- 评测说明：`docs/evaluation.md`。
- 公开样本测试：`docs/public_benchmark_results.md`。
- 标准横评报告：`docs/standard_benchmark_report.md`、
  `examples/benchmark_results/standard_table_benchmark_summary.json`。
- 复杂版式 accuracy：`docs/layout_accuracy_report.md`、
  `examples/benchmark_results/layout_accuracy_summary.json`。
- Edge layout 专项：`docs/edge_layout_benchmark_report.md`、
  `examples/benchmark_results/edge_layout_summary.json`。
- 100 任务 soak：`docs/soak_test_report.md`、
  `examples/benchmark_results/soak_test_summary.json`。
- 中国公开年报扩展样本：`docs/china_public_annual_report_analysis.md`。
- GPU 年报与并发验证：`docs/gpu_validation_report.md`、
  `examples/gpu_validation_evidence_report.json`。
- 稳定性恢复证据：`docs/stability_recovery_report.md`。
- 极端样本测试：`docs/adversarial_benchmark_report.md`。
- Agent 规划与上下文修复证据：`docs/p0_agent_planning_and_context_repair.md`。
- Agent 能力证据包：`docs/agent_capability_evidence.md`。
- 技术报告：`docs/technical_report.md`。
- 开源发布说明：`docs/open_source_release.md`。

## 开源许可

项目使用 Apache License 2.0，详见 `LICENSE` 和 `NOTICE`。
公开发布范围、样本来源和不包含内容见 `docs/open_source_release.md`。
