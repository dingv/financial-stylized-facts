# 真实市场示例

以下报告由本库直接读取随仓库附带的真实价格生成，图表与文字均来自计算结果，没有人工补写结论。

| 示例 | 数据与价格 | 完整报告 |
| --- | --- | --- |
| AAPL | 2000-03-01 至 2013-03-01，复权收盘价、未复权成交量 | [AAPL.html](reports/AAPL.html) |
| MSFT | 2000-03-01 至 2013-03-01，复权收盘价、未复权成交量 | [MSFT.html](reports/MSFT.html) |
| EUR/USD | 2010–2025，纽约中午参考汇率，美元/欧元 | [EURUSD.html](reports/EURUSD.html) |
| USD/JPY | 2010–2025，纽约中午参考汇率，日元/美元 | [USDJPY.html](reports/USDJPY.html) |

下载 HTML 后用浏览器打开，或克隆仓库后直接打开本地文件。页面已嵌入图像，无需启动网页服务器。

## 重新生成

在项目根目录、已激活的 Conda 环境中运行：

```bash
python examples/run_reports.py --dataset AAPL --output /tmp/fsf-aapl
python examples/run_reports.py --dataset all --output /tmp/fsf-markets
```

分别打开 `/tmp/fsf-aapl/AAPL/report/index.html` 或 `/tmp/fsf-markets/<数据名>/report/index.html`。输出目录须尚不存在。脚本核对输入 SHA256，保存转换后的输入、来源清单、完整统计表和报告，不访问网络或修改随附数据。

全部样本按资产分别计算，参数相同：普通 ACF 最大 30 个观测，长范围 ACF 最大 100 个观测，粗细比例 5，分布聚合倍数 1/5/10/20，区块重采样 399 次。固定股票样本取提供方的整个历史范围，汇率范围预先定为 2010–2025；没有根据结果挑选日期。

日频示例的一步是相邻有效报价，可能跨越假日或周末。汇率 CSV 中的空白行保留，但本示例在分析时明确选择 `available` 模式。它们不是固定 24 小时收益，也不能用于展示分钟级市场微观结构。

数据来源、复权与再分发说明见 [data/README.md](../data/README.md)。报告所用配置与输入哈希保存在 HTML 的方法部分和完整结果中。
