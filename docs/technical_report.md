# FinDoc Verifier Agent 技术报告

## 1. 摘要

FinDoc Verifier Agent 是一个面向高价值金融文档的数据处理服务。系统将年报、审计材料、
扫描件和 Office 附件转换为结构化表格，并保留字段证据、质量诊断、修复记录和阶段级执行日志。

系统使用 MinerU 作为主要解析引擎，并在其上构建 Agent 工作流：任务规划、工具路由、表格归一、
财务校验、确定性修复和可复现结果打包。产品重点不是开放域问答，而是生成可审计、可复盘的可靠金融数据。

## 2. 产品范围

当前版本覆盖六类常见金融文档处理难点：

- 高密度年报财务报表。
- 存在 OCR 歧义的扫描财务材料。
- 跨页财务表格。
- DOCX 管理或审计报告。
- PPT/XLSX 附件包中的重复指标。
- HTML/网页表格中的多级表头、合并单元格和单位继承。
- 复杂图表中的指标抽取，以及正文对图表指标的全局指代消解。

每个完成任务都会返回结构化表格、行级证据、质量诊断、修复记录和可复盘执行日志。

## 3. 系统设计

### 3.1 核心组件

- `FastAPI` 提供异步任务创建、状态查询和结果查询。
- `TaskStore` 持久化任务、请求和结果；本地默认 SQLite，生产可替换为外部数据库和任务队列。
- `DocumentProfiler` 先生成输入画像，记录文件类型、大小、扫描线索、中文财报线索和推荐解析策略。
- `TaskPlanner` 根据文档画像、文档类型和目标生成可解释执行计划。
- `MinerUClient` 将解析请求路由到本地 pipeline 模型或远端 HTTP backend。
- `NativeHtmlParser` 直接处理 HTML/网页表格，保留 caption、单位、期间和 evidence。
- `materialize_tables()` 将解析块转换为稳定的金融表格 schema。
- `verify_tables()` 检查数值一致性、缺失字段、证据覆盖和解析风险。
- `repair_numeric_cells()` 修复确定性的 OCR 数字混淆，并触发复验。
- `evaluate_result()` 将任务结果与记录好的 benchmark 期望值对齐。

### 3.2 执行流程

1. 接收任务请求并保存任务元数据。
2. 对输入做文档画像，生成 `plan.json`，记录每一步的依赖、成功条件、失败动作和路由原因。
3. 按画像选择文本层、OCR、附件展开或大文档预检查策略，并使用选定 backend 和页码范围调用 MinerU。
4. 当 MinerU 失败或质量诊断高风险时，先分类失败原因，再按策略尝试受影响页 OCR、远端 hybrid 或本地 pipeline fallback。
5. 将解析内容归一为结构化金融表格。
6. 执行财务校验和质量诊断。
7. 对可恢复的问题执行确定性数值修复。
8. 对修复后的值重新校验。
9. 打包 `result.json`、`trace.jsonl` 和摘要指标。

## 4. Agent 能力

系统重点体现以下生产级文档自动化能力：

- 规划：按 PDF、扫描件、DOCX、PPTX、XLSX 等输入选择处理路径，并记录画像驱动的决策原因。
- 混合任务 DAG：当任务包含 PDF、扫描件和 Office 附件等多输入时，计划会按输入生成并行解析分支，
  执行 trace 会使用对应的 `parse_input_*` 分支阶段名，再汇入共享上下文推断和跨文件指标核验节点。
- 工具调用：显式记录 MinerU backend、OCR/text 模式和页码范围。
- HTML 结构化：`.html/.htm` 输入走原生解析路径，不依赖 OCR 或外部模型，支持 rowspan / colspan 展开。
- 图表结构化：chart block 可转为统一指标表，覆盖堆叠柱状图、折线图、瀑布图和 annotation 数值。
- 全局指代消解：正文中的“上述收入”“该增幅”“该比率”“该金额”等短语会回指到候选图表或表格指标，
  并在 evidence 中记录来源页、目标行、期间、单位和置信度。
