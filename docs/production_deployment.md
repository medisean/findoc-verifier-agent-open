# Docker 一键生产部署

本文档给出单节点生产参考部署。默认模式会启动 FinDoc Verifier Agent API、持久化任务状态和运行产物，
并通过健康检查确认服务可用。大 PDF/OCR 生产负载建议接入远端 MinerU 服务或在具备 GPU 的容器环境中运行。

## 1. 一键启动

```bash
cp .env.docker.example .env.docker
docker compose --env-file .env.docker up --build -d
curl http://127.0.0.1:8000/health
```

如果本机 `8000` 已被占用，只需要把 `.env.docker` 中的 `PORT` 改成可用宿主机端口，例如
`18080`，然后访问 `http://127.0.0.1:18080/health`。容器内 API 固定监听 `8000`，
Compose 会完成宿主机端口到容器端口的映射。

停止服务：

```bash
docker compose --env-file .env.docker down
```

查看日志：

```bash
docker compose --env-file .env.docker logs -f app
```

## 2. 配置项

`.env.docker.example` 中的默认配置适合单机部署：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INSTALL_MINERU` | `true` | 构建镜像时安装 MinerU CLI 和 pipeline 依赖。 |
| `PORT` | `8000` | 宿主机 API 端口；容器内 API 端口固定为 `8000`。 |
| `UVICORN_WORKERS` | `1` | API worker 数。默认单 worker，避免 SQLite 写入竞争。 |
| `ARTIFACT_ROOT` | `/data/runs` | 容器内任务产物目录。 |
| `TASK_STORE_PATH` | `/data/runs/tasks.sqlite3` | 容器内任务状态数据库。 |
| `MINERU_ENDPOINT` | 空 | 远端 MinerU 服务地址。为空时使用本地 MinerU CLI。 |
| `MINERU_MAX_CONCURRENCY` | `1` | 单进程内 MinerU 调用并发上限。 |

`docker-compose.yml` 会将宿主机 `./runs` 挂载到容器 `/data/runs`，因此容器重启后任务状态、
`plan.json`、`trace.jsonl` 和 `result.json` 都会保留。

## 3. 远端 MinerU 服务

生产环境推荐把 OCR/GPU 解析与 API 进程解耦。将 `.env.docker` 中的 `MINERU_ENDPOINT` 指向远端服务：

```bash
MINERU_ENDPOINT=http://your-mineru-server:30000
MINERU_MAX_CONCURRENCY=1
```

然后重启：

```bash
docker compose --env-file .env.docker up --build -d
```

任务也可以在 `options` 中显式传入：

```json
{
  "backend": "hybrid-http-client",
  "server_url": "http://your-mineru-server:30000"
}
```

## 4. 本地 MinerU 模型

如果容器内直接运行 MinerU pipeline，需要先下载模型。建议优先使用 ModelScope：

```bash
docker compose --env-file .env.docker exec app \
  mineru-models-download -s modelscope -m pipeline
```

下载完成后重启 API：

```bash
docker compose --env-file .env.docker restart app
```

GPU 机器上可使用 Docker 的 GPU 运行时启动容器；不同厂商驱动差异较大，生产上更推荐把 MinerU
作为独立 GPU 服务暴露给 `MINERU_ENDPOINT`。

## 5. 验证 API

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

提交 HTML smoke 任务：

```bash
curl -X POST http://127.0.0.1:8000/v1/tasks \
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

查询结果：

```bash
curl http://127.0.0.1:8000/v1/tasks/{task_id}
curl http://127.0.0.1:8000/v1/tasks/{task_id}/result
```

已完成一次本地 Docker smoke 验证：`INSTALL_MINERU=false`、宿主机端口 `18080`、HTML 财务表格任务
`succeeded`，校验通过率、数字解析覆盖和 evidence 覆盖均为 1.0000。完整记录见
`docs/docker_smoke_report.md`。

## 6. 生产注意事项

- 当前 Docker Compose 是单节点参考部署，适合 API 接入、演示、单机批处理和可复现验证。
- 多副本生产部署建议将 `TaskStore` 替换为 PostgreSQL/MySQL，并使用 Redis、Celery、RQ 或云队列承载后台任务。
- 大 PDF/OCR 任务建议保持 `MINERU_MAX_CONCURRENCY=1`，通过多 GPU 服务或队列扩展吞吐。
- `.env.docker` 不应提交；只提交 `.env.docker.example`。
- 对外暴露前应在网关层补充鉴权、限流、TLS 和访问日志。
