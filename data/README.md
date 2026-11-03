# 市场数据

`examples/` 是随仓库分发的固定真实样本。个人研究数据放 `raw/`，转换结果放 `processed/`；这两个目录由 Git 忽略，原始数据不会被分析程序覆盖。

## 随附样本

| 文件 | 观测范围 | 行数 | 价格与单位 |
| --- | --- | ---: | --- |
| [AAPL.csv](examples/AAPL.csv) | 2000-03-01 — 2013-03-01 | 3,270 | 股票复权收盘价，USD |
| [MSFT.csv](examples/MSFT.csv) | 2000-03-01 — 2013-03-01 | 3,270 | 股票复权收盘价，USD |
| [EURUSD.csv](examples/EURUSD.csv) | 2010-01-01 — 2025-12-31 | 4,174 | 纽约中午参考汇率，USD per EUR |
| [USDJPY.csv](examples/USDJPY.csv) | 2010-01-01 — 2025-12-31 | 4,174 | 纽约中午参考汇率，JPY per USD |
| [BTC.csv](examples/BTC.csv) | 2020-01-01 — 2025-12-31 | 2,192 | UTC 日末参考价 USD，现货成交额 USD |
| [ETH.csv](examples/ETH.csv) | 2020-01-01 — 2025-12-31 | 2,192 | UTC 日末参考价 USD，现货成交额 USD |
| [BRENT.csv](examples/BRENT.csv) | 2010-01-04 — 2025-12-31 | 4,047 | Brent FOB 现货，USD/桶 |
| [HENRYHUB.csv](examples/HENRYHUB.csv) | 2010-01-04 — 2025-12-31 | 4,036 | Henry Hub 天然气现货，USD/百万 Btu |
| [GOLD.csv](examples/GOLD.csv)、[SILVER.csv](examples/SILVER.csv) | 1960-01 — 2025-12 | 各 792 | 月均价，USD/金衡盎司 |
| [COPPER.csv](examples/COPPER.csv) | 1960-01 — 2025-12 | 792 | 月均价，USD/公吨 |
| [BTC_FUT_202512.csv](examples/BTC_FUT_202512.csv)、[ETH_FUT_202512.csv](examples/ETH_FUT_202512.csv) | 2025-10 — 2025-11 | 各 1,464 | 固定交割合约小时收盘价，USDT |
| [TXO_202512_24000_CALL.csv](examples/TXO_202512_24000_CALL.csv)、[TXO_202512_24000_PUT.csv](examples/TXO_202512_24000_PUT.csv) | 2025-03-20 — 2025-12-16 | 各 186 | 台指期权每日结算权利金，指数点 |

两个汇率文件各有 173 个源 `ND` 日期，保存为空白；其余各有 4,001 个有效报价。周末不补行。示例分析明确跳过空白，按相邻有效观测计算；原 CSV 不删行或插值。

## 股票来源

