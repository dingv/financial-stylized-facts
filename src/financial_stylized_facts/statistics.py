"""Descriptive estimates with explicit failure reasons and pair counts."""
import numpy as np
from scipy import signal, stats


def distribution(values):
    values = np.asarray(values, dtype=float)
    if np.isinf(values).any():
        raise ValueError("收益中不能包含 Infinity")
    x = values[np.isfinite(values)]
    result = {"n": len(x), "mean": None, "std": None, "zero_fraction": None,
              "excess_kurtosis": None, "excess_kurtosis_uncorrected": None,
              "pearson_kurtosis": None, "status": "insufficient_data", "reason": "没有有效收益",
              "estimator": "scipy_fisher_bias_false", "tail_counts": {},
              "uncertainty": {"status": "not_computed", "reason": "此函数只计算点估计；报告层可另行计算区块重采样近似区间"}}
    if not len(x):
        return result
    scale = float(np.max(np.abs(x))) or 1.0
    normalized = x / scale
    spread = float(normalized.std(ddof=0))
    result.update(mean=float(normalized.mean() * scale), std=float(spread * scale), zero_fraction=float(np.mean(x == 0)))
    if spread == 0:
        result.update(status="zero_variance", reason="所有收益相同；峰度与标准化尾概率不可计算")
        return result
    if len(x) < 4:
        result["reason"] = "修正超额峰度至少需要 4 个收益观测"
        return result
    scaled = (normalized - normalized.mean()) / spread
    result.update(status="computed", reason=None,
                  excess_kurtosis=float(stats.kurtosis(scaled, fisher=True, bias=False)),
                  excess_kurtosis_uncorrected=float(stats.kurtosis(scaled, fisher=True, bias=True)),
                  pearson_kurtosis=float(stats.kurtosis(scaled, fisher=False, bias=True)))
    result["tail_counts"] = {str(k): {"count": int(np.sum(np.abs(scaled) > k)), "probability": float(np.mean(np.abs(scaled) > k))} for k in [2, 3, 4]}
    return result


def autocorrelation(segments, max_lag=30, min_pairs=20):
    """Global-mean, fixed-denominator ACF; gaps and session edges never pair.

    This reduces to the usual adjusted=False ACF for one complete segment.
    Missing entries stay on their original grid. Pair counts are reported.
    """
    if max_lag < 1 or min_pairs < 2:
        raise ValueError("max_lag 必须为正，min_pairs 至少为 2")
    segments = [np.asarray(s, dtype=float) for s in segments if len(s)]
    if any(np.isinf(s).any() for s in segments):
        raise ValueError("ACF 输入不能包含 Infinity")
    finite = [s[np.isfinite(s)] for s in segments]
    n = sum(len(s) for s in finite)
    result = {"status": "insufficient_data", "reason": "有效观测或同段配对不足", "n": n,
              "estimator": "session_masked_fixed_denominator", "lags": [], "values": [], "pair_counts": [],
              "uncertainty": {"status": "not_implemented", "reason": "未提供显著性检验；不能凭相关系数判定长记忆"}}
    if n < 2:
        return result
    scale = max((float(np.max(np.abs(s))) for s in finite if len(s)), default=1.0) or 1.0
    segments = [s / scale for s in segments]
    finite = [s[np.isfinite(s)] for s in segments]
    mean = sum(float(s.sum()) for s in finite) / n
    denominator = sum(float(np.sum((s - mean) ** 2)) for s in finite)
    if denominator == 0:
        result.update(status="zero_variance", reason="序列零方差，ACF 不可计算")
        return result
    lagmax = min(max_lag, max(len(s) for s in segments) - 1)
    numerator = np.zeros(lagmax + 1)
    pairs = np.zeros(lagmax + 1, dtype=np.int64)
    for s in segments:
        mask = np.isfinite(s)
        centered = np.where(mask, s - mean, 0.0)
        length = min(lagmax + 1, len(s))
        numerator[:length] += signal.correlate(centered, centered, mode="full", method="fft")[len(s)-1:len(s)-1+length]
        pairs[:length] += np.rint(signal.correlate(mask.astype(float), mask.astype(float), mode="full", method="fft")[len(s)-1:len(s)-1+length]).astype(np.int64)
    values = [float(np.clip(v / denominator, -1, 1)) if p >= min_pairs else None for v, p in zip(numerator, pairs)]
    if n >= min_pairs:
        values[0] = 1.0
    result.update(lags=list(range(lagmax+1)), values=values, pair_counts=pairs.tolist())
    if any(v is not None for v in values[1:]):
        result.update(status="computed", reason=None)
    return result


def three_acfs(sampled, max_lag=30, min_pairs=20):
    segments = [g["log_return"].to_numpy(dtype=float) for _, g in sampled.groupby("session_id", sort=False)]
    return {name: autocorrelation([transform(s) for s in segments], max_lag, min_pairs)
            for name, transform in [("return", lambda x: x), ("absolute_return", np.abs), ("squared_return", np.square)]}
