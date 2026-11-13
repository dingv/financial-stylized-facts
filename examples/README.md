# 真实市场示例

以下报告由本库直接读取随仓库附带的真实价格生成，图表与文字均来自计算结果，没有人工补写结论。

| 示例 | 数据与价格 | 完整报告 |
| --- | --- | --- |
| AAPL | 2000-03-01 至 2013-03-01，复权收盘价、未复权成交量 | [AAPL.html](reports/AAPL.html) |
| MSFT | 2000-03-01 至 2013-03-01，复权收盘价、未复权成交量 | [MSFT.html](reports/MSFT.html) |
| EUR/USD | 2010–2025，纽约中午参考汇率，美元/欧元 | [EURUSD.html](reports/EURUSD.html) |
| USD/JPY | 2010–2025，纽约中午参考汇率，日元/美元 | [USDJPY.html](reports/USDJPY.html) |
| BTC | 2020–2025，UTC 日末美元参考价、现货美元成交额 | [BTC.html](reports/BTC.html) |
| ETH | 2020–2025，UTC 日末美元参考价、现货美元成交额 | [ETH.html](reports/ETH.html) |
| Brent | 2010–2025，欧洲 Brent FOB 现货，美元/桶 | [BRENT.html](reports/BRENT.html) |
| Henry Hub | 2010–2025，天然气现货，美元/百万 Btu | [HENRYHUB.html](reports/HENRYHUB.html) |
| 黄金、白银 | 2010–2025，工作日官方核算价，UAH/金衡盎司 | [黄金](reports/GOLD_UAH.html) · [白银](reports/SILVER_UAH.html) |
| BTC、ETH 交割期货 | 2025-10 至 2025-11，单一 2025-12-26 到期合约的小时收盘价 | [BTC 期货](reports/BTC_FUT_202512.html) · [ETH 期货](reports/ETH_FUT_202512.html) |

下载 HTML 后用浏览器打开，或克隆仓库后直接打开本地文件。页面已嵌入图像，无需启动网页服务器。

## 重新生成

在项目根目录、已激活的 Conda 环境中运行：

```bash
python examples/run_reports.py --dataset AAPL --output /tmp/fsf-aapl
python examples/run_reports.py --dataset BTC --output /tmp/fsf-btc
python examples/run_reports.py --dataset GOLD_UAH --output /tmp/fsf-gold
python examples/run_reports.py --dataset BTC_FUT_202512 --output /tmp/fsf-futures
python examples/run_reports.py --dataset all --output /tmp/fsf-markets
```

分别打开 `/tmp/fsf-aapl/AAPL/report/index.html` 或 `/tmp/fsf-markets/<数据名>/report/index.html`。输出目录须尚不存在。脚本核对输入 SHA256，保存转换后的输入、来源清单、完整统计表和报告，不访问网络或修改随附数据。

全部样本按资产、合约分别计算，统计窗口以各自基础观测为单位：普通 ACF 最大 30 个观测，长范围 ACF 最大 100 个观测，粗细比例 5，分布聚合倍数 1/5/10/20，区块重采样 399 次。固定股票样本取提供方的整个历史范围，汇率和能源范围预先定为 2010–2025，加密资产为 2020–2025；没有根据结果挑选日期。

日频示例的一步是相邻有效报价。BTC、ETH 包含全部日历日，一步为一天；股票、汇率和能源可能跨越假日或周末。汇率 CSV 中的空白行保留，但本示例在分析时明确选择 `available` 模式。能源现货同样按有效报价计算，其中 Henry Hub 有一个源空白记录。

数据来源、复权与再分发说明见 [data/README.md](../data/README.md)。报告中的逐项结论同时导出到 `assessment.csv`；完整配置和输入哈希保存在 `results.json`。指标含义与判读规则见[通用教学文档](../docs/learning-guide.md)。

Coin Metrics 数据和相应衍生示例采用 CC BY-NC 4.0，来源署名见各报告及[数据许可](../data/examples/licenses/coinmetrics.txt)。能源示例采用 EIA 公共领域数据。

## 金属与期货的时间含义

- **黄金、白银**：2010–2025 年各 4,174 个工作日官方价格，4,173 个相邻观测收益。计价为 UAH/金衡盎司，因此反映金属及计价货币的共同变化。保留工作日重复报价，不增加周末观测。
- **交割期货**：一个 lag 是一小时，UTC 小时末标签。两份样本各有 1,464 个小时，保持单一到期合约，没有换月跳点。成交量为同小时基础资产数量。

NBU 数据按开放数据署名条件分发；Binance 样本及衍生报告采用 CC BY-NC-SA 4.0 及其数据条款。来源、单位与转换步骤见[数据说明](../data/README.md)。

主要相关检验的有效样本量、带宽、原始及 Holm 校正 p 值见各数据集的 `*-primary-dependence-intervals.csv`。方法对照与验证见[评估方法](../docs/assessment-methods.md)。

README 总览图由已保存的评估表生成：

```bash
python examples/plot_assessment_overview.py
```

绘图需要中文字体（如 Noto Sans CJK）；可用 `--font /path/to/font` 指定字体文件。