**Quandl WIKI Prices**，通过 [Bokeh sampledata 的固定版本](https://github.com/bokeh/bokeh_sampledata/tree/5999dc3b42e7ec445dcd4c0e15f6b8b8a1ab824f)获取；原归档由 marketneutral 在 Kaggle 提供。[Bokeh 的股票模块说明](https://github.com/bokeh/bokeh_sampledata/blob/5999dc3b42e7ec445dcd4c0e15f6b8b8a1ab824f/src/bokeh_sampledata/stocks.py)标明 Public Domain，并链接到 [Quandl 原发布说明归档](https://web.archive.org/web/20150411011214/https://www.quandl.com/data/WIKI)。这里保留来源署名。

从合并股票 CSV 中按 ticker 提取 AAPL、MSFT，保留原观测顺序和值，将列名规范为小写。`open,high,low,close,volume` 未复权；`adj_close` 是来源提供的拆股、分红调整价，包含样本期之后公司行动的调整。报告用 `adj_close` 和原 `volume`，量价分析应考虑两者调整方式不同。

该样本不是早期 Bokeh/Yahoo CSV 的原样拷贝；两者复权快照不同，不能将其报告当作同一份输入的结果。数据按来源提供的值使用，未独立逐笔核验。

## 汇率来源

**Board of Governors of the Federal Reserve System (US), Foreign Exchange Rates, H.10**：[欧元](https://www.federalreserve.gov/releases/h10/hist/dat00_eu.htm)、[日元](https://www.federalreserve.gov/releases/h10/hist/dat00_ja.htm)。数据为纽约中午买入参考汇率，不是交易所收盘价，无成交量。

美联储的[版权声明](https://www.federalreserve.gov/disclaimer.htm)说明，未另行标注的信息属于公共领域，可复制、分发并注明来源。这里只分发数字观测及本项目分析，不使用美联储标志，不表示获得机构背书。

将源表的日期转为 ISO 日期，选取 2010–2025 全部行，数值字符串保持原精度，`ND` 转为空白。未做反向报价、插值、去极值或价格合成。

## 加密资产来源

**Coin Metrics, Inc., Community Network Data**：[固定数据版本](https://github.com/coinmetrics/data/tree/f1a36afb962731c387bb03982758ab0103063da5)。BTC、ETH 使用预先选定的 2020–2025 全部日历日，两个样本的价格和成交额均无缺失。提取 `time,PriceUSD,volume_reported_spot_usd_1d`，重命名为 `date,price_usd,spot_volume_usd`，保留数值字符串。

[PriceUSD](https://github.com/coinmetrics/docs-website/blob/master/asset-metrics/market/priceusd.md) 是 UTC 日末参考价。[现货成交额](https://github.com/coinmetrics/docs-website/blob/master/asset-metrics/volume/volume_reported_spot_usd_1d.md) 为其覆盖的现货交易所报告美元金额之和；不是币数量、链上转账额或全市场交易额。按照来源的[时间戳约定](https://github.com/coinmetrics/docs-website/blob/master/market-data/market-data-faqs.md)，日期 D 标记该 UTC 日：价格是日末，成交额覆盖整日，因此同一行成交额与当日对前日的收益配对。交易所覆盖范围可能随时间变化。

这些数据及相应衍生示例采用 **[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)**，需署名且限非商业使用；原[许可声明](examples/licenses/coinmetrics.txt)随附。数据经过日期筛选和列选择，未更改数值。软件代码的 MIT 许可不替代第三方数据许可。

## 能源来源

**U.S. Energy Information Administration (EIA)**：[Europe Brent Spot Price FOB](https://www.eia.gov/dnav/pet/hist/RBRTED.htm)、[Henry Hub Natural Gas Spot Price](https://www.eia.gov/dnav/ng/hist/rngwhhdD.htm)，下载于 2026-11-03。EIA [再使用说明](https://www.eia.gov/about/copyrights_reuse.php)允许分发公共领域数据，并要求注明来源与日期。

从 Excel 的 `Data 1` 提取 2010–2025 全部观测，保留源精度和空白。Brent 有 4,047 个有效报价；Henry Hub 有 4,035 个有效报价和 1 个空白。未补周末、插值或去极值。这些是现货报价，不是期货连续合约或总回报指数，没有成交量。

## 金属数据来源

**World Bank Prospects Group, Commodity Price Data (Pink Sheet)**：[官方数据目录与 CC BY 4.0 许可](https://datacatalog.worldbank.org/search/dataset/0038238/commodity-prices-history-and-projections)。使用 2026 年 10 月快照的 `Monthly Prices`，预先选择 1960–2025 全部月份。黄金、白银按金衡盎司；铜按公吨，均为名义美元报价。

每月一条，月初日期仅作月份标签。保留源数值和缺失槽，不插值；计算月均价格之间的变化，不把它写成月末收盘收益。原始 Excel 的 `Description` 保留各报价品种的定义。转换只选择列、日期范围与重命名，来源为 World Bank，许可 CC BY 4.0。

## 交割期货来源

**Binance Vision USD-M Futures**：[官方数据说明](https://github.com/binance/binance-public-data)。预先选择 `BTCUSDT_251226`、`ETHUSDT_251226` 两个 2025-12-26 到期合约，提取 2025 年 10、11 月全部 1h K 线。源文件与其 SHA256 分别记录在 `source_files`。

使用真实 K 线 close；成交量取基础资产数量 `volume`（BTC 或 ETH），不是 USDT 成交额。将 `hh:59:59.999` 收盘时间标记为下一整点，以同一区间价格与量配对。保留零成交量；若无成交，价格留空，不沿用前价。两个实际样本均无缺失小时、无零成交小时。输入共 1,464 个价格，对应 1,463 个可计算收益。

这是固定到期日合约，没有换月，也不是永续合约。价格收益不包括保证金杠杆、费用或资金管理。数据、筛选后的样本及衍生统计/报告采用 **CC BY-NC-SA 4.0** 及 [Binance Vision 数据条款](examples/licenses/binance-terms.md)，需注明 Binance Vision 并以相同数据许可分享；软件代码仍独立采用 MIT。

## 期权来源

**台湾期货交易所 TAIFEX 每日选择权行情**：[政府开放数据条目](https://data.gov.tw/dataset/11320)、[年度历史下载](https://www.taifex.com.tw/cht/3/optDailyMarketView)。开放数据条目采用[政府资料开放授权条款第 1 版](https://data.gov.tw/license)；交易所[网站使用条款第三项](https://www.taifex.com.tw/cht/edu/userTerms)明确排除已授权政府开放平台的资料。来源署名：台湾期货交易所、金融监督管理委员会证券期货局；下载日期 2026-11-03。

从 2025 年完整原始压缩包筛选：TXO、202512 到期月、行权价 24000、一般交易时段，分别保存 CALL 与 PUT。样本含同一合约挂牌后的全部到期日前记录，未根据统计表现选择日期或拼接其他合约。两份均为 2025-03-20 至 2025-12-16，共 186 个价格。

分析采用交易所每日 `结算价`；[官方规则](https://www.taifex.com.tw/cht/5/optSetPrice)允许无近期成交时由交易所决定，因此不称为实际成交收盘价。实际 `收盘价` 另存 `last_trade_price`，无成交时为空；`volume` 为一般时段成交口数，零量保留。日期、结算价、成交价、成交量及合约标识均保留在 CSV，转换不修改价格。

[到期日为 2025-12-17](https://www.taifex.com.tw/cht/5/optIndxFSP?commodityIds=2&end_month=12&end_year=2025&start_month=12&start_year=2024)，终止日的结算栏 0 不视为期权权利金观测；这不是在普通交易日剔除零价。每份仅 185 条收益，未降低 HAC、GARCH 或长记忆的样本门槛。

## 重建新增样本

原始下载地址、文件名、版本和 SHA256 见清单。保存原始文件后可离线重建指定样本；输出目录须尚不存在：

```bash
# 仅重建 EIA Excel 样本需要此额外依赖；生成报告不需要。
python -m pip install xlrd==2.0.2
python examples/prepare_market_data.py --raw /path/to/originals --output /tmp/fsf-rebuilt
```

通过 `--datasets` 选择新增数据，例如：

```bash
python examples/prepare_market_data.py --raw /path/to/originals --output /tmp/extended-rebuilt \
  --datasets GOLD SILVER COPPER \
  BTC_FUT_202512 ETH_FUT_202512 TXO_202512_24000_CALL TXO_202512_24000_PUT
```

默认仍重建 BTC、ETH、BRENT、HENRYHUB 四份日频样本。World Bank XLSX、Binance ZIP 和 TAIFEX ZIP 的重建只使用 Python 标准库，无需新增依赖。脚本先验证原文件，再逐字节验证重建 CSV 与清单一致。EIA 下载文件会更新，重建此快照需使用对应下载日保存的原件。

## 来源清单与复现

[manifest.json](examples/manifest.json)记录下载日期、固定版本、源文件与样本 SHA256、字段、时间范围、处理和分发说明。`examples/run_reports.py` 会先核对样本哈希再运行。

EBS、个人下载文件及大规模行情不随 Git 分发。软件和第三方数据的使用条件分别以各自的说明为准。
