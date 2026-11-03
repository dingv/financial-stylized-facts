# 方法与软件引用

Cont 的清单提供研究问题，不规定所有市场共用的时间间隔、阈值或统一通过标准。本库采用的具体算法和边界分别记录在技术文档中。

| 来源 | 本库采用的内容 |
| --- | --- |
| [Cont (2001), Empirical properties of asset returns: stylized facts and statistical issues](https://doi.org/10.1080/713665670) | 十一项事实的覆盖框架 |
| [Ratliff-Crain 等，Revisiting Cont’s Stylized Facts，v2](https://arxiv.org/html/2311.07738v2) | 多事实联合评估的参考，杠杆及粗细尺度方向的操作定义 |
| [Newey & West (1987)](https://doi.org/10.2307/1913610) | Bartlett HAC 协方差；本库另行推导所用统计量的线性化贡献 |
| [Lo (1991), Long-Term Memory in Stock Market Prices](https://doi.org/10.2307/2938368)；[Gould、Porter、Howison (2016)，附录 B.3](https://people.maths.ox.ac.uk/porterm/papers/long-memory-published.pdf) | 修正 R/S 与短期依赖参照；本轮公式和临界值通过后一来源核对，未声称完整通读 Lo 扫描原文 |
| [Jensen、Johansen、Simonsen，Inverse Statistics in Economics](https://arxiv.org/abs/cond-mat/0211039) | 对称收益阈值的首达时间；本库不照搬其去趋势、密度拟合或市场结论 |
| [arch 模型文档](https://bashtage.github.io/arch/univariate/introduction.html)及[区块重采样文档](https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html) | GARCH 拟合依赖及重采样交叉验证 |
| [SciPy kurtosis](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kurtosis.html)、[statsmodels ACF](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.acf.html) | 修正超额峰度、完整单段 ACF 的参考实现 |

Q-Q 使用固定次序统计量与高斯中点排序概率，经验尾概率直接计数；不是复制某篇论文的图或软件实现。完整公式见 [统计约定](internal/statistical-contract.md)、[HAC](internal/dependence-inference.md)、[首达时间](internal/first-passage.md)和[长尺度对照](internal/long-memory.md)。

引用本库时记录版本、Git 提交、数据来源、采样设置及所用方法。仓库的 `CITATION.cff` 暂使用已有维护者署名 dingwei，没有编造 DOI、机构或已发表论文；正式公开前可由维护者确认署名。引用库不能替代引用原始数据及所用统计方法。
