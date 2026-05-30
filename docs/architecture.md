# 架构说明

FinDoc Verifier Agent 采用面向生产流程的执行闭环：

1. 理解任务目标和文档类型。
2. 生成工具执行计划。
3. 按输入类型调用 MinerU、远端 backend 或原生 HTML parser。
4. 将金融表格、图表指标和叙述指标归一为稳定 schema。
5. 对正文中的跨页指代做目标指标解析。
6. 校验数字并识别异常。
7. 对低置信数值字段执行确定性修复。
8. 修复后再次校验。
9. 输出结构化结果和可追溯日志。

当前实现使用 SQLite 管理本地运行状态，并把产物写入本地磁盘。如果需要长期运行或多进程部署，
可将任务状态存储替换为 PostgreSQL/MySQL，并接入 Redis/Celery/RQ 或云队列。

MinerU 路由按任务解析。文本层 PDF 默认 `pipeline + txt`，扫描 PDF 和图片默认
`pipeline + ocr`。显式任务参数可以切换到远端 `hybrid-http-client` 或
`vlm-http-client` backend。
HTML 输入走原生解析路径，直接将网页 table 转为内容块，再进入统一的结构化、校验和 trace 流程。
chart block 会转为指标表；正文中的“上述收入”“该增幅”“该比率”“该金额”等指代会解析到候选图表或
表格指标，并保留目标页码、期间、单位和置信度。

校验完成后，Agent 会执行确定性修复，例如将 `1O0`、`l,23O` 这类 OCR 数字混淆修复为可解析数值。
修复记录写入 `quality.repairs` 和 `trace.jsonl`，随后 verifier 会基于修复后的表格再次运行。
