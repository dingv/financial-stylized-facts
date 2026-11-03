"""Stratified circular-block percentile intervals for marginal statistics.

No null hypothesis is imposed. Intervals are pointwise, not simultaneous,
and require suitable stationarity, weak dependence, and finite moments.
"""
import hashlib

import numpy as np
from scipy.stats import rankdata

from .conditional import continuous_segments
from .activity import _pearson


NAMES = ["mean", "std", "skewness", "excess_kurtosis", "tail_probability_3sigma", "zero_fraction",
         "volume_abs_pearson", "volume_abs_spearman", "volume_squared_pearson"]


def circular_indices(n, block_length, rng):
    """Fixed-size CBB; wrapping is within a continuous source segment only."""
    starts = rng.integers(0, n, size=(n+block_length-1)//block_length)
    return ((starts[:, None]+np.arange(block_length)) % n).ravel()[:n]


def marginal_statistics(x, volume=None, min_pairs=20):
    """Same finite-sample moment definitions as the descriptive diagnostics."""
    x = np.asarray(x, dtype=float)
    out = np.full(len(NAMES), np.nan)
    if len(x) < 4 or not np.isfinite(x).all():
        return out
    scale = float(np.max(np.abs(x))) or 1.
    y = x/scale
    mean = y.mean()
    centered = y-mean
    m2 = np.mean(centered**2)
    out[0], out[1], out[5] = mean*scale, np.sqrt(m2)*scale, np.mean(x == 0)
    if m2 == 0:
        return out
    n = len(y)
    z = centered/np.sqrt(m2)
    out[2] = np.sqrt(n*(n-1))/(n-2)*np.mean(z**3)
    out[3] = (n-1)/((n-2)*(n-3))*((n+1)*(np.mean(z**4)-3)+6)
    out[4] = np.mean(np.abs(z) > 3)
    if volume is not None:
        v = np.asarray(volume, dtype=float)
        valid = np.isfinite(v)
        abs_r = np.abs(y[valid])
        # Preserve unavailable zero-variance estimates as NaN, not a fake zero.
        for idx, a, b in [(6, v[valid], abs_r), (7, rankdata(v[valid]), rankdata(abs_r)),
                          (8, v[valid], abs_r**2)]:
            value, _, _ = _pearson(a, b, min_pairs)
            out[idx] = np.nan if value is None else value
    return out


def percentile_rows(draws, estimates, names=NAMES, level=.95):
    rows = []
    for i, name in enumerate(names):
        finite = draws[:, i][np.isfinite(draws[:, i])]
        point = estimates[i]
        row = {"metric": name, "estimate": float(point) if np.isfinite(point) else None,
               "lower": None, "upper": None, "bootstrap_se": None, "valid_reps": len(finite),
               "status": "not_computable", "reason": "原统计量不可计算"}
        if np.isfinite(point):
            if len(finite) < .95*len(draws):
                row.update(reason="超过 5% 的重采样结果不可计算")
            elif np.ptp(finite) <= 64*np.finfo(float).eps*np.max(np.abs(finite)):
                row.update(status="degenerate", reason="重采样统计量没有变化，不能据此给出有信息的区间")
            else:
                bounds = np.quantile(finite, [(1-level)/2, (1+level)/2], method="linear")
                row.update(status="computed", reason=None, lower=float(bounds[0]), upper=float(bounds[1]),
                           bootstrap_se=float(finite.std(ddof=1)))
        rows.append(row)
    return rows


def uncertainty_diagnostics(sampled, config, seed_key=""):
    """Resample each contiguous segment independently, holding segment sizes fixed."""
    result = {"status": "disabled", "reason": "本次关闭重采样区间", "method": "stratified_circular_block_percentile",
              "confidence_level": .95, "simultaneous": False, "null_test": False,
              "reps": config.bootstrap_reps, "base_seed": config.bootstrap_seed, "n": 0, "blocks": [],
              "unsupported": ["acf", "leverage", "timescale_asymmetry", "garch_parameter_uncertainty", "conditional_tail_uncertainty"],
              "assumptions": "近似段内平稳和弱依赖、相应统计量所需矩存在；段数与各段样本量固定；不是跨段状态变化的不确定性"}
    if config.bootstrap_reps == 0:
        return result
    frames = [g for _, g in continuous_segments(sampled)]
    segments = [g.log_return.to_numpy(dtype=float) for g in frames]
    volumes = [g.volume.to_numpy(dtype=float) for g in frames] if config.volume_kind == "interval" else None
    n = sum(map(len, segments))
    result.update(n=n, segment_lengths=[len(s) for s in segments])
    if n < 200:
        result.update(status="insufficient_data", reason="有效收益少于 200 条，暂不计算近似区间")
        return result
    work = n*config.bootstrap_reps*len(config.bootstrap_block_lengths)
    result["estimated_work"] = work
    if work > config.bootstrap_max_work:
        result.update(status="resource_limit", reason="重采样工作量超过上限；未抽取数据或缩减重复次数冒充完整结果")
        return result
    original = np.concatenate(segments)
    estimates = marginal_statistics(original, np.concatenate(volumes) if volumes is not None else None, config.min_pairs)
    if estimates[1] == 0:
        result.update(status="zero_variance", reason="收益恒定，重采样无法提供有信息的不确定性")
        return result
    for block_length in config.bootstrap_block_lengths:
        row = {"block_length": block_length, "status": "insufficient_data", "reason": None, "intervals": []}
        if any(len(s) < 2*block_length for s in segments) or n < 20*block_length:
            row["reason"] = "至少一连续段不足两个块，或全路径不足二十个块；未删除短段凑样本"
            result["blocks"].append(row)
            continue
        # Independent keyed streams make adding paths or block choices order-invariant.
        digest = hashlib.sha256(f"{config.bootstrap_seed}:{seed_key}:{block_length}".encode()).digest()
        seed = int.from_bytes(digest[:8], "little")
        row["seed"] = seed
        rng = np.random.default_rng(seed)
        draws = np.empty((config.bootstrap_reps, len(NAMES)))
        for b in range(config.bootstrap_reps):
            indices = [circular_indices(len(s), block_length, rng) for s in segments]
            x = np.concatenate([s[ix] for s, ix in zip(segments, indices)])
            v = np.concatenate([s[ix] for s, ix in zip(volumes, indices)]) if volumes is not None else None
            draws[b] = marginal_statistics(x, v, config.min_pairs)
        count = len(NAMES) if volumes is not None else 6
        row["intervals"] = percentile_rows(draws[:, :count], estimates[:count], NAMES[:count])
        row.update(status="computed", reason=None)
        result["blocks"].append(row)
    available = sum(b["status"] == "computed" for b in result["blocks"])
    result.update(status="computed" if available == len(result["blocks"]) else "partially_computed" if available else "not_computable",
                  reason=None if available else "数据不足以支撑所选块长；请查看各方案原因")
    return result
