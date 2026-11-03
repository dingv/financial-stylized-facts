# 市场数据

`examples/` 是随仓库分发的固定真实样本。个人研究数据放 `raw/`，转换结果放 `processed/`；这两个目录由 Git 忽略，原始数据不会被分析程序覆盖。

## 随附样本

| 文件 | 观测范围 | 行数 | 价格与单位 |
| --- | --- | ---: | --- |
| [AAPL.csv](examples/AAPL.csv) | 2000-03-01 — 2013-03-01 | 3,270 | 股票复权收盘价，USD |
| [MSFT.csv](examples/MSFT.csv) | 2000-03-01 — 2013-03-01 | 3,270 | 股票复权收盘价，USD |
| [EURUSD.csv](examples/EURUSD.csv) | 2010-01-01 — 2025-12-31 | 4,174 | 纽约中午参考汇率，USD per EUR |
| [USDJPY.csv](examples/USDJPY.csv) | 2010-01-01 — 2025-12-31 | 4,174 | 纽约中午参考汇率，JPY per USD |

两个汇率文件各有 173 个源 `ND` 日期，保存为空白；其余各有 4,001 个有效报价。周末不补行。示例分析明确跳过空白，按相邻有效观测计算；原 CSV 不删行或插值。

## 股票来源

**Quandl WIKI Prices**，通过 [Bokeh sampledata 的固定版本](https://github.com/bokeh/bokeh_sampledata/tree/5999dc3b42e7ec445dcd4c0e15f6b8b8a1ab824f)获取；原归档由 marketneutral 在 Kaggle 提供。[Bokeh 的股票模块说明](https://github.com/bokeh/bokeh_sampledata/blob/5999dc3b42e7ec445dcd4c0e15f6b8b8a1ab824f/src/bokeh_sampledata/stocks.py)标明 Public Domain，并链接到 [Quandl 原发布说明归档](https://web.archive.org/web/20150411011214/https://www.quandl.com/data/WIKI)。这里保留来源署名。

从合并股票 CSV 中按 ticker 提取 AAPL、MSFT，保留原观测顺序和值，将列名规范为小写。`open,high,low,close,volume` 未复权；`adj_close` 是来源提供的拆股、分红调整价，包含样本期之后公司行动的调整。报告用 `adj_close` 和原 `volume`，量价分析应考虑两者调整方式不同。

该样本不是早期 Bokeh/Yahoo CSV 的原样拷贝；两者复权快照不同，不能将其报告当作同一份输入的结果。数据按来源提供的值使用，未独立逐笔核验。

## 汇率来源

**Board of Governors of the Federal Reserve System (US), Foreign Exchange Rates, H.10**：[欧元](https://www.federalreserve.gov/releases/h10/hist/dat00_eu.htm)、[日元](https://www.federalreserve.gov/releases/h10/hist/dat00_ja.htm)。数据为纽约中午买入参考汇率，不是交易所收盘价，无成交量。

美联储的[版权声明](https://www.federalreserve.gov/disclaimer.htm)说明，未另行标注的信息属于公共领域，可复制、分发并注明来源。这里只分发数字观测及本项目分析，不使用美联储标志，不表示获得机构背书。

将源表的日期转为 ISO 日期，选取 2010–2025 全部行，数值字符串保持原精度，`ND` 转为空白。未做反向报价、插值、去极值或价格合成。

## 来源清单与复现

[manifest.json](examples/manifest.json)记录下载日期、固定版本、源文件与样本 SHA256、字段、时间范围、处理和分发说明。`examples/run_reports.py` 会先核对样本哈希再运行。

EBS、个人下载文件及大规模行情不随 Git 分发。软件和第三方数据的使用条件分别以各自的说明为准。
