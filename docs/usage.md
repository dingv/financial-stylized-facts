# 生成第一份报告

本版回答六组问题：价格和收益怎样变化、分布是什么形状、方向与波动是否持续、大涨大跌是否对称、拉长间隔后分布如何变化、平静和剧烈时段怎样交替。它提供描述性结果，不自动判定某个市场“通过”全部金融事实。

## 准备价格文件

输入 CSV 至少有两列：

```csv
timestamp,price,asset_id,path_id,session_id
2024-01-02T09:30:00Z,100.0,example,run1,day1
2024-01-02T09:35:00Z,100.2,example,run1,day1
2024-01-02T09:40:00Z,100.1,example,run1,day1
```

这只是字段示例，三行不够进行可靠的统计分析。

- `timestamp`：明确的日期时间。带 `Z` 表示 UTC；没有时区时，必须传入 `--timezone`。
- `price`：有限且大于零的价格。缺失或非法价格不会被悄悄删除，应在整理数据时明确处理。
- `asset_id`、`path_id`：可选；缺省分别为 `series`、`observed`。每组单独计算，保留标识中的前导零。
- `session_id`：可选；同一组资产/路径内，一个值代表一个连续交易段。午休前后或闭市前后可以分段，不能重复用同一个标识表示不同交易段。

不要把实际缺失的交易日直接删除后当作连续日频序列。当前没有交易日历，也不读取成交量或直接输入的收益率。这些功能会单独增加。

## 高频或分钟数据

```bash
fsf analyze prices.csv --output /tmp/my-fsf-report \
  --frequency 5min --timezone Asia/Shanghai \
  --max-staleness 30s --price-type transaction
```

这里每五分钟取一次价格，允许使用该时刻之前最多 30 秒内的最后价格；更旧则留缺失。`30s` 只是示例，应按数据频率决定。默认 `--max-staleness 0s` 只接受精确网格端点，不默认无限沿用旧价。

收益是相邻网格价格的对数差，不重叠；任一端点缺失，该收益就缺失。网格以 UTC 的固定时间边界对齐，范围限于每段实际观测的起止时间。同一时间的多条记录按原文件行顺序取最后一条，并在报告说明。

没有 `session_id` 时，默认按指定时区的日期分段（未指定则 UTC），不计算跨日收益；这只是保守默认，不能代替交易所日历。跨夜连续市场或模拟轨迹可以提供明确的 session，或在确认数据确实连续时选择 `--session-policy continuous`。午休、周末或长缺口需要明确分段与合理的沿用上限。

## 已整理的日收盘价

```bash
fsf analyze daily.csv --output /tmp/my-daily-report \
  --sampling observations --observation-unit trading-day \
  --timezone UTC --price-type close
```

这个模式按每个交易日的观测顺序计算，不插入周末。lag 1 是相邻交易日，不能解释成固定 24 小时。使用前需自行核对交易日是否齐全；当前程序无法识别漏掉的交易日。不要给每行分配不同的 session，否则无法计算相邻日收益；确有断档需要隔断时，再指定新的 session。

## 怎么读结果

打开 `index.html`，从下拉框选择资产或路径。每组分别展示价格与收益、收益密度、收益/绝对收益/平方收益的 ACF。密度图不混合路径、不叠加正态参照；峰度从样本直接计算。

ACF 横轴在固定网格模式中标为实际时长。例如五分钟收益的 lag 2 对应十分钟。日频观测模式标为观测次数，并在页面写明单位。默认最多 30 个 lag；`--max-lag` 可调整。`--min-pairs 20` 表示配对不足的点留空，这个门槛不是显著性保证。

本版没有置信区间、尾指数或长记忆检验。正超额峰度、连续正相关都是需要结合样本量解释的线索。不能把高峰度直接写成已经证明幂律厚尾，也不能把几个相关点称为长记忆。

输出目录还包含：

| 文件 | 内容 |
| --- | --- |
| `results.json` | 配置、输入及代码哈希、版本、逐组完整统计和不可计算原因 |
| `summary.csv` | 每组覆盖情况、峰度、均值、标准差与零收益比例 |
| `acf.csv` | 三类序列每个 lag 的相关系数与有效配对数 |
| `scales.csv` | 各聚合尺度的样本量、缺失块数、峰度与高斯分位数距离 |
| `figures/` | 独立 PNG 图，便于引用 |

HTML 嵌入全部图片，可以单独复制到本地打开；图表字号适合电脑阅读。输出目录必须是新目录，程序不会覆盖旧报告。首版在内存中读入整个 CSV，多路径 HTML 也会较大；超大原始逐笔文件应先通过后续适配流程整理，当前不保证直接处理性能。

## 新增的三个诊断

**涨跌不对称。** 左右尾柱图比较偏离本路径均值 1、2、3 个标准差的概率，另给修正偏度。展开附录可看原始收益分位数和连续同号涨跌段。这里的“涨跌段”不是完整的最大回撤或首达时间分析；段遇到零收益、反向变化、缺口或交易段边界时结束。边界截断的段另行计数，不用于段幅度摘要。

**多尺度分布。** 默认比较基础间隔的 1、5、10、20 倍。例如基础间隔为 1 分钟，就是 1、5、10、20 分钟收益。日频观测模式则是 1、5、10、20 个交易日。按每段首个采样价格固定起点，不重叠相加对数收益；块内有缺失则整块无效，结尾不足整块就舍弃，不为凑样本移动分组起点。图中给峰度和标准化分位数相对高斯的距离，表中列出样本数。分位数距离只看 1%–99% 的等距概率点，不能代替远尾检验，也不是 p 值。

**间歇性。** 滚动 RMS 展示平静与剧烈时段。另用全路径均值、标准差定义大幅变化，记录出现次数和连续片段长度；缺口与交易段边界断开片段。这是描述规则，不把长期漂移或外部时段变化自动解释成内生机制。

例如在一分钟基础采样上，比较 1、5、15、60 分钟收益，用最近 30 个收益算 RMS：

```bash
fsf analyze prices.csv --output /tmp/report-scales \
  --frequency 1min --timezone UTC --price-type midquote \
  --aggregation-factors 1 5 15 60 --rms-window 30 --burst-threshold 3
```

沿用价格的时长仍需按数据情况单独设置。聚合倍数必须从 1 开始严格递增；默认窗口和阈值是可调整的工程约定，不是 Cont 为所有市场指定的参数。

## Python 调用

```python
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.report import analyze_csv

result = analyze_csv(
    "prices.csv", "/tmp/report-python",
    AnalysisConfig(frequency="5min", timezone="UTC", price_type="midquote"),
)
```

这是开发版接口。详细估计量与边界处理见[技术约定](internal/statistical-contract.md)，完整目标见[评估方案](evaluation-plan.md)。
