"""Interval volume and coarse/fine volatility: descriptive, paired diagnostics."""
import numpy as np
from scipy.stats import rankdata

from .diagnostics import _arrays


def _pearson(x, y, min_pairs):
    """Pairwise coefficient with independent scaling, no IID p value."""
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    n = len(x)
    if n < min_pairs:
        return None, n, "insufficient_pairs"
    x = x / max(float(np.max(np.abs(x))), np.finfo(float).tiny)
    y = y / max(float(np.max(np.abs(y))), np.finfo(float).tiny)
    x, y = x-x.mean(), y-y.mean()
    xx, yy = np.dot(x, x), np.dot(y, y)
    if xx <= n*np.finfo(float).eps**2 or yy <= n*np.finfo(float).eps**2:
        return None, n, "zero_or_near_zero_pair_variance"
    return float(np.clip(np.dot(x, y)/np.sqrt(xx*yy), -1, 1)), n, "computed"


def volume_diagnostics(sampled, config):
    result = {"status": "not_applicable", "reason": "未提供已声明口径的区间成交量",
              "kind": config.volume_kind, "unit": config.volume_unit, "n": 0,
              "correlations": {}, "bins": [], "uncertainty": "not_implemented",
              "seasonality_adjustment": "not_implemented"}
    if config.volume_kind == "none":
        return result
    volume = sampled["volume"].to_numpy(dtype=float)
    returns = sampled["log_return"].to_numpy(dtype=float)
    valid = np.isfinite(volume) & np.isfinite(returns)
    volume, returns = volume[valid], returns[valid]
    result["n"] = len(returns)
    result["unpaired_slots"] = int(len(sampled)-len(returns))
    # Rescale before squaring, preserving correlations even for extreme magnitudes.
    abs_r = np.abs(returns)
    scaled_r = abs_r/max(float(abs_r.max()) if len(abs_r) else 0., np.finfo(float).tiny)
    for name, values in [("absolute", scaled_r), ("squared", scaled_r**2)]:
        pearson, n, status = _pearson(volume, values, config.min_pairs)
        spearman, _, rank_status = _pearson(rankdata(volume), rankdata(values), config.min_pairs)
        result["correlations"][name] = {"pearson": pearson, "spearman": spearman, "pair_count": n,
                                         "status": status, "rank_status": rank_status}
    result["status"] = result["correlations"]["absolute"]["status"]
    result["reason"] = {"computed": None, "insufficient_pairs": "同一区间的收益与成交量配对不足",
                        "zero_or_near_zero_pair_variance": "成交量或波动几乎没有变化，无法计算相关"}[result["status"]]
    if len(volume) >= config.min_pairs:
        # Quantile edges are unique: equal volumes never split into arbitrary ranks.
        cuts = np.unique(np.quantile(volume, [0, .2, .4, .6, .8, 1]))
        inner = cuts[1:-1]
        labels = np.searchsorted(inner, volume, side="right")
        for label in np.unique(labels):
            mask = labels == label
            result["bins"].append({"bin": len(result["bins"])+1, "n": int(mask.sum()),
                                   "volume_min": float(volume[mask].min()), "volume_max": float(volume[mask].max()),
                                   "mean_volume": float(np.max(volume[mask])*np.mean(volume[mask]/np.max(volume[mask]))) if np.max(volume[mask]) else 0.,
                                   "mean_absolute_return": float(abs_r[mask].mean())})
    return result


def coarse_fine_blocks(segments, factor):
    """C=abs(sum r), F=mean(abs r), using complete non-overlapping blocks."""
    if isinstance(factor, bool) or not isinstance(factor, (int, np.integer)) or factor < 2:
        raise ValueError("coarse factor must be an integer >= 2")
    pairs, discarded, invalid = [], 0, 0
    for segment in _arrays(segments):
        n = len(segment)//factor
        discarded += len(segment)-n*factor
        blocks = segment[:n*factor].reshape(n, factor)
        good = np.isfinite(blocks).all(axis=1)
        coarse, fine = np.full(n, np.nan), np.full(n, np.nan)
        coarse[good] = np.abs(blocks[good].sum(axis=1))
        fine[good] = np.abs(blocks[good]).mean(axis=1)
        invalid += int((~good).sum())
        pairs.append((coarse, fine))
    return pairs, {"total_blocks": sum(len(c) for c, _ in pairs), "invalid_blocks": invalid,
                   "discarded_return_slots": discarded}


def timescale_asymmetry(segments, factor=30, max_lag=30, min_pairs=20):
    """A(k)=corr(F_t,C_{t+k}); D(k)=A(k)-A(-k), k>0.

    Negative D means coarse-past/fine-future correlation is stronger than reverse.
    This is an operational coarse/fine comparison, not a causality test.
    """
    if isinstance(max_lag, bool) or not isinstance(max_lag, (int, np.integer)) or max_lag < 1 or min_pairs < 2:
        raise ValueError("max_lag must be positive; min_pairs >= 2")
    pairs, quality = coarse_fine_blocks(segments, factor)
    limit = min(max_lag, max((len(c)-1 for c, _ in pairs), default=0))
    limit = max(0, limit)
    rows = []
    for lag in range(-limit, limit+1):
        xs, ys = [], []
        for coarse, fine in pairs:
            if len(coarse) <= abs(lag):
                continue
            if lag > 0:
                xs.append(fine[:-lag]); ys.append(coarse[lag:])
            elif lag < 0:
                xs.append(fine[-lag:]); ys.append(coarse[:lag])
            else:
                xs.append(fine); ys.append(coarse)
        x = np.concatenate(xs) if xs else np.array([])
        y = np.concatenate(ys) if ys else np.array([])
        value, n, status = _pearson(x, y, min_pairs)
        rows.append({"lag": lag, "correlation": value, "pair_count": n, "status": status})
    lookup = {r["lag"]: r for r in rows}
    differences = []
    for lag in range(1, limit+1):
        forward, reverse = lookup[lag], lookup[-lag]
        available = forward["correlation"] is not None and reverse["correlation"] is not None
        differences.append({"lag": lag, "difference": forward["correlation"]-reverse["correlation"] if available else None,
                            "fine_leads_coarse": forward["correlation"], "coarse_leads_fine": reverse["correlation"],
                            "forward_pairs": forward["pair_count"], "reverse_pairs": reverse["pair_count"]})
    computed = any(r["difference"] is not None for r in differences)
    return {"status": "computed" if computed else "not_computable",
            "reason": None if computed else "完整粗尺度区间配对不足，或区间波动没有变化",
            "factor": factor, "quality": quality, "correlations": rows, "differences": differences,
            "definition": "C=abs(sum r); F=mean(abs r); A(k)=corr(F_t,C_(t+k)); D(k)=A(k)-A(-k)",
            "estimator": "lag_specific_pairwise_pearson", "uncertainty": "not_implemented"}


def activity_diagnostics(sampled, config):
    # Remove only the structural first return of each session, not internal gaps.
    segments = [g["log_return"].to_numpy(dtype=float)[1:]
                for _, g in sampled.groupby("session_id", sort=False)]
    return {"volume_volatility": volume_diagnostics(sampled, config),
            "timescale_asymmetry": timescale_asymmetry(segments, config.coarse_factor, config.max_lag, config.min_pairs)}
