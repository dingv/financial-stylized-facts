# 评估方法与开源实现

每个资产、路径独立评估。主要方法在计算前确定，辅助设置展示稳定性；真实市场数据和模拟数据使用同一套规则。区间是否显著不参与选择数据、采样尺度或主要方法。

## 开源实现对照

| 实现 | 实际做法 | 本库采用的部分 |
| --- | --- | --- |
| [MarS](https://github.com/microsoft/MarS/blob/main/market_simulation/examples/report_stylized_facts.py) | 多尺度偏度；收益与未来绝对收益相关；粗细波动的正负 lag 差；第 8 项并入波动聚集图。seaborn 误差带汇总多个 symbol，并非单条路径的联合显著性检验。 | 固定的指标定义、方向及独立展示。逐路径推断另行实现，不复用跨 symbol 误差带。偏度函数的 ±5% 过滤不采用。 |
| [Safari 的公开代码](https://github.com/Saraaqzs/stylized_dev) | `src/corr.py` 调用 statsmodels ACF/CCF；notebook 对绝对收益 ACF 作双对数回归，绘制偏度与尾部；时间尺度不对称部分只有占位。 | 作为指标与图形对照，不作为完整自动判定标准。不采用极端值过滤或把相关 ACF 点的普通回归标准误当作幂律检验证据。 |
| [statsmodels](https://www.statsmodels.org/stable/index.html) | Bartlett / Newey–West HAC、样本量带宽规则、Holm 多重检验、Kim–White 稳健偏度。 | 数值参考与交叉测试。带宽至少覆盖正在检验的 lag；保留本库缺失槽和交易段边界。 |
| [arch](https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html) | 循环区块重抽样及百分位置信区间。 | 按连续段重抽样；索引生成、区间与 arch 做一致性测试。 |

上述工作没有共同的一套“11 项自动通过门槛”。本库使用文献定义和成熟统计实现组织主要检验，并通过已知性质数据检验自动结论。MarS 本次核对的文件 blob 为 `7f54c225c9007171b243be0b5bc1576bbd9e6f82`；Safari notebook blob 为 `2a40ee9334abd6edf1e519a88678ca39e5e4ee53`。

## 主要结论与稳定性

- **涨跌不对称**：Bowley / Kim–White 分位数偏度 `(Q25+Q75−2Q50)/(Q75−Q25)`，循环区块 95% 区间，默认主要块长 10。该指标反映分布中部形状；普通偏度、左右远尾及首达时间分别展示。左偏与右偏对称处理，右偏记为反向证据。
- **杠杆效应**：`corr(r[t], abs(r[t+k]))`，默认正 lag 1–10。未来平方收益和负 lag 为对照，不能替换未显著的主要指标。
- **时间尺度不对称**：同一非重叠粗区间的 `C=abs(sum(r))` 与 `F=mean(abs(r))`，检验 `corr(F[t],C[t+k])−corr(C[t],F[t+k])`。负值为粗波动在前更强。
- **缓慢衰减**：参考 Ratliff-Crain 等的图 7，从 lag 5 起拟合绝对收益自相关，并读远端逐点区间。原尺度模型比较与分段持续性作补充。

相关检验的主要带宽为 `max(abs(k), floor(4*(n/100)^(2/9)))`，n 是该尺度的有效配对数。每个代理、每个方向的预设 lag 家族使用双侧 Holm 校正；无效 lag 以 p=1 保留在校正计划中，实际 p 输出为空。默认主检验至少 200 对、且不少于 `20*(bandwidth+1)` 对。这个有限样本门槛是库的适用性规则，带宽公式来自 statsmodels；两者分别记录。

主要配置不随辅助带宽的增加而改变。`primary_dependence_intervals.csv` 给出主要带宽、样本门槛、原始及校正 p；`assessment.csv` 给出逐项结论与 `inference_status`；其他设置保留为稳定性结果。Holm 控制范围是每条路径的一组预设 lag，不是跨资产或 11 项的整体控制。

## 数值与识别能力验证

单元测试对照 statsmodels 的 HAC、Holm 和稳健偏度，以及 arch 的区块索引和百分位区间；同时检查收益反号、时间反转、缺失、零四分位距、辅助配置变化和样本不足。

`tests/validation/validate_primary_assessments.py` 固定种子，检验：

- 高斯、Student-t(5)、可逆随机波动空模型的方向误报率；
- 已知正负杠杆、粗到细和细到粗关系的识别率；
- 对称与左右偏分布的分位数偏度检验；
- 独立、短记忆、长记忆波动及方差突变的持续性表现。

方向检验使用 1500/4000 条收益，每种 100 次；分布检验 1500 条、100 次；持续性检查 4096 条、40 次。输出包含二项式 Wilson 95% 区间。验证生成序列只用于测试，不作为真实市场示例。

固定种子的独立验证结果：

| 检查 | 结果 |
| --- | --- |
| 无方向关系：高斯、t(5)、可逆随机波动，两个样本量合计 | 杠杆检验误报 35/600；尺度方向检验误报 19/600 |
| 预设较强正负杠杆与粗细方向关系，两个样本量 | 各条件 100/100 识别到设定方向 |
| 分位数偏度：高斯、对称 t(5) | 各误报 3/100 |
| 分位数偏度：左右偏 Gamma 对照 | 各识别 87/100 |
| 持续性：独立与短记忆随机波动 | 各 0/40 出现持续性迹象 |
| 持续性：长记忆随机波动、方差突变 | 分别 18/40、40/40 出现迹象；均未通过全部分段稳定性条件 |

这些频率对应脚本中的具体过程与效应强度。方差突变结果说明，全样本持续性可以来自结构变化，因此报告将其称为“持续性迹象”，与稳定长记忆结论分开。

```bash
python -m tests.validation.validate_primary_assessments --output /tmp/primary-validation.json
```

## 方法来源

- [Kim & White (2004), On more robust estimation of skewness and kurtosis](https://doi.org/10.1016/S1544-6123(03)00003-5)
- [statsmodels robust_skewness](https://www.statsmodels.org/stable/generated/statsmodels.stats.stattools.robust_skewness.html)
- [statsmodels Bartlett HAC](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html)
- [statsmodels Holm 多重检验](https://www.statsmodels.org/stable/generated/statsmodels.stats.multitest.multipletests.html)
- [arch 区间构造](https://bashtage.github.io/arch/bootstrap/confidence-intervals.html)
