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
| 黄金、白银、铜 | 1960–2025，月度均价 | [黄金](reports/GOLD.html) · [白银](reports/SILVER.html) · [铜](reports/COPPER.html) |
| BTC、ETH 交割期货 | 2025-10 至 2025-11，单一 2025-12-26 到期合约的小时收盘价 | [BTC 期货](reports/BTC_FUT_202512.html) · [ETH 期货](reports/ETH_FUT_202512.html) |
| 台指看涨／看跌期权 | 2025-03-20 至 2025-12-16，2025-12-17 到期，K=24000，日结算价 | [看涨](reports/TXO_202512_24000_CALL.html) · [看跌](reports/TXO_202512_24000_PUT.html) |

下载 HTML 后用浏览器打开，或克隆仓库后直接打开本地文件。页面已嵌入图像，无需启动网页服务器。

## 重新生成

在项目根目录、已激活的 Conda 环境中运行：

```bash
python examples/run_reports.py --dataset AAPL --output /tmp/fsf-aapl
python examples/run_reports.py --dataset BTC --output /tmp/fsf-btc
python examples/run_reports.py --dataset GOLD --output /tmp/fsf-gold
python examples/run_reports.py --dataset BTC_FUT_202512 --output /tmp/fsf-futures
python examples/run_reports.py --dataset TXO_202512_24000_CALL --output /tmp/fsf-option
python examples/run_reports.py --dataset all --output /tmp/fsf-markets
```

分别打开 `/tmp/fsf-aapl/AAPL/report/index.html` 或 `/tmp/fsf-markets/<数据名>/report/index.html`。输出目录须尚不存在。脚本核对输入 SHA256，保存转换后的输入、来源清单、完整统计表和报告，不访问网络或修改随附数据。

全部样本按资产、合约分别计算，统计窗口以各自基础观测为单位：普通 ACF 最大 30 个观测，长范围 ACF 最大 100 个观测，粗细比例 5，分布聚合倍数 1/5/10/20，区块重采样 399 次。固定股票样本取提供方的整个历史范围，汇率和能源范围预先定为 2010–2025，加密资产为 2020–2025；没有根据结果挑选日期。

日频示例的一步是相邻有效报价。BTC、ETH 包含全部日历日，一步为一天；股票、汇率和能源可能跨越假日或周末。汇率 CSV 中的空白行保留，但本示例在分析时明确选择 `available` 模式。能源现货同样按有效报价计算，其中 Henry Hub 有一个源空白记录。

数据来源、复权与再分发说明见 [data/README.md](../data/README.md)。报告中的逐项结论同时导出到 `assessment.csv`；完整配置和输入哈希保存在 `results.json`。指标含义与判读规则见[通用教学文档](../docs/learning-guide.md)。

Coin Metrics 数据和相应衍生示例采用 CC BY-NC 4.0，来源署名见各报告及[数据许可](../data/examples/licenses/coinmetrics.txt)。能源示例采用 EIA 公共领域数据。

## 商品与衍生品的时间含义

- **月度商品**：一个 lag 是一个日历月。输入为月均价，计算相邻月均价的对数变化；并非月末持有收益，也未假定每月固定 30 天。
- **交割期货**：一个 lag 是一小时，UTC 小时末标签。两份样本各有 1,464 个小时，保持单一到期合约，没有换月跳点。成交量为同小时基础资产数量。
- **期权**：每份 186 个结算价、185 个有效收益。固定标的、行权价、到期日与看涨／看跌方向；到期日不作为权利金观测。结算价可能包含交易所估值，实际成交收盘价另列，缺失不填补。样本不足的 HAC、GARCH、长记忆检验按原阈值报告原因。

期权权利金受到标的变化、隐含波动率与时间价值衰减共同影响，这组结果用于观察该合约的价格序列，不等同于标的市场或对冲策略收益。各频率结果分别解读。

World Bank 样本采用 CC BY 4.0；Binance 样本和衍生报告采用 CC BY-NC-SA 4.0 及其数据条款；TAIFEX 每日行情采用台湾政府资料开放授权条款第 1 版。具体来源和转换步骤见[数据说明](../data/README.md)。
