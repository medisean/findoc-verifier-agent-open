# 样例输入文件

请将 benchmark 文件按以下文件名放到本目录：

- `annual_report.pdf`
- `scanned_financial_statement.pdf`
- `cross_page_table.pdf`
- `management_report.docx`
- `investor_deck.pptx`
- `financial_model.xlsx`

这些文件默认不提交，除非已确认许可允许分发。核心评测任务定义在
`examples/sample_tasks.yaml`。

本目录已提交两个可再分发的小型结构化样本：

- `html_financial_table.html`：HTML 多级表头、rowspan / colspan 样本。
- `complex_chart_reference_blocks.json`：复杂图表与全局指代消解样本。

`public_benchmark_cn/` 已包含 4 份中国上市公司公开披露年报 PDF，用于中文年报扩展验证。

数据来源说明见 `examples/inputs/SOURCES.md`。