- 自动恢复：解析失败时识别模型缓存、模型配置、资源不足、远端不可用、超时和缺失输入等错误类型；低质量时优先尝试受影响页重跑，并只接受更优结果。
- 校验：执行数值一致性校验，并输出证据覆盖、解析覆盖等诊断。
- 修复与恢复：记录 OCR 数字修复前后的值，并保留单位、期间、行标签、peer value 和 evidence 等上下文证据。
- 可追溯：以 JSONL 记录每个阶段，支持复盘、失败定位和审计。

`plan.json` 保存可解释计划和文档画像。
混合输入任务的 `plan.json` 还包含 `graph` 字段，记录 DAG 边、并行组、节点数和 `is_dag` 检查结果。
`trace.jsonl` 记录任务输入、计划动作、工具参数、耗时、校验输出、修复事件和完成状态。
`result.json` 保存最终结构化结果包。

## 5. Benchmark 覆盖

### 5.1 核心任务

| Task | 表 | 行 | 硬失败 | 校验通过率 | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| `annual_report_pdf-full-local` | 58 | 632 | 0 | 1.0 | 年报全量抽取 |
| `cross_page_table_pdf-full-local` | 58 | 627 | 0 | 1.0 | 跨页续表合并 |
| `scanned_financial_statement_pdf-ocr-fallback` | 1 | 2 | 0 | 1.0 | OCR 叙述指标兜底 |
| `docx_management_report-latest-smoke` | 1 | 3 | 0 | 1.0 | DOCX 表格抽取 |
| `ppt_xlsx_attachment_pack-multi-smoke` | 3 | 11 | 0 | 1.0 | 多文件附件解析 |
| `html_native_parse` | 1 | 2 | 0 | 1.0 | HTML 原生表格解析 |
| `chart_reference_resolution` | 4 | 16 | 0 | 1.0 | 复杂图表与全局指代消解 |

新增混合任务计划样例 `mixed_financial_verification_pack` 会针对 PDF 年报、扫描财务材料和 XLSX
附件生成动态 DAG，用于证明多输入任务规划、共享上下文和跨文件核验能力。该能力由
`tests/test_executor.py::test_mixed_document_plan_builds_dynamic_dag` 和
`tests/test_executor.py::test_mixed_executor_trace_follows_dynamic_plan` 覆盖。

### 5.2 公开金融报表样本

| Task | 表 | 行 | 硬失败 | 校验通过率 | 说明 |
| --- | ---: | ---: | ---: | ---: | --- |
| `public-aapl-2024-financials` | 5 | 136 | 0 | 1.0 | Apple 2024 核心财务报表页 |
| `public-wmt-2024-financials` | 5 | 154 | 0 | 1.0 | Walmart 2024 核心财务报表页 |
| `public-nvda-2024-financials` | 5 | 134 | 0 | 1.0 | NVIDIA 2024 高密度表格页 |
| `public-jpm-2024-financials` | 6 | 174 | 0 | 1.0 | JPMorgan Chase 2024 核心财务报表页 |

### 5.3 中国公开年报全量样本

| Task | 表 | 行 | 硬失败 | 数值解析覆盖 | 财务相关表 | 说明 |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `cn_byd_2025_annual_report` | 278 | 2540 | 0 | 0.9660 | 68 | 比亚迪 2025 年报全量 PDF |
| `cn_catl_2025_annual_report` | 344 | 2397 | 0 | 0.9799 | 62 | 宁德时代 2025 年报全量 PDF |
| `cn_moutai_2025_annual_report` | 253 | 2185 | 0 | 0.9913 | 51 | 贵州茅台 2025 年报全量 PDF |
| `cn_cmb_2025_annual_report` | 262 | 3942 | 0 | 0.9800 | 78 | 招商银行 2025 年报全量 PDF |

4 份中文年报均完成全量验证，行级证据覆盖为 1.0，硬性数值一致性失败为 0。

### 5.4 GPU OCR 与并发复核

