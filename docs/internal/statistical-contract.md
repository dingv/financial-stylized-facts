# 统计实现约定

本文件记录本库的算法与数据约定，不代表对任何论文实现细节的还原。当前实现：价格 CSV 输入、采样、对数收益、峰度、KDE、三类 ACF、涨跌不对称、多尺度聚合、间歇性、杠杆效应、长范围波动 ACF、区间量价关系、粗细尺度方向、条件厚尾与报告导出。其他段落明确标为计划；部分边际与量价统计已有近似区间；完整正式显著性检验尚未实现。已实现部分用手算、性质测试和成熟函数交叉校验。

## 输入与采样

当前只接受价格 CSV：必需字段 timestamp、price，可选 asset_id、path_id、session_id。价格要求有限且大于零，无效行直接报错；不静默删除。缺省标识为 series、observed。计划增加明确的已计算收益接口；可选 volume 字段按末尾的区间量约定，不根据数值猜测输入类别。

时间必须附时区或由配置指定；同时间多成交需要稳定顺序字段，否则按声明的输入顺序处理并披露。默认不将不同 session、资产、路径拼接成一条序列。

固定时间价格在网格端点取不晚于端点的最后有效观测。成交数据的前值沿用只能在明确交易时段内，且受 max_staleness 限制；区间收盘数据采用其明确的端点定义，防止重采样错移一格。首次价格之前、长数据缺口及跨日断点保留缺失。保留真实零收益，报告前值沿用比例。

r_t = log(P_t) - log(P_{t-Δ})，默认非重叠。日频的“一个 lag”可以是一交易日，不能标成固定 24 小时；盘中跨 session 的配对策略必须写入结果。收益截尾、去极值、季节性调整都不是隐式默认项。

## 分布与尾部

正文展示逐资产/路径的原始收益 KDE，记录带宽与样本数；常数或样本不足时用点质量/说明代替失败的 KDE。经验分布和统计量直接由样本计算，不由平滑曲线反算。

矩估计定义 m_j = mean((r-mean(r))^j)，未修正超额峰度 g2=m4/m2²-3。主报告可以使用小样本修正版，必须同时标注估计器和 n；n<4 或方差为零则不可计算。小样本修正不保证消除序列相关导致的偏差。对照 [SciPy kurtosis](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.kurtosis.html) 的 fisher=True、bias=False。

当前对每条路径构造 z=(r-mean(r))/std(r,ddof=0)，导出 |z|>2、3、4 的次数及经验比例。计划增加 P(|z|>x)、左右尾和 QQ 图；对数坐标上的零尾概率应留空。高斯参照为 2*sf(x)。超额峰度和有限阈值超额概率均不等于证明数学意义的幂律尾。主峰度采用 SciPy fisher=True、bias=False，同时输出未修正超额峰度及未修正 Pearson 峰度；KDE 使用全样本 Scott 带宽，默认不加高斯曲线。

默认不自动报告尾指数。后续尾指数模块需有阈值敏感性、尾部有效样本量、估计区间、拟合优度及替代分布比较，不能只看 log-log R²。

## ACF 与时间依赖

