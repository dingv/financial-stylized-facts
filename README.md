# Financial Stylized Facts

面向不同金融市场的典型统计事实（stylized facts）分析库。

目标是覆盖 Cont 总结的 11 项事实：输入价格、收益率及可选成交量数据，生成便于阅读的图文报告，以及可复核的统计结果。用于比较真实市场与模拟市场，不局限于外汇。

**当前版本：基础流程已可运行。** 支持 CSV 价格输入、时间采样、收益分布与三类自相关，生成独立 HTML 报告和统计数据。当前只提供收益自相关、厚尾、波动聚集的描述性诊断；尚未完成 11 项事实或正式显著性检验。

## 先看一份报告

在已配置的 Conda 环境中运行：

```bash
conda activate financial-stylized-facts
cd /home/dingwei/financial-stylized-facts
demo_dir=$(mktemp -d /tmp/fsf-example-XXXXXX)
python examples/synthetic_prices.py "$demo_dir/prices.csv"
fsf analyze "$demo_dir/prices.csv" --output "$demo_dir/report" --frequency 1min --price-type synthetic
```

打开输出目录里的 `index.html`，即可切换查看三种合成序列：独立高斯收益、独立厚尾收益，以及有波动持续性的 GARCH 收益。HTML 已嵌入图片，可以单独复制到本地打开。数值另外保存在 `results.json`、`summary.csv` 和 `acf.csv`。

自己的 CSV 至少包含 `timestamp,price`；多资产、多路径使用 `asset_id,path_id`。详见[使用指南](docs/usage.md)。原始 EBS/FRED 文件尚未接入专用适配器，不能直接假定其字段符合本接口。

## 计划提供什么

- 统一的数据检查与采样约定，明确时间尺度、缺失值和交易时段。
- 逐资产、逐模拟路径分析，展示统计量、图形和证据局限。
- 一键生成 HTML 报告，并导出机器可读结果与运行配置。
- 用已知性质的合成序列和多个真实市场的数据验证。

指标不是所有市场都必须通过的打分表。数据不足、缺少成交量或检验不适用时，将明确说明原因。

## 目录

- `src/financial_stylized_facts/`：Python 包。
- `docs/roadmap.md`：开发路线。
- `docs/evaluation-plan.md`：11 项事实的评估与报告方案。
- `docs/development.md`：Conda 环境使用说明。
- `docs/internal/`：后续技术规格与实现记录。
- `tests/`：手算、边界、成熟函数和已知性质序列验证。
- `examples/`：可运行的合成数据示例。

真实数据保留在仓库外，以路径或配置引用；研究结果也不默认提交到 Git。已有外汇项目可以调用本库，本库不依赖其模拟器。

## 开发状态

开发统一使用 Conda 环境 `financial-stylized-facts`，不用 venv。环境使用与重建见[开发环境](docs/development.md)，完整覆盖计划见[评估方案](docs/evaluation-plan.md)。运行 `python -m pytest -q` 验证计算和报告。

首版将输入与采样结果读入内存，适合经过整理的研究数据；尚未验证超大原始逐笔文件的性能。没有内置交易日历，交易时段应由输入明确指定。报告会显示缺口、沿用价格和不可计算原因，不将这些情况伪装成有效的统计结果。

项目计划开源；公开发布前再确定许可证、完善文档和验证。详见[开发路线](docs/roadmap.md)。
