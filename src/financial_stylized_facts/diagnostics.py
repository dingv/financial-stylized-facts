"""Asymmetry, scale aggregation and intermittency: descriptive, not tests.

Each caller supplies one asset/path. Session edges and missing values retain
their meaning; aggregate blocks never shift to hide an invalid observation.
"""
import numpy as np
import pandas as pd
from scipy import stats

from .statistics import distribution


def _arrays(segments):
    arrays = [np.asarray(s, dtype=float) for s in segments]
    if any(a.ndim != 1 or np.isinf(a).any() for a in arrays):
        raise ValueError("需要一维收益序列；允许 NaN 缺口，不允许 Infinity")
    return arrays


def _finite(arrays):
    return np.concatenate([a[np.isfinite(a)] for a in arrays]) if arrays else np.array([])


def signed_runs(segments):
    """Runs of strictly same-sign returns; zero, gap, session and sign break.

    Censoring flags distinguish observed reversals/zeros from data boundaries.
    Cumulative values are log returns, not percentage drawdowns from a peak.
    """
    runs = []
    for a in _arrays(segments):
        i = 0
        while i < len(a):
            if not np.isfinite(a[i]) or a[i] == 0:
                i += 1
                continue
            start, sign = i, int(np.sign(a[i]))
            while i < len(a) and np.isfinite(a[i]) and np.sign(a[i]) == sign:
                i += 1
            runs.append({"sign": sign, "length": i-start,
                         "log_return": float(a[start:i].sum()),
                         "left_censored": start == 0 or not np.isfinite(a[start-1]),
                         "right_censored": i == len(a) or not np.isfinite(a[i])})
    return runs


def asymmetry(segments):
    arrays = _arrays(segments)
    x = _finite(arrays)
    result = {"status": "insufficient_data", "reason": "偏度至少需要 3 个有效收益", "n": len(x),
              "skewness": None, "estimator": "adjusted_fisher_pearson",
              "quantile_method": "linear", "quantiles": {}, "tails": [], "runs": {},
              "uncertainty": {"status": "not_implemented"}}
    if len(x):
        result["quantiles"] = {str(p): float(np.quantile(x, p, method="linear")) for p in [.01, .05, .5, .95, .99]}
    if len(x) >= 3:
        scale = float(np.max(abs(x))) or 1.
        y = x/scale
        if np.std(y) == 0:
            result.update(status="zero_variance", reason="常数收益的偏度和标准差尾部比较不可计算")
        else:
            result.update(status="computed", reason=None, skewness=float(stats.skew(y, bias=False)))
            z = (y-y.mean())/y.std(ddof=0)
            result["tails"] = [{"sigma": k, "left_count": int(np.sum(z < -k)), "right_count": int(np.sum(z > k)),
                                "left_probability": float(np.mean(z < -k)), "right_probability": float(np.mean(z > k))} for k in [1, 2, 3]]
    runs = signed_runs(arrays)
    for name, sign in [("up", 1), ("down", -1)]:
        selected = [r for r in runs if r["sign"] == sign]
        complete = [r for r in selected if not (r["left_censored"] or r["right_censored"])]
        magnitudes = [abs(r["log_return"]) for r in complete]
        result["runs"][name] = {"observed_count": len(selected), "complete_count": len(complete),
                               "boundary_censored_count": len(selected)-len(complete),
                               "median_abs_log_return": float(np.median(magnitudes)) if magnitudes else None,
                               "q95_abs_log_return": float(np.quantile(magnitudes, .95)) if magnitudes else None,
                               "mean_length": float(np.mean([r["length"] for r in complete])) if complete else None}
    return result


def aggregate_returns(segments, factor):
    """Nonoverlapping sums anchored at the first return slot of each segment.

    The caller removes only the structural first-price NaN, not data gaps.
    """
    if not isinstance(factor, (int, np.integer)) or isinstance(factor, bool) or factor < 1:
        raise ValueError("factor 必须为正整数")
    chunks, discarded, invalid, blocks = [], 0, 0, 0
    for a in _arrays(segments):
        count = len(a)//factor
        discarded += len(a) % factor
        matrix = a[:count*factor].reshape(count, factor)
        valid = np.isfinite(matrix).all(axis=1)
        sums = np.full(count, np.nan)
        sums[valid] = matrix[valid].sum(axis=1)
        chunks.append(sums)
        invalid += int(np.sum(~valid))
        blocks += count
    return chunks, {"total_blocks": blocks, "invalid_blocks": invalid, "discarded_partial_slots": discarded}


