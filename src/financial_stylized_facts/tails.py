"""Finite-sample tail diagnostics, not a power-law fit or normality test."""
import numpy as np
from scipy.special import ndtri


def tail_diagnostics(values):
    values = np.asarray(values, dtype=float)
    if np.isinf(values).any():
        raise ValueError("收益中不能包含 Infinity")
    x = values[np.isfinite(values)]
    result = {"status": "insufficient_data", "reason": "至少需要 4 条有效收益", "n": len(x),
              "standardization": "path_mean_population_std", "ccdf": [], "qq": [],
              "qq_method": "order_statistics_vs_normal_mid_rank", "qq_max_points": 2000,
              "scope": "经验尾概率与高斯分位数对照；没有尾指数、p 值或置信带"}
    if len(x) < 4:
        return result
    normalized = x / (float(np.max(np.abs(x))) or 1.0)
    spread = normalized.std(ddof=0)
    if spread == 0:
        result.update(status="zero_variance", reason="零方差序列不能标准化")
        return result
    z = np.sort((normalized - normalized.mean()) / spread)
    absolute = np.sort(np.abs(z))
    # Fixed grid, plus the observed maximum to expose the zero-count endpoint.
    for threshold in np.unique(np.r_[np.linspace(0, 6, 121), absolute[-1]]):
        count = len(x) - int(np.searchsorted(absolute, threshold, side="right"))
        result["ccdf"].append({"threshold_sigma": float(threshold), "count": count,
                               "probability": count / len(x)})
    # Plot bounded, deterministic ranks including both extremes. All data define z.
    ranks = np.unique(np.linspace(0, len(z)-1, min(len(z), 2000)).astype(int))
    for rank in ranks:
        p = (int(rank) + .5) / len(z)
        result["qq"].append({"rank": int(rank)+1, "plotting_probability": p,
                             "normal_quantile": float(ndtri(p)), "sample_quantile": float(z[rank])})
    result.update(status="computed", reason=None)
    return result