Colab GPU 环境完成了 4 份中文公开年报的 MinerU pipeline OCR 全量复核；4 个任务全部成功，
硬性一致性失败为 0，证据覆盖均为 1.0。同时完成并发 2 和并发 3 的短页窗 OCR 压测，
每轮 12 个任务，均为 12/12 成功。完整指标见 `docs/gpu_validation_report.md` 和
`examples/gpu_validation_evidence_report.json`。

### 5.5 标准横评

本地标准横评使用 4 份公开英文年报的核心财务页窗，共 24 页，对比传统 PDF 表格抽取 baseline、
MinerU pipeline/txt 直接解析和 FinDoc Agent。

| 方法 | 任务数 | 成功 | 表 | 行 | 硬失败 | 期望通过率 | 数值解析覆盖 | 证据覆盖 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `pdfplumber_traditional` | 4 | 4 | 6 | 129 | 0 | 0.3750 | 1.0000 | 1.0000 |
| `mineru_pipeline_txt_direct` | 4 | 4 | 23 | 603 | 0 | 1.0000 | 0.9891 | 1.0000 |
| `findoc_agent` | 4 | 4 | 21 | 598 | 0 | 1.0000 | 0.9842 | 1.0000 |

FinDoc Agent 相比传统 baseline 多结构化 15 张表、469 行，期望检查平均提升 0.6250。与 MinerU
直接解析相比，Agent 的纯抽取通过率保持一致，同时提供任务规划、质量诊断、修复闭环、trace 和
API 生命周期。完整结果见 `docs/standard_benchmark_report.md` 和
`examples/benchmark_results/standard_table_benchmark_summary.json`。

### 5.6 复杂版式 Accuracy 与 Soak

复杂版式定向 accuracy 覆盖 HTML 多级表头和 `rowspan/colspan` 展开、跨页续表和单位继承、
密集数字脚注和括号负数。3 个 case 全部通过。

| 指标 | 结果 |
| --- | ---: |
| header precision / recall | 1.0000 / 1.0000 |
| row precision / recall | 1.0000 / 1.0000 |
| numeric exact match | 1.0000 |
| cross-page merge accuracy | 1.0000 |
| unit inheritance accuracy | 1.0000 |

本地 100 任务 control-plane soak 使用 HTML 原生解析路径，验证任务规划、并发执行和产物写出。

| 指标 | 结果 |
| --- | ---: |
| 任务数 | 100 |
| 并发 | 8 |
| 成功率 | 1.0000 |
| plan/trace/result coverage | 1.0000 |
| output shape consistency | 1.0000 |
| hard failures | 0 |

Adversarial fixture 汇总：3 个任务全部通过，6 个 required metrics 全部命中，硬失败为 0。
Edge layout 专项覆盖手写批注、多栏混排和嵌套/多行表头，3 个 case 全部通过，
7 个 required metrics 全部命中，硬失败为 0；其中批注噪声排除、阅读顺序、嵌套表头和
合并单元格展开指标均为 1.0000。
详见 `docs/layout_accuracy_report.md`、`docs/edge_layout_benchmark_report.md`、
`docs/soak_test_report.md` 和
`docs/adversarial_benchmark_report.md`。

### 5.7 Docker Smoke

本地 Docker Desktop 环境完成一键启动和 API 任务流验证。镜像从零构建后以
`INSTALL_MINERU=false` 轻量 API 模式启动，宿主机端口 `18080` 映射到容器 `8000`，
健康检查返回 `{"status":"ok","service":"FinDoc Verifier Agent"}`。随后提交 HTML 财务表格任务
`docker-html-smoke`，任务状态为 `succeeded`，表格数 1、行数 2、数字解析覆盖 1.0000、
evidence 覆盖 1.0000、校验通过率 1.0000，且 `plan.json`、`trace.jsonl`、`result.json`
均写入 `/data/runs`。完整记录见 `docs/docker_smoke_report.md`。

### 5.8 复现命令

