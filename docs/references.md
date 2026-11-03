# 参考文献

| 文献 | 对应分析 |
| --- | --- |
| [Cont (2001), Empirical properties of asset returns: stylized facts and statistical issues](https://doi.org/10.1080/713665670) | 11 项典型事实的研究框架 |
| [Ratliff-Crain et al. (2025), Revisiting Cont’s stylized facts for modern stock markets](https://doi.org/10.1080/14697688.2025.2530637)；[开放预印本 v2](https://arxiv.org/abs/2311.07738v2) | 多事实联合评估、杠杆效应、粗细尺度方向 |
| [Newey & West (1987)](https://doi.org/10.2307/1913610) | Bartlett HAC 协方差 |
| [Lo (1991), Long-Term Memory in Stock Market Prices](https://doi.org/10.2307/2938368)；[Gould, Porter & Howison (2016), Appendix B.3](https://people.maths.ox.ac.uk/porterm/papers/long-memory-published.pdf) | 修正 R/S 与短期依赖检验 |
| [Jensen, Johansen & Simonsen, Inverse Statistics in Economics](https://arxiv.org/abs/cond-mat/0211039) | 对称收益阈值的首达时间 |

这些文献提供研究问题和方法依据；本库的估计量、采样和默认参数见[统计方法](methods.md)，不代表逐项照搬某篇文章的全部设置。

数值参考与依赖：[SciPy kurtosis](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kurtosis.html)、[statsmodels ACF](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.acf.html)、[arch GARCH](https://bashtage.github.io/arch/univariate/introduction.html)、[arch 区块重采样](https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html)。
