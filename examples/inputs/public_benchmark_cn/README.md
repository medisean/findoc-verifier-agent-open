# 中国公开年报样本

本目录包含 4 份中国上市公司公开披露的 2025 年年度报告 PDF。文件来源为巨潮资讯公开披露链接，
可直接用于本地页段验证或远端全量解析。

| 文件 | 公司 | 页数 | 大小 | SHA256 | 来源 |
| --- | --- | ---: | ---: | --- | --- |
| `byd_2025_annual_report.pdf` | 比亚迪 | 268 | 7.3MB | `710d8b2e08e37ba521f1c4071d2c3e2369d3cadabc21a45073215d9f72138b0b` | `https://static.cninfo.com.cn/finalpage/2026-03-28/1225045351.PDF` |
| `catl_2025_annual_report.pdf` | 宁德时代 | 232 | 1.9MB | `c15272977147dee7e6935a38ea0e4fd6855370aabb106f54cfe20f7cf6048ec9` | `https://static.cninfo.com.cn/finalpage/2026-03-10/1225002214.PDF` |
| `moutai_2025_annual_report.pdf` | 贵州茅台 | 143 | 1.0MB | `474905deeaf0f875fc0a1b097a626c0c7852c427faadc5d7fc7816cbf45ea288` | `https://static.cninfo.com.cn/finalpage/2026-04-17/1225114741.PDF` |
| `cmb_2025_annual_report.pdf` | 招商银行 | 350 | 31MB | `abe612a273468072b176dd51ea460c1e1596f8ca729cbc6db3fa28ba9a57ea79` | `https://static.cninfo.com.cn/finalpage/2026-03-28/1225047590.PDF` |

建议先用 CPU 跑关键页段，再用 GPU 或远端 MinerU 服务跑全量 PDF。样本价值分析见
`docs/china_public_annual_report_analysis.md`。
