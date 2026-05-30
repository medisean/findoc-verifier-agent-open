# 开源发布范围

本项目采用 Apache License 2.0。当前公开仓保留可复现、可复用、可再分发的工程材料：

- `app/`、`tests/`、`scripts/run_cn_full_validation.py`、`scripts/run_stability_smoke.py`、
  `scripts/run_capability_evidence.py`、`scripts/run_standard_benchmark.py`、
  `scripts/run_layout_accuracy_benchmark.py`、`scripts/run_adversarial_evaluation.py`、
  `scripts/run_soak_test.py`。
- `scripts/build_adversarial_fixtures.py` 以及可确定性生成的 adversarial 样本。
- `Dockerfile`、`docker-compose.yml`、`.dockerignore`、`.env.docker.example`，用于单节点生产参考部署。
- `examples/sample_tasks.yaml`、评测期望、版式 accuracy 期望、能力证据示例、GPU 验证摘要、
  Edge layout 期望、标准横评摘要、复杂版式和 soak 摘要、复杂图表指代样本、公开来源说明、
  中国公开年报样本和英文公开年报页窗横评样本。
- 技术、部署、Docker、API、API 示例、评测、架构、稳定性、GPU 验证、标准横评、
  Docker smoke、复杂版式 accuracy、edge layout、soak 和公开 benchmark 文档。
- `README.md`、`LICENSE`、`NOTICE`、`pyproject.toml`、`uv.lock` 和 CI 配置。

公开仓不包含以下内容：

- 本地运行目录、模型缓存、虚拟环境和临时下载。
- 展示压缩包、发布压缩包和临时归档。
- 私有配置、环境变量、token、密钥或账户信息。
- 不能确认再分发权限的第三方输入文件。

仓库中的中国上市公司年报样本来自公开披露链接，并在 `examples/inputs/SOURCES.md` 与
`docs/china_public_annual_report_analysis.md` 中记录来源、页数和 SHA256，便于复核输入一致性。
