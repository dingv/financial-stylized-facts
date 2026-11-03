# 把真实行情变成可分析的数据

先确认一行代表什么，再计算收益。日频参考汇率、股票调整收盘价、EBS 成交价记录可以使用同一套统计工具，但不是同一种价格，不能直接混成一条序列。

本库提供两个步骤：`prepare` 只读原文件，另写规范 CSV 和来源清单；`analyze-prepared` 根据清单里的配置生成报告。两个步骤都要求新的输出目录，不覆盖原数据或旧报告。

## FRED 日频外汇

当前专用适配器核对了 `DEXUSEU`（每欧元的美元数）与 `DEXJPUS`（每美元的日元数）。它们是纽约中午参考汇率，不是全天交易的收盘价。[FRED 系列说明](https://fred.stlouisfed.org/series/DEXUSEU)

```bash
fsf prepare fred /path/to/DEXUSEU.csv --asset DEXUSEU \
  --start 2000-03-01 --end 2013-03-01 --output /tmp/fred-ready
fsf analyze-prepared /tmp/fred-ready --output /tmp/fred-report
```

默认保留文件里明确为空的价格槽：缺口两侧不计算收益，也不把后面的观测向前挪。这有利于发现缺失的影响，但连续段可能短到无法拟合 GARCH。

如果研究对象是“相邻可用参考报价的变化”，可以在转换时明确指定 `--missing-policy available`。此时空价格日期移除，报告记录移除行数；lag 1 指相邻可用报价，可能间隔周末或假日，**不叫固定 24 小时收益**。原始文件没有出现的日期不会自动补齐，程序也不会推断每个缺失都是休市。

规范 CSV 的 UTC 零点只是日期标签。它不把实际中午观测改称零点成交。

## EBS 高频成交价

```bash
fsf prepare ebs-tick /path/to/ebs-tick.csv --asset EUR/USD \
  --frequency 5min --max-staleness 5min --output /tmp/ebs-ready
fsf analyze-prepared /tmp/ebs-ready --output /tmp/ebs-report
```

只读取 `Event Type=D` 的 `Last Trade`，保留 GMT 时间戳，排除报价行。EBS 历史文件采用时间片结构，不能宣称一行就是一张订单；Tick 文件也没有成交量，因此量价分析会标为不可用。[CME 官方字段说明](https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457573144/EBS+Spot+FX)

例子在五分钟网格向后取价，最多沿用五分钟内的价格；太旧则缺失。这个期限是显式选择，不是所有市场的标准。较长沿用可能增加零收益，报告会显示沿用数与缺口数。相同时间戳的价格按原文件顺序取最后一条，不据此推断真实成交先后。

当前适配器把一个文件视作一个连续 session，适合已核对的一日样本；包含周末、休市或多日不同交易段的文件需先明确分段。它不读取 Level 1/2 成交量，也不重建订单簿。

## 股票或其他日频 CSV

```bash
fsf prepare daily-csv /path/to/stock.csv --asset AAPL \
  --date-column Date --price-column 'Adj Close' \
  --price-type 'provider-adjusted close' \
  --volume-column Volume --volume-unit shares --output /tmp/stock-ready
fsf analyze-prepared /tmp/stock-ready --output /tmp/stock-report
```

列名和价格含义必须明确。程序不会判断某个 `Close` 是否已复权，也不会自动修复拆股跳跃。成交量可省略；提供时需声明单位，真实零量与缺失量分开保存。收盘至收盘收益含隔夜变化，日成交量通常只涵盖该交易日，这种时间覆盖差别仍需解释。

开发验证使用 Bokeh 的 AAPL/MSFT 历史样本。提供方标注 `Adj Close`，并说明来自公开新闻来源；调整算法和量的复权未被本项目独立审计。它适合检查跨市场输入与数值流程，不作为交易所行情质量认证。[Bokeh 字段读取代码](https://github.com/bokeh/bokeh/blob/3.4.0/src/bokeh/sampledata/stocks.py)

需要复跑这一示例时，显式下载到新的临时目录：

```bash
python examples/fetch_stock_samples.py /tmp/bokeh-stock-samples
```

脚本固定两份小文件及其 SHA256；远端内容变化就停止，不自动接受新快照。本库不捆绑这些行情。数据使用权与软件许可证是两回事，公开发布报告或再分发数据前需核对提供方条款。

## 可追溯性与局限

转换目录包含 `prices.csv` 和 `provenance.json`。清单记录原文件和规范 CSV 的 SHA256、范围、缺失策略、字段解释及分析配置；生成报告时重新校验规范 CSV。原文件不写入仓库，清单不记录账户凭据。

原始输入按整份 CSV 读入内存，适用于这里核对的小型文件；不保证直接处理数 GB 的原始行情。非法价格、未知事件类型、重复日频日期会报错，不自动删除来获得更好看的分布。日频不存在内置交易日历；数据异常与真实极端事件必须区别处理。
