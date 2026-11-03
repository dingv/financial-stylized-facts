# 变更记录

## 0.13.0.dev0 — 首版候选准备中

- Cont 11 项均有明确的描述诊断、不可计算原因和逐路径报告。
- 条件厚尾使用 Gaussian QMLE GARCH(1,1)，失败、缺口和拟合覆盖率可追溯。
- 适用统计量有区块 bootstrap 或 HAC 近似区间；长尺度另有 Lo 修正 R/S 的窗口与带宽对照。
- 对称阈值首达时间、截断记录和连续片段内回撤/回升补充分布偏度。
- 新增默认折叠的经验尾概率与 Q-Q 图，正文密度图不叠加正态分布。
- 包内 `fsf demo`、公共 Python 入口、单文件 HTML、CSV/JSON 及输入哈希。
- 只读 EBS Tick、FRED 两系列和明确字段日频 CSV 适配；股票/外汇八份真实样本验证。
- 源码包→wheel→安装后测试与演示验证；GitHub CI 从新的 Linux/Python 3.12 Conda 环境执行。

JSON schema 为 0.13，新增 `tail_diagnostics` 和同名 CSV；此前 0.11 的指标定义保持不变。开发版尚不承诺稳定 API 或跨版本二进制/结果结构兼容。没有自动“11 项通过”评分、交易建议或长记忆证明。

本条是发布说明草稿，不表示已经公开发布。更早的开发过程见 Git 历史及 `docs/internal/execution-plan.md`。
