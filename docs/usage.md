# 使用指南

## 先运行真实数据示例

在项目 Conda 环境中执行：

```bash
python examples/run_reports.py --dataset AAPL --output /tmp/fsf-aapl
```

打开 `/tmp/fsf-aapl/AAPL/report/index.html`。页面先展示 11 项评估总览，再给出各项关键数值与图形证据。说明由统计结果和固定规则生成，无需 GPT。指标解释与判读规则集中在[通用教学文档](learning-guide.md)。

## 准备自己的 CSV

| 字段 | 含义 |
| --- | --- |
| `timestamp` | 日期时间；带时区，或通过 `--timezone` 明确指定 |
| `price` | 有限且大于零的价格 |
| `asset_id` | 可选，资产名称；默认 `series` |
| `path_id` | 可选，路径名称；默认 `observed` |
| `session_id` | 可选，连续交易段；不同段之间不计算收益或相关配对 |
| `volume` | 可选，截至该时间戳的基础区间成交量，需声明单位 |

每个资产、路径单独计算。空白价格默认报错；显式使用 `--allow-missing-prices` 时保留缺口，不插值。无穷、非正价格或无法识别的数值始终报错。

## 分钟或逐笔价格

```bash
fsf analyze prices.csv --output /tmp/intraday-report \
  --frequency 5min --timezone Asia/Shanghai \
  --max-staleness 30s --price-type transaction
```

每五分钟取一次不晚于端点的最后价格，最多向前寻找 30 秒；更旧则留空。收益为相邻端点的对数价差，不重叠。相同时间戳按文件行顺序取最后一条。参数中的 30 秒只是示例，并非适用于所有数据。

未提供 `session_id` 时，默认按指定时区的日期分段，不计算跨日收益。跨夜连续序列可显式设置 `--session-policy continuous`。程序没有内置交易所日历，午休、休市与长缺口需要据数据明确处理。

## 日频价格

```bash
fsf analyze daily.csv --output /tmp/daily-report \
  --sampling observations --observation-unit trading-day \
  --timezone UTC --price-type adjusted-close
```

此时按源观测顺序计算，不填充周末。lag 1 表示相邻观测，可能跨越周末或假日，不是固定 24 小时。源文件未出现的交易日不会自动补齐，应先核对日期覆盖。股票、FRED 和 EBS 原始文件的转换见[数据指南](data-guide.md)。

## 调整分析尺度

```bash
fsf analyze prices.csv --output /tmp/multiscale-report \
  --frequency 1min --timezone UTC --price-type midquote \
  --max-lag 30 --aggregation-factors 1 5 15 60 \
  --rms-window 30 --volatility-max-lag 300 --coarse-factor 30
```

这里普通 ACF 最多观察 30 分钟，分布比较 1、5、15、60 分钟收益；RMS 使用过去 30 个基础收益。粗细波动方向图一步为 30 个基础间隔。日频观测模式中的这些数值均表示观测数量。

密度图不混合路径，也不默认叠加正态曲线。峰度直接从收益计算，与 KDE 平滑曲线无关。近似区间及其假设见[统计方法](methods.md)；完整选项用 `fsf analyze --help` 查看。

## 成交量

含 `volume` 时需添加 `--volume-kind interval --volume-unit shares`（或真实单位）。它必须已经按分析频率汇总，表示结束于本行时间戳的区间量；程序不把逐笔量、累计量或报价次数自动当作该区间成交量。量缺失留空，真实零成交量填 0。

## 输出文件

| 文件 | 用途 |
| --- | --- |
| `index.html` | 可独立复制、离线打开的图文报告 |
| `assessment.csv` | 与 HTML 一致的逐项结论、证据类型、关键数值和规则版本 |
| `summary.csv` | 样本量、峰度、均值、标准差等摘要 |
| `observations.csv` | 保留的详细观察，兼容原有分析流程 |
| `results.json` | 完整统计、配置、版本和输入哈希 |
| `figures/` | 可用于论文或演示的 PNG |
| 其他 CSV | ACF、多尺度、量价、首达时间、区间等逐项结果 |

输出目录必须尚不存在，程序不会覆盖已有报告。数据不足或不适用的项目保留原因，JSON 中以 `null` 表示不可计算值。CSV 在内存中处理，超大逐笔文件应先转换或选择研究范围。

## 在程序中读取评估结果

```python
for group in result["groups"]:
    for fact in group["assessment"]["by_fact"].values():
        print(group["asset_id"], group["path_id"], fact["name"],
              fact["label"], fact["evidence_level"], fact["metrics"])
```

每条记录包含 `conclusion`、`summary`、`metrics`、`evidence`、`rule_id` 和 `computation_status`。schema 0.14 新增 `assessment`，已有数值字段及 `findings` 保留。详细规则见[教学文档](learning-guide.md)。
