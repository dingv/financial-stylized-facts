# Financial Stylized Facts

面向不同金融市场的典型统计事实（stylized facts）分析库。

当前首版目标、进度与验收要求见[项目进度](docs/status.md)。

目标是覆盖 Cont 总结的 11 项事实：输入价格、收益率及可选成交量数据，生成便于阅读的图文报告，以及可复核的统计结果。用于比较真实市场与模拟市场，不局限于外汇。

**当前版本：十一项事实已有描述性诊断。** 支持 CSV 价格输入、时间采样、收益分布、自相关、涨跌不对称、多尺度分布变化、间歇性、收益与后续波动关系，较长范围的波动相关对照、区间成交量与波动关系，粗细尺度波动的时间方向对照，以及 GARCH 调整后的残差厚尾，生成独立 HTML 报告与统计数据。分布与部分量价统计量已有区块重采样近似区间；早期时间相关指标另有 HAC 区间、带宽对照及单路径内多重比较区间。条件厚尾需要可选 arch 依赖；完整正式检验仍待完善；较长范围的 ACF 不等于已经完成长记忆检验。

## 先看一份报告

在已配置的 Conda 环境中运行：

```bash
conda activate financial-stylized-facts
cd /home/dingwei/financial-stylized-facts
demo_dir=$(mktemp -d /tmp/fsf-example-XXXXXX)
python examples/synthetic_prices.py "$demo_dir/prices.csv"
fsf analyze "$demo_dir/prices.csv" --output "$demo_dir/report" --frequency 1min --price-type synthetic
```

打开输出目录里的 `index.html`，即可切换查看五种合成序列：独立高斯、独立厚尾、有波动持续性的 GARCH、有明显偏度的独立收益，以及负冲击后增大波动的示意过程。最后一种只用于验证时间方向，不是拟合得到的真实市场模型。HTML 已嵌入图片，可以单独复制到本地打开。数值另行导出 JSON 与 CSV。

报告先给当前路径的具体观察，再逐项看图与限制；每个观察都能追溯到统计结果。它会提醒极端观测对峰度的影响、数据缺口和拟合覆盖率，不把十一项事实当作自动评分表。

自己的 CSV 至少包含 `timestamp,price`；多资产、多路径使用 `asset_id,path_id`。详见[使用指南](docs/usage.md)。EBS Tick、两组 FRED 外汇及明确字段的日频 CSV 可先用 `fsf prepare` 转换，见[真实数据指南](docs/data-guide.md)与[第一轮验证结果](docs/real-data-validation.md)。

量价与时间方向另有一个刻意构造的校验示例：

```bash
activity_dir=$(mktemp -d /tmp/fsf-activity-XXXXXX)
python examples/activity_prices.py "$activity_dir/prices.csv"
fsf analyze "$activity_dir/prices.csv" --output "$activity_dir/report" \
  --frequency 1min --coarse-factor 2 --volume-kind interval \
  --volume-unit synthetic-units --price-type synthetic
```

它展示同一构造过程及其时间反转：粗细波动差值应反号，同期量价关系应保持。成交量是人为生成的，只用于检查计算和阅读图形，不能当作真实市场证据。

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
