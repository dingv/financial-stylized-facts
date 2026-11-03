# 数据指南

项目内统一使用以下目录：

```text
data/
  examples/       随 Git 分发的真实样本与来源清单
  raw/            本地原始数据，Git 忽略
  processed/      本地整理后的输入，Git 忽略
examples/
  run_reports.py  示例报告生成脚本
  reports/        精选真实数据报告和预览图
```

原始文件保持不变；转换结果写入新目录。随仓库分发的数据详见 [data/README.md](../data/README.md)。个人数据无需复制到仓库外，也无需加入 Git。临时报告推荐输出到 tmp。

## 日频股票与其他日频 CSV

```bash
fsf prepare daily-csv data/raw/stocks/AAPL.csv \
  --asset AAPL --date-column Date --price-column 'Adj Close' \
  --price-type adjusted-close --volume-column Volume --volume-unit shares \
  --output /tmp/aapl-prepared
fsf analyze-prepared /tmp/aapl-prepared --output /tmp/aapl-report
```

明确价格是否复权、量的单位与复权方式。价格调整并不代表成交量也已调整。日频转换用 UTC 零点作日期标签，并不声称这是实际收盘时刻。

## FRED 汇率

```bash
fsf prepare fred data/raw/fred/DEXUSEU.csv \
  --asset DEXUSEU --missing-policy available --output /tmp/fx-prepared
fsf analyze-prepared /tmp/fx-prepared --output /tmp/fx-report
```

适配器支持 `DEXUSEU`（美元/欧元）与 `DEXJPUS`（日元/美元），使用纽约中午参考汇率。`available` 明确跳过无报价日期，收益跨相邻有效观测；`preserve` 保留源文件中的空白槽，断开缺口两侧收益。两种方式的时钟不同，应按研究问题选择，不能把删缺失后的一步叫固定一天。

## EBS Tick

```bash
fsf prepare ebs-tick data/raw/ebs/ebs-fx-tick-2026-07-30.csv \
  --asset EUR/USD --frequency 5min --max-staleness 5min \
  --output /tmp/ebs-prepared
fsf analyze-prepared /tmp/ebs-prepared --output /tmp/ebs-report
```

该适配器面向已核对字段的 EBS Tick CSV，不是所有 EBS 产品的通用解析器。买卖侧汇总按文件顺序处理，以有成交量侧的 VWAP 构造代理成交价；它不是交易所逐笔原始成交价。成交量与分析时间区间对齐。

文件范围与交易段约定保存在转换清单中。一个文件日只能描述该日，不能替代长期市场样本。原始 EBS 文件和对应私有报告不随示例数据分发。

## 可复核的来源

转换输出 `prices.csv` 与 `provenance.json`，记录源文件哈希、字段、缺失策略和分析配置。`analyze-prepared` 核对规范输入的哈希后生成报告。数据来源声明不等于真实性或完整性的独立保证；报告记录数据提供方及价格含义。