def scale_diagnostics(segments, factors):
    arrays = _arrays(segments)
    output = []
    probabilities = np.arange(1, 100)/100
    normal = stats.norm.ppf(probabilities)
    for factor in factors:
        chunks, quality = aggregate_returns(arrays, factor)
        x = _finite(chunks)
        moments = distribution(x)
        distance = None
        if moments["status"] == "computed":
            y = x/(float(np.max(abs(x))) or 1.)
            z = (y-y.mean())/y.std(ddof=0)
            distance = float(np.sqrt(np.mean((np.quantile(z, probabilities, method="linear")-normal)**2)))
        output.append({"factor": int(factor), **quality, "n": moments["n"], "status": moments["status"], "reason": moments["reason"],
                       "excess_kurtosis": moments["excess_kurtosis"], "normal_quantile_rmse": distance,
                       "small_sample": moments["n"] < 100})
    return {"status": "computed" if any(r["status"] == "computed" for r in output) else "insufficient_data",
            "method": "nonoverlapping_log_return_sum", "anchor": "first_sampled_price_each_session",
            "normal_quantile_probabilities": probabilities.tolist(), "quantile_method": "linear",
            "uncertainty": {"status": "not_implemented"}, "scales": output}


def rolling_rms(segments, window):
    if not isinstance(window, (int, np.integer)) or isinstance(window, bool) or window < 2:
        raise ValueError("window 必须是至少为 2 的整数")
    output = []
    for a in _arrays(segments):
        finite = a[np.isfinite(a)]
        scale = float(np.max(abs(finite))) if len(finite) else 1.
        scale = scale or 1.
        squared = pd.Series((a/scale)**2)
        output.append(np.sqrt(squared.rolling(window, min_periods=window).mean().clip(lower=0).to_numpy())*scale)
    return output


def intermittency(segments, window=20, threshold=3.):
    arrays = _arrays(segments)
    x = _finite(arrays)
    rms = rolling_rms(arrays, window)
    n_rms = sum(int(np.isfinite(a).sum()) for a in rms)
    result = {"status": "insufficient_data", "reason": "至少需要两个有效收益", "n": len(x),
              "window": window, "threshold_sigma": threshold, "rms_valid_windows": n_rms,
              "rms_coverage": n_rms/len(x) if len(x) else None,
              "threshold_reference": "abs(return - full_path_mean) / full_path_std_ddof0",
              "exceedance_count": None, "exceedance_fraction": None, "episodes": {},
              "uncertainty": {"status": "not_implemented"}}
    if not np.isfinite(threshold) or threshold <= 0:
        raise ValueError("threshold 必须有限且为正")
    if len(x) < 2:
        return result, rms
    scale = float(np.max(abs(x))) or 1.
    y = x/scale
    mean, std = y.mean(), y.std(ddof=0)
    if std == 0:
        result.update(status="zero_variance", reason="收益零方差，标准化大幅波动阈值不可计算")
        return result, rms
    flags = [np.where(np.isfinite(a), (abs(a/scale-mean) > threshold*std).astype(float), np.nan) for a in arrays]
    runs = signed_runs(flags)
    lengths = [r["length"] for r in runs]
    complete = [r["length"] for r in runs if not (r["left_censored"] or r["right_censored"])]
    count = sum(lengths)
    result.update(status="computed", reason=None, exceedance_count=count, exceedance_fraction=count/len(x),
                  episodes={"observed_count": len(runs), "boundary_censored_count": len(runs)-len(complete),
                            "max_observed_length": max(lengths) if lengths else 0,
                            "mean_complete_length": float(np.mean(complete)) if complete else None})
    return result, rms


def analyze_diagnostics(sampled, config):
    # First entry is the structural NaN from differencing the first price.
    segments = [g["log_return"].to_numpy(dtype=float) for _, g in sampled.groupby("session_id", sort=False)]
    returns = [s[1:] for s in segments]
    intermittent, rms = intermittency(segments, config.rms_window, config.burst_threshold)
    return {"asymmetry": asymmetry(segments), "aggregation": scale_diagnostics(returns, config.aggregation_factors),
            "intermittency": intermittent}, rms
