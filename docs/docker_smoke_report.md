# Docker Smoke 验证报告

验证日期：2026-05-31 CST

本报告记录 FinDoc Verifier Agent 在本地 Docker Desktop 环境中的一键启动、健康检查和完整 API
任务流验证。该验证使用轻量 API 镜像模式，不在容器内安装 MinerU pipeline，适合证明生产 API
控制面、任务状态、结果写出和持久化目录配置可复现。

## 环境

| 项目 | 值 |
| --- | --- |
| Docker Client | 29.4.3, darwin/arm64 |
| Docker Server | 29.4.3, Docker Desktop 4.74.0, linux/arm64 |
| Docker Compose | v5.1.4 |
| 镜像 | `findoc-verifier-agent:prod` |
| Compose 文件 | `docker-compose.yml` |
| 配置文件 | `.env.docker` from `.env.docker.example` |
| `INSTALL_MINERU` | `false` |
| 宿主机端口 | `18080` |
| 容器端口 | `8000` |

`PORT` 在 Docker Compose 中表示宿主机 API 端口；容器内应用固定监听 `8000`，便于把本机端口改为
`18080` 等非默认值时仍保持健康检查和内部路由稳定。

## 启动与健康检查

启动命令：

```bash
cp .env.docker.example .env.docker
# 本次本地验证将 .env.docker 中 INSTALL_MINERU=false, PORT=18080
docker compose --env-file .env.docker up --build -d
```

Compose 状态：

```text
NAME                     IMAGE                        SERVICE   STATUS                    PORTS
mineru-question2-app-1   findoc-verifier-agent:prod   app       Up 47 seconds (healthy)   0.0.0.0:18080->8000/tcp
```

健康检查：

```bash
curl -sS http://127.0.0.1:18080/health
```

响应：

```json
{"status":"ok","service":"FinDoc Verifier Agent"}
```

关键日志：

```text
Uvicorn running on http://0.0.0.0:8000
"GET /health HTTP/1.1" 200 OK
```

## API 任务流验证

提交 HTML 财务表格任务：

```bash
curl -sS -X POST http://127.0.0.1:18080/v1/tasks \
  -H "Content-Type: application/json" \
  -d '{
    "task_name": "docker-html-smoke",
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

任务结果：

| 字段 | 值 |
| --- | --- |
| `task_id` | `9eb1fe77-2afd-4a86-8471-f941dbc1a504` |
| `status` | `succeeded` |
| 表格数 | 1 |
| 行数 | 2 |
| 原始数字单元格 | 4 |
| 数字解析覆盖 | 1.0000 |
| evidence 覆盖 | 1.0000 |
| 校验通过率 | 1.0000 |
| warning | 0 |
| failure | 0 |
| repair | 0 |

结果摘要：

```text
Parsed 1 tables with 2 rows. Validation pass rate: 100.00%.
Warnings: 0; failures: 0; repairs: 0.
```

结果路径：

```text
/data/runs/9eb1fe77-2afd-4a86-8471-f941dbc1a504/plan.json
/data/runs/9eb1fe77-2afd-4a86-8471-f941dbc1a504/trace.jsonl
/data/runs/9eb1fe77-2afd-4a86-8471-f941dbc1a504/result.json
```

关键日志：

```text
"POST /v1/tasks HTTP/1.1" 200 OK
"GET /v1/tasks/9eb1fe77-2afd-4a86-8471-f941dbc1a504 HTTP/1.1" 200 OK
"GET /v1/tasks/9eb1fe77-2afd-4a86-8471-f941dbc1a504/result HTTP/1.1" 200 OK
```

## 结论

- Docker 镜像可在本地从零构建并启动。
- Compose 健康检查通过，主机端口到容器端口映射正常。
- FastAPI 任务创建、状态查询、结果查询完整跑通。
- `plan.json`、`trace.jsonl`、`result.json` 写入持久化目录 `/data/runs`。
- 轻量 API 模式可用于控制面部署验证；生产 OCR/GPU 解析可通过 `INSTALL_MINERU=true` 构建本地
  MinerU 镜像，或使用 `MINERU_ENDPOINT` 指向独立 MinerU 服务。