完整等距序列采用 rho(k)=sum_{t=k}^{n-1}[(x_t-xbar)(x_{t-k}-xbar)] / sum_{t=0}^{n-1}(x_t-xbar)²。分别对 r、|r|、r² 去均值。该定义可对照 [statsmodels ACF](https://www.statsmodels.org/stable/generated/statsmodels.tsa.stattools.acf.html) 的 adjusted=False。

存在缺口时不允许 dropna 后压缩时间再算 ACF。当前实现的估计器命名为 `session_masked_fixed_denominator`：在同一资产/路径内，以全体有效 x 的均值为 xbar，分母 D 为全体有效平方偏差和；分子只累加同一 session 内、原网格相距 k 且两端均有效的乘积。每个 lag 另输出有效配对数 N(k)，分子不按 N(k) 重新缩放。内部缺口不会改变 lag 长度；缺口两侧若恰好相距 k，则属于该 lag 的有效端点配对，不能解释成中间路径连续。

完整单段时这等于 adjusted=False ACF；多 session 或缺失时，配对损失会使估计幅度受覆盖率影响，因此不能和完整序列无条件比较。均值为全路径均值，不是分时段去均值，日历分段仍可能贡献相关性。默认 N(k)<20 的点输出 null，这只是展示门槛，不是统计显著性标准。FFT 计算分子与掩码配对数；通过显式手算缺口和 session 样例验证。零方差与样本不足返回原因，lag 0 不在正文图中绘制。

白噪声的 ±1.96/sqrt(n) 只能标为独立零相关近似参照，不称为所有统计量通用的置信区间。bootstrap 需保持路径与 session 边界，并明确重采样单位、区块长度和随机种子。分布区间与零假设显著性检验是两类任务，不能把普通 block bootstrap 当作已施加零相关零假设。

收益、波动的短期相关和绝对收益 ACF 的慢衰减分开解释。季节性或状态切换可能贡献相关性，提供显式季节性对照；不以自动去均值方式隐去待解释现象。

## 涨跌不对称、多尺度聚合与间歇性（已实现描述诊断）

涨跌不对称：修正 Fisher-Pearson 偏度，调用 [SciPy skew](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.skew.html) 的 bias=False，至少 3 条有效非恒定收益。原始收益的 1%、5%、50%、95%、99% 分位数采用 [NumPy quantile](https://numpy.org/doc/stable/reference/generated/numpy.quantile.html) 的 linear 方法。左右尾围绕全路径均值、使用 ddof=0 标准差，以全部有效收益作分母，分别计数 z<-k、z>k，k=1、2、3。分位数与尾部计数是不同定义，不能将均值中心化后的左尾直接称为实际亏损概率。

连续严格同号收益构成一段，零收益、变号、NaN 与 session 边界断段。段累计值为对数收益之和；不是峰谷最大回撤。相邻边界为缺口或 session 起止时，标记为截断；原始段数包含截断段，幅度中位数、95% 分位数与平均长度只用两端完整观察到的段。这一选择也可能影响长段样本，因此不作为完整 gain/loss asymmetry 的统一检验，首达时间仍待扩展。

多尺度：去除每个 session 首价差分产生的结构性 NaN 后，从首个收益槽起固定分成 m 个观测一块，m 默认 1、5、10、20。保留块内数据缺失的位置，有任一 NaN 则整块无效；不重排或滑动凑完整块。每段末尾不足 m 个的收益槽舍弃，并报告数量。有效块值为对数收益之和，等于完整价格路径的端点对数差。各尺度独立估计修正超额峰度；独立以均值、ddof=0 标准差标准化，计算 0.01、0.02、…、0.99 分位数与标准正态对应分位数的 RMSE。该距离是项目的描述指标，忽略比 1%/99% 更远的尾部；没有有限样本校准或 p 值。N<100 提示小样本，N<4 或零方差不计算峰度/分位数距离，不用“不显著”代替高斯化证据。

间歇性：每个 session 独立计算向后完整窗口 RMS=sqrt(mean(r²))，默认窗口 20 个基础收益；不去局部均值，因此漂移也贡献 RMS。有缺失的窗口留空。另以 abs(r-全路径均值)>k*全路径标准差定义大幅变化，默认 k=3；统一全样本阈值用于描述，不能称为实时预警或无前视预测。连续超阈值观测为片段，非超阈值、缺口和边界断开；报告总占比、观测片段数、最大观测长度、截断段数和完整片段平均长度。没有片段时数量与最大观测长度为 0，平均完整长度为 null；零方差时标准化阈值不可计算。RMS 有效窗口覆盖率以有效基础收益数为分母，包含起始窗口不足的影响。

上述设置是操作约定，并非声称 Cont 指定了统一参数或检验。三项仅标记 descriptive_only。

## 杠杆效应与长范围波动 ACF（已实现描述诊断）

杠杆效应使用 L(k)=corr(r_t, v_{t+k})，v 分别取 r² 和 |r|，正 k 表示当前收益在前、波动在后；输出负 k 和同期 k=0 作对照。操作定义参考 [Ratliff-Crain 等第 4.6 节](https://arxiv.org/html/2311.07738v2)，不宣称等同于所有文献中其他归一化的 leverage function。

每个 lag 只取同一 session 内的有效端点配对，不要求中间所有点有效，不跨 session；不压缩缺口。对该 lag 的配对集合各自求均值与平方偏差和，使用 Pearson 分子/分母，与完整序列 ACF 的全序列固定分母不同。估计器名 lag_specific_pairwise_pearson。FFT 分别计算掩码配对数、两侧和、平方和与乘积和，先按全路径有限返回值最大绝对值缩放，再全局中心化以减小平方溢出与抵消误差；最后仍按配对集合中心化。以显式循环配对和 [SciPy pearsonr](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.pearsonr.html) 交叉验证符号、数值和边界。

N(k)<min_pairs 时为 insufficient_pairs；配对方差小于或等于 64*机器 epsilon*对应二阶原始和尺度时，标 zero_or_near_zero_pair_variance 并输出 null，不把舍入误差生成的相关当作结果。不导出 SciPy 的 iid p 值，也不将负相关称为因果。倒数报价将 r 变为 -r、波动代理不变，因此相关符号反转。

长范围波动相关沿用 session_masked_fixed_denominator 估计器，主序列为 |r|，默认最大 lag=300，可设 1–2000。按时间排序后的观测槽将整条路径等分为默认 4 个诊断段（可设 2–8），保留缺口，每段内仍按 session 分隔；每段各自估计均值、固定分母和 ACF。边界前一槽到边界后一槽产生的基础收益保留并归到结束时刻，但 ACF 端点不跨诊断段。等槽数不是等日历跨度，也不是自动去除日内季节性。输出分段起止时间、有效样本量和每 lag 配对数，样本不足不画曲线。

该对照可以识别状态混合对全程相关的贡献，但分段后配对减少与均值重估也影响曲线，因此不单凭“分段后相关下降”确定机制。保留负点、不选择正点作 log-log 拟合；long_memory_test 状态固定为 not_implemented。较长范围相关仍可能来自短记忆、结构变化或季节性，不能代替幂律或长记忆检验。新增测试含无杠杆的 iid、已知前向波动响应、倒数报价反号，以及“全程正相关但分段接近零”的方差状态混合。

## 结果与验证

当前结果 schema_version=0.6。顶层包含 config、provenance、coverage 和 groups；每组含 asset_id、path_id、quality、distribution、acf、density、figures、asymmetry、aggregation、intermittency，以及 leverage、volatility_persistence、volume_volatility、timescale_asymmetry、conditional_tails、uncertainty。指标内记录状态、定义和样本数；ACF 另有 lags、values、pair_counts。coverage 的全部 11 项标 descriptive_only；每路径条件厚尾另记录是否启用、依赖缺失和拟合状态；第 8 项并不代表已做长记忆检验。JSON 不输出 NaN/Infinity，不可计算数值为 null 并附原因。输入及 Python/模板源码 SHA256、依赖版本随结果保存；不把本地绝对数据路径写进报告。scales.csv、leverage.csv、volatility_acf.csv、volume.csv、timescale.csv、conditional.csv、uncertainty.csv 逐组导出结果；不持久化逐点 RMS 或全部涨跌段，原输入和配置可重建。

输入校验、指标可计算状态和科学证据强弱分别记录。统计相关不作投资预测保证；缺少证据与反向证据不混同。

最小验证集：手算收益/矩/ACF；高斯 iid；Student-t iid（如自由度 5）；已知系数 AR(1)；Gaussian GARCH；缺口、时区、重复时间、不同 session、倒数报价、零方差、极短样本。用有容差的理论性质与成熟函数作交叉核对，随机测试固定种子并避免脆弱 p 值断言。只使用合成小数据，真实案例不进入单元测试仓库。

## 参考范围

[Cont (2001), DOI](https://doi.org/10.1080/713665670) 提供事实覆盖框架；[Ratliff-Crain et al. v2](https://arxiv.org/html/2311.07738v2) 用作多项事实联合评估的参考。以上公式、默认口径与报告设计是项目约定，尚需逐模块验证，不代表上述文章均采用完全相同的计算方法。
# 区间成交量与粗细尺度方向：0.4 实现约定

新增模块参考 [Ratliff-Crain 等，Revisiting Cont’s Stylized Facts，v2 第 4.7–4.8 节及附录 A.4](https://arxiv.org/html/2311.07738v2)，并采用以下显式操作定义。它们是描述诊断，不是统一的显著性检验。Cont 清单提供研究问题，不规定本库的分组数或默认尺度。

## 成交量

`volume_kind=interval`，必须声明单位。每行的量对应截至该行时间戳的基础收益区间；grid 输入预先对齐并汇总到 `frequency`，不转换累计量或自动聚合逐笔数据。observations 的量对应结束于该观测的区间。空白量为缺失，零是有效观测；负值、无穷、重复时间戳和未声明口径拒绝。不同资产的单位需统一声明或分别运行。缺失量不沿用；价格沿用策略与量分开处理。

对同一路径有限的 `(volume_t, |r_t|)`、`(volume_t, r_t²)` 配对分别计算 Pearson 和 Spearman（平均秩处理并列）。不输出 SciPy 的 IID p 值；时间依赖未处理。量及收益先缩放再计算，避免大金额平方溢出。低于 `min_pairs` 或方差近零，系数为 null 并保留原因。图使用量的 0、20、40、60、80、100% 分位边界，去掉重复边界，相同量不拆组；最多五组，可能不等样本数。不把分组均值的相关冒充原始区间相关。日内季节调整尚未实现。

## 时间尺度不对称

每个 session 去掉首个结构性缺失收益后，按 `m=coarse_factor>=2` 分成不重叠整块。第 t 块：`C_t = |Σ r_i|`，`F_t = mean(|r_i|)`。含缺口的块无效，但保留其位置；尾部不足 m 的收益舍弃。时间方向定义沿用所参考论文：`A(k)=corr(F_t,C_(t+k))`，`D(k)=A(k)-A(-k)`。正 k 下，A(k) 是细在前，A(-k) 是粗在前；所以 D<0 表示粗在前的相关更强。常量缩放 F 不影响 Pearson 系数。

每个 k 按同 session 的有效配对独立去均值计算 Pearson；不跨 session，不用同期 k=0 推断不对称。差值任一方向不可算则为 null。横轴一步为 m 个基础间隔；observations 模式只能标为 m 个观测，不能假称固定分钟。默认 m=30，最大 lag 沿用 `max_lag`，但以完整块数截断。该默认是可配置选择，不是从数据挑选最大不对称。

配对、差值及两向样本数全部导出；没有置信区间、因果推断或样本外预测检验。反转整块对齐的时间序列应使 D 反号；将 FX 收益整体反号应不改变 C、F、D。测试包含这两个性质、手算分块、含缺口的直接 Pearson 对照，以及已知粗在前的构造过程。

## 条件厚尾：0.5 实现约定

使用 [arch 8.0 的模型定义](https://bashtage.github.io/arch/univariate/introduction.html) 和 [fit API](https://bashtage.github.io/arch/univariate/generated/generated/arch.univariate.base.ARCHModel.fit.html)。常数均值 Gaussian QMLE GARCH(1,1)：`r_t=mu+sigma_t*z_t`，`sigma_t²=omega+alpha*(r_(t-1)-mu)²+beta*sigma_(t-1)²`。创新准似然选 normal，不通过选择 t 分布预先强加厚尾形状。模型参数用整段估计，结果是样本内诊断。

每个 session 按 NaN 切成连续有效收益段，时间顺序逐段独立拟合。默认最低 500 条收益，每路径最多尝试 8 段、100000 条，优化最多 500 次迭代。短段、超限段不拼接、不截断；所有段的状态都输出。图和残差只来自成功段，成功覆盖率明确报告。模型开关关闭或依赖缺失也分别记录。

输入先按该段均值 c 和 ddof=0 标准差 s 转成 y=(r-c)/s；arch 的 rescale=False，优化 ftol=1e-8。拟合后 mu=c+s*mu_y，omega=s²*omega_y，alpha/beta 不变，条件波动恢复原单位。记录优化状态、消息、迭代次数、软件警告。非零 convergence_flag、非有限参数/残差、非正条件波动或不满足方差参数约束时不产生残差结论。系数接近零、alpha+beta>=0.995 只作启发式提示，阈值不是统计检验。

拟合后舍弃前 garch_burn=50 个观测，并在同一截取范围对原始收益和 z=(r-mu)/sigma 分别计算峰度与尾部计数。分布图的原始收益再次按截取样本中心化与标准化，残差使用原模型 z；无正态密度参照，无跨段合并。原始平方 ACF 使用 ((r-mean(r))/std(r))²，残差平方 ACF 使用 z²；单段 fixed-denominator 定义与已有 ACF 一致。两者的残余相关用于检查过滤效果，不输出未经校准的拟合后 IID p 值。

逐段参数、状态、前后峰度在 conditional.csv；可用段的 timestamp、r、mu、sigma、z 在 conditional/，与显示区间相同。测试核对残差恒等式、方差递推、单位变换、Gaussian/t 创新模拟的过滤行为，以及缺口、短段、资源限制、优化失败和依赖缺失。100% 拟合成功不等于模型充分；持续性接近 1 时 50 个初始化缓冲观测可能不足。

## 区块重采样区间：0.6 实现约定

采用 [Circular Block Bootstrap](https://bashtage.github.io/arch/bootstrap/timeseries-bootstraps.html) 和[百分位区间](https://bashtage.github.io/arch/bootstrap/generated/generated/arch.bootstrap.CircularBlockBootstrap.conf_int.html)。实现用 NumPy 生成索引，单连续段的索引及 95% 区间与 arch 的相同种子结果逐项核对。默认 399 次、块长 10/20/40 个基础收益，三个方案都保存，不筛选较窄或更显著的区间。

每条资产/路径内，session 与收益缺口划分连续段。对每段独立均匀抽取固定长度块，块在该段内循环，拼成与该段等长的重采样序列，末块裁至原长度。循环仅是 bootstrap 人造边界，不声称原时间序列首尾相邻；不跨真实缺口或资产。各段长度保持固定，所有重采样观测用于同一路径的边际统计，不生成拼接后的 ACF。量与收益共同按相同索引重采样，量的缺失跟随原观测，不能通过独立抽量破坏同期关系。

覆盖均值、ddof=0 标准差、修正偏度、修正超额峰度、每次重新标准化后 |z|>3 的经验概率、零收益比例，以及量与 |r| 的 Pearson/Spearman、量与 r² 的 Pearson。估计公式与原诊断保持一致。使用 2.5%/97.5% 分位数（linear 插值），并输出重复估计的样本标准差。至少 95% 重复可计算才输出区间；重采样结果在浮点精度下没有变化则标记 degenerate，不把稀有事件零计数解释为概率上界为零。

全路径不足 200 条、任一连续段不足两个块或总观测不足二十块时对应方案不可用；短段不会静默删除。每路径 `n × reps × 块长方案数` 默认上限 2000 万，超限整个模块标记 resource_limit，不悄悄下采样或降低重复数。使用 seed、资产/路径标识、块长的 SHA256 派生独立随机流，增加其他路径或块长不会改变既有方案。参数、真实使用的种子和有效重复次数均导出。

这是按段分层、条件于已观测段数/长度的**单统计量近似区间**，不是从总体随机抽取未来交易日的区间。需要段内近似平稳、弱依赖及统计量所需矩条件；峰度的区间尤其依赖高阶矩。长记忆、强远尾、结构变化、信息性缺失或跨段关联可能使覆盖率失效。块长对照揭示部分敏感性，但不证明假设成立。不存在统一的 11 项“通过”判定。

没有施加零相关、正态性或其他零假设；不提供 p 值，不把“区间不含零”解释为未经校准的全报告显著性。多个资产、多个指标和块长的区间不是同时置信区间，没有多重比较校正。ACF/杠杆/尺度差值、GARCH 参数和拟合后残差暂不提供该区间，不用固定残差重采样忽略模型估计误差。相关的图和元数据继续明确无不确定性。