代码检查和测试：

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check .
UV_CACHE_DIR=.uv-cache uv run python -m pytest -q
UV_CACHE_DIR=.uv-cache uv run python scripts/run_stability_smoke.py --clean
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_standard_benchmark.py --clean
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_layout_accuracy_benchmark.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_adversarial_evaluation.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_edge_layout_benchmark.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_soak_test.py --clean --task-count 100 --concurrency 8
UV_CACHE_DIR=.uv-cache uv run python scripts/build_adversarial_fixtures.py
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build -d
curl http://127.0.0.1:8000/health
docker compose --env-file .env.docker down
rm -f .env.docker
```

单任务评测：

```bash
UV_CACHE_DIR=.uv-cache uv run python -m app.agent.evaluator \
  runs/annual_report_pdf-full-local/result.json \
  examples/evaluation_expectations.yaml
```

每个 benchmark 的等价评测方式见 `docs/evaluation.md`。

稳定性恢复证据见 `docs/stability_recovery_report.md`。
小型极端样本证据见 `docs/adversarial_benchmark_report.md`。
Agent 规划与上下文修复证据见 `docs/p0_agent_planning_and_context_repair.md`。
Agent 能力证据包见 `docs/agent_capability_evidence.md` 和 `examples/capability_evidence_report.json`。

## 6. 部署与运行模型

- 本地 CPU 可运行 smoke test、Office 文档解析和小页段 PDF。
- 本地 MinerU pipeline 模型可支持文本层 PDF 和 OCR 验证。
- 远端 MinerU HTTP backend 可支持更大的 OCR 任务或集中部署。
- 页码范围参数支持先低成本验证，再扩展到完整文档处理。
- Docker Compose 单节点生产参考部署已补齐，支持一键启动、健康检查、持久化 `runs/` 和远端 MinerU 配置。
- Docker smoke 已通过，覆盖镜像构建、健康检查、任务创建、状态查询、结果查询和产物写出。

相关说明：

- `docs/deployment.md`
- `docs/production_deployment.md`
- `docs/docker_smoke_report.md`
- `docs/api.md`
- `docs/api_examples.md`
- `docs/evaluation.md`
- `docs/standard_benchmark_report.md`
- `docs/layout_accuracy_report.md`
- `docs/edge_layout_benchmark_report.md`
- `docs/soak_test_report.md`
- `docs/public_benchmark_results.md`
- `docs/open_source_release.md`

## 7. 可靠性和可观测性

每个任务都会输出：

- `result.json`：表格、质量指标、诊断、修复记录和摘要。
- `trace.jsonl`：执行步骤、工具参数、耗时和恢复动作。

该输出模型支持结果复盘、下游入库和定向调试。修复闭环只处理确定性问题；无法确定的问题会保留
warning，并保留原始证据。

## 8. 产品价值

FinDoc Verifier Agent 面向需要结构化金融数据且不能丢失来源证据的团队。典型用途包括：

- 投研和分析中的财务报表入库。
- 企业文档流水线中的证据保留型 ETL。
- OCR 历史档案的质量筛查。
- PPT/XLSX 附件中的跨格式指标抽取。

## 9. 当前版本状态

当前仓库包含：

- 通过的 lint 和测试套件。
- 7 个核心能力样例的通过记录。
- HTML 原生解析、混合 DAG 执行和上下文修复的能力证据报告。
- 复杂图表结构化和全局指代消解的能力证据报告。
- 4 个海外公开 benchmark 和 4 个中国公开年报全量 benchmark 的通过记录。
- 传统 baseline、MinerU 直接解析和 FinDoc Agent 的本地标准横评记录。
- 复杂版式定向 accuracy、adversarial 结果表和 100 任务本地 soak 记录。
- 手写批注、多栏混排、嵌套/多行表头 edge layout 专项记录。
- Colab GPU OCR 全量复核和并发 2/3 压测记录。
- 本地 Docker 一键启动和 API smoke 记录。
- 可复现的 result 和 trace 本地产物。
- 排除 secrets、cache、虚拟环境和运行产物的打包说明。
