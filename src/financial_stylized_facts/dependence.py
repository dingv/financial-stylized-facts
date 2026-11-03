"""Time-direction and long-horizon diagnostics, without causal/long-memory claims."""
import numpy as np
from scipy.signal import correlate

from .diagnostics import _arrays
from .statistics import autocorrelation


def lagged_volatility_correlation(segments, max_lag=30, min_pairs=20, proxy="squared"):
    """Pairwise Pearson corr(r[t], proxy(r[t+k])); k>0 means future volatility.

    FFT masked moments retain gaps and session edges. Means and variances are
    recomputed from eligible pairs for each lag, unlike fixed-denominator ACF.
    """
    if proxy not in {"absolute", "squared"}:
        raise ValueError("proxy 必须为 absolute 或 squared")
    if not isinstance(max_lag, (int, np.integer)) or not 1 <= max_lag <= 2000 or min_pairs < 2:
        raise ValueError("max_lag 必须为 1–2000 的整数，min_pairs 至少为 2")
    arrays = [a for a in _arrays(segments) if len(a)]
    valid = [a[np.isfinite(a)] for a in arrays]
    n = sum(len(a) for a in valid)
    result = {"status": "insufficient_data", "reason": "有效观测或同段配对不足", "n": n,
              "proxy": proxy, "estimator": "lag_specific_pairwise_pearson",
              "definition": "corr(r[t], proxy(r[t+k])); positive k = future volatility",
              "lags": [], "values": [], "pair_counts": [], "point_status": [],
              "uncertainty": {"status": "not_implemented"}}
    if n < 2:
        return result
    scale = max(float(np.max(abs(a))) for a in valid if len(a)) or 1.
    arrays = [a/scale for a in arrays]
    transform = np.abs if proxy == "absolute" else np.square
    mean_x = sum(float(np.nansum(a)) for a in arrays)/n
    mean_y = sum(float(np.nansum(transform(a))) for a in arrays)/n
    limit = min(max_lag, max(len(a) for a in arrays)-1)
    lags = np.arange(-limit, limit+1)
    counts = np.zeros(len(lags), dtype=np.int64)
    moments = np.zeros((5, len(lags)))
    for a in arrays:
        mask = np.isfinite(a).astype(float)
        x = np.where(mask, a-mean_x, 0.)
        y = np.where(mask, transform(a)-mean_y, 0.)
        local = min(limit, len(a)-1)
        dest = slice(limit-local, limit+local+1)
        source = slice(len(a)-1-local, len(a)+local)
        counts[dest] += np.rint(correlate(mask, mask, method="fft")[source]).astype(np.int64)
        # correlate(left, right)[N-1+k] = sum(left[t+k]*right[t]).
        for i, (left, right) in enumerate([(mask, x), (y, mask), (mask, x*x), (y*y, mask), (y, x)]):
            moments[i, dest] += correlate(left, right, method="fft")[source]
    values, statuses = [], []
    for i, count in enumerate(counts):
        if count < min_pairs:
            values.append(None)
            statuses.append("insufficient_pairs")
            continue
        sx, sy, sxx, syy, sxy = moments[:, i]
        vx, vy = sxx-sx*sx/count, syy-sy*sy/count
        tol = 64*np.finfo(float).eps
        if vx <= tol*max(abs(sxx), sx*sx/count) or vy <= tol*max(abs(syy), sy*sy/count):
            values.append(None)
            statuses.append("zero_or_near_zero_pair_variance")
            continue
        values.append(float(np.clip((sxy-sx*sy/count)/np.sqrt(vx*vy), -1, 1)))
        statuses.append("computed")
    result.update(lags=lags.tolist(), values=values, pair_counts=counts.tolist(), point_status=statuses)
    if any(v is not None for lag, v in zip(lags, values) if lag != 0):
        result.update(status="computed", reason=None)
    elif any(s == "zero_or_near_zero_pair_variance" for s in statuses):
        result.update(status="zero_variance", reason="可配对序列的方差为零或过小，相关系数不可计算")
    return result


def dependence_diagnostics(sampled, config):
    ordered = sampled.sort_values("timestamp", kind="stable")
    segments = [g["log_return"].to_numpy(dtype=float) for _, g in ordered.groupby("session_id", sort=False)]
    leverage = {proxy: lagged_volatility_correlation(segments, config.max_lag, config.min_pairs, proxy)
                for proxy in ["squared", "absolute"]}
    full = autocorrelation([abs(a) for a in segments], config.volatility_max_lag, config.min_pairs)
    blocks = []
    for index, positions in enumerate(np.array_split(np.arange(len(ordered)), config.stability_blocks)):
        block = ordered.iloc[positions]
        parts = [abs(g["log_return"].to_numpy(dtype=float)) for _, g in block.groupby("session_id", sort=False)]
        acf = autocorrelation(parts, config.volatility_max_lag, config.min_pairs)
        # A return reaching back across a diagnostic split stays assigned to its
        # ending time; no ACF pair itself crosses that split or a session edge.
        blocks.append({"block": index+1, "slots": len(block),
                       "start": str(block["timestamp"].iloc[0]) if len(block) else None,
                       "end": str(block["timestamp"].iloc[-1]) if len(block) else None, "acf": acf})
    persistence = {"status": full["status"], "reason": full["reason"], "full": full, "blocks": blocks,
                   "requested_max_lag": config.volatility_max_lag, "split_method": "chronological_equal_observation_slots",
                   "long_memory_test": {"status": "not_implemented", "reason": "延长 ACF 与分段比较只是诊断，未做长记忆或幂律检验"}}
    return {"leverage": leverage, "volatility_persistence": persistence}
