# Edge Layout 专项报告

本报告补充手写批注、多栏混排和嵌套/多行表头场景。该专项使用确定性 fixture，
重点验证边界行为：批注类噪声不进入财务指标、多栏叙述不串入表格、嵌套表头能展开为稳定期间字段。
机器可读结果见 `examples/benchmark_results/edge_layout_summary.json`。

## 覆盖场景

| Case | 难点 | 期望行为 |
| --- | --- | --- |
| `edge_handwritten_annotation_overlay` | 手写批注覆盖表格区域 | 保留 warning，不把批注文本当作财务行或指标 |
| `edge_two_column_mixed_layout` | 左栏叙述、右栏表格 | 保持阅读顺序和列边界，避免叙述串表 |
| `edge_nested_multiline_header_table` | 嵌套表头、多行表头、合并单元格 | 展开为 `H1 2025 actual/budget` 等稳定期间 |

## 汇总指标

| 指标 | 结果 |
| --- | ---: |
| case count | 3 |
| passed count | 3 |
| required metrics | 7/7 |
| required metric accuracy | 1.0000 |
| evidence coverage | 1.0000 |
| numeric parse coverage | 1.0000 |
| hard failures | 0 |
| annotation noise rejection | 1.0000 |
| reading order accuracy | 1.0000 |
| nested header accuracy | 1.0000 |
| merged cell expansion accuracy | 1.0000 |

## 结果表

| Case | status | required metrics | hard fail | warning | 关键边界 |
| --- | --- | ---: | ---: | ---: | --- |
| `edge_handwritten_annotation_overlay` | pass | 2/2 | 0 | 1 | 批注噪声被 warning 标记并排除 |
| `edge_two_column_mixed_layout` | pass | 2/2 | 0 | 0 | 多栏叙述未串入表格行 |
| `edge_nested_multiline_header_table` | pass | 3/3 | 0 | 0 | 嵌套表头和合并单元格展开准确 |

## 复现命令

```bash
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/build_edge_layout_fixtures.py
UV_CACHE_DIR=.uv-cache uv run --extra dev python scripts/run_edge_layout_benchmark.py
```

该专项不替代真实 OCR 全量验证；它用于固定边界样例和期望行为，确保后续改动不会把批注、多栏叙述或
嵌套表头处理成幻觉指标。
