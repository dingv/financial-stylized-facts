# 时间相关指标的不确定性：0.9

这是本库对现有估计量的操作约定，不宣称 Cont 为各市场规定过统一的检验。默认计算早期 10 个正滞后的三类 ACF、正反 10 个滞后的两类收益/波动 Pearson 相关，以及粗细尺度方向差值。lag 0 不作推断。长范围 ACF、分段 ACF 与 GARCH 拟合后残差未套用这些区间。

## 计算依据

使用估计量的线性化贡献加 Bartlett/Newey–West HAC 协方差。参考 Newey & West (1987), *A Simple, Positive Semi-Definite, Heteroskedasticity and Autocorrelation Consistent Covariance Matrix*, Econometrica 55(3), 703–708，[DOI](https://doi.org/10.2307/1913610)。已核对原文 703–705 页的矩条件、Bartlett 权重及一致性条件；交叉实现参考 [statsmodels cov_hac](https://www.statsmodels.org/stable/generated/statsmodels.stats.sandwich_covariance.cov_hac.html) 的 `S_hac_simple`，不使用小样本自由度修正。

HAC 不要求观测独立，但并非适用于任何依赖过程。区间以共同稳定矩、弱短期依赖和足够高阶矩为前提；尤其平方收益相关的影响函数需要很高阶矩，强远尾可能破坏方差和渐近近似。长记忆、结构变化、信息性缺失、跨 session 的相关均可能使覆盖率失效。不能用此短记忆近似区间来证明长记忆存在或不存在。

### ACF

令 n 为有效观测数，μ 为全路径均值，zₜ=xₜ−μ（无效位置的贡献设为零），D=Σzₜ²。对同 session 中相距 k 的有效端点集合定义 cₜ=zₜzₜ₊ₖ，否则 cₜ=0，S=Σ有效配对(zₜ+zₜ₊ₖ)，ρ=Σcₜ/D。当前固定分母 ACF 的逐原始槽线性化贡献为：

`q_t = [c_t − ρ z_t² − (S/n) z_t] / D`。

最后一项包含均值估计的影响；缺口或边界使配对均值不同于全均值时不能直接省略。贡献已含 1/n 量级，不再额外除以样本数。推断针对本库保留配对损失的估计量；缺口造成的幅度衰减不会通过区间被自动纠正。

### Pearson 与方向差值

每个 lag 按有效配对中心化，dₓ=x−配对均值，dᵧ=y−配对均值，Dₓ=Σdₓ²，Dᵧ=Σdᵧ²：

`q_t = d_x d_y / sqrt(D_x D_y) − ρ/2 * (d_x²/D_x + d_y²/D_y)`。

贡献放回当前收益 t 的原始槽，未参与配对的槽为零。粗细尺度 D(k)=corr(Fₜ,Cₜ₊ₖ)−corr(Fₜ,Cₜ₋ₖ)，使用同一粗区间槽上的两组贡献之差。因此协方差被保留，不把两条相关曲线当成独立估计量来相加方差。

### HAC 与区间

`V_B = Σ_sessions [Σ_t q_t² + 2 Σ_{h=1}^B (1−h/(B+1)) Σ_t q_t q_{t−h}]`。

不对各 session 的贡献再次去均值，不含跨 session 项。基础时钟或粗区间的缺口保留；零贡献不是伪造为零的收益。标准误 sqrt(V_B)。报告 `estimate ± 1.96 SE`，与相关的 [-1,1] 或差值的 [-2,2] 取交集。交集不修复渐近近似的适用性。

默认 B=10/20/40，均为预先指定的工作带宽，不称为理论最优或自动选择。ACF/杠杆用基础槽，方向差值用粗区间槽；CSV 同时输出可换算的秒数。图中固定第一种带宽，失效时不切换到其他带宽。

所有计划指标、滞后和带宽组合构成同一路径的一个 family，默认 m=240；同时输出临界值 Φ⁻¹(1−0.05/(2m)) 的 Bonferroni 区间。m 包含不可计算的计划行，避免按结果缩小 family；不跨资产、路径或其他分布统计校正。它仍依赖单项渐近近似，不是有限样本精确覆盖保证，不给“通过数”。

## 门槛和资源

- 配对数至少 max(min_pairs, inference_min_pairs, 20(B+1))，默认 inference_min_pairs=200；这是保守工程门槛，不是样本充分性定理。
- B 不小于 |lag|，确保不主动省略最短共享观测范围；不保证覆盖所有真实依赖。
- 近参数边界、零线性化方差、配对不足时无区间并保存原因。
- 每路径估算工作量 `N_slots * L * (7 + 1/coarse_factor) * (max(B)+1)`，默认上限 1 亿；超限整项跳过，不截短样本、减少带宽或挑滞后。此上限不是精确 CPU/内存预算。
- `--dependence-inference off` 可关闭；其余指标仍计算。

## 验证

测试包括逐行加权有限差分核对影响函数、与 statsmodels Bartlett 协方差交叉核对、差值联合协方差、独立序列和 AR(1) 标准误量级、缺口/session/尺度与现有图中点估计一致性，以及资源与小样本状态。`examples/validate_hac.py` 另用固定种子对 Gaussian iid 和 AR(1) 做小规模覆盖率审计；不通过调参数追求恰好 95%。Monte Carlo 的 Wilson 区间描述模拟误差，不是市场统计量的区间。

完整逐项数据在 `dependence_intervals.csv` 与 `group.dependence_uncertainty`。正文只显示早期区间和简短限制，全部带宽、校正区间与原因放折叠附录。
