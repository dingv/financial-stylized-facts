"""Finite-range absolute-return decay on Pearson pairs at their original lags."""
import numpy as np


def _pearson(moments, n):
    x, y, xx, yy, xy = np.moveaxis(moments, -1, 0)
    vx, vy = xx-x*x/n, yy-y*y/n
    valid = (vx > 64*np.finfo(float).eps*xx) & (vy > 64*np.finfo(float).eps*yy)
    denominator = np.sqrt(np.maximum(vx, 0)*np.maximum(vy, 0))
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(valid, np.clip((xy-x*y/n)/denominator, -1, 1), np.nan)


def _pair_interval(parts, n, block, reps, rng):
    # Resample starts of already aligned lag pairs within each continuous run.
    totals = np.zeros((reps, 5))
    variable = False
    for values in parts:
        size = len(values)
        length = min(size, block)
        prefix = np.vstack((np.zeros(5), values.cumsum(axis=0)))
        count, remainder = divmod(size, length)
        variable |= size > length
        for first in range(0, reps, 32):
            target = totals[first:first+32]
            starts = rng.integers(size-length+1, size=(len(target), count))
            target += (prefix[starts+length]-prefix[starts]).sum(axis=1)
            if remainder:
                starts = rng.integers(size-remainder+1, size=len(target))
                target += prefix[starts+remainder]-prefix[starts]
    estimates = _pearson(totals, n)
    if not variable or not np.all(np.isfinite(estimates)):
        return None, None
    return tuple(map(float, np.quantile(estimates, [.025, .975])))


def loglog_decay(segments, config):
    end = config.volatility_max_lag
    runs = []
    for segment in segments:
        edges = np.flatnonzero(np.diff(np.r_[False, np.isfinite(segment), False]))
        runs.extend(np.abs(segment[a:b]) for a,b in edges.reshape(-1,2) if b-a > 1)
    n = sum(map(len, runs))
    block = max(1, int(np.cbrt(n)))
    reps = config.decay_bootstrap_reps
    interval_work = reps*end*sum((len(v)+block-1)//block for v in runs)
    intervals = reps > 0 and interval_work <= config.decay_bootstrap_max_work
    rng = np.random.default_rng(config.bootstrap_seed)
    result = dict(start=5, end=end, rows=[], beta=None, amplitude=None, r_squared=None,
                  reps=reps, block_length=block, interval_reason=None if intervals else
                  ("已关闭重抽样" if not reps else "超过重抽样工作量预算"),
                  status="insufficient_data", conclusion="insufficient_data")
    scale = max((a.max() for a in runs), default=0.)
    if end < 6 or not scale:
        result["summary"] = "拟合需要至少两个预设滞后点和有变化的绝对收益。"
        return result
    runs = [a/scale for a in runs]
    for lag in range(1, end+1):
        parts = []
        for a in runs:
            if len(a) > lag:
                x, y = a[:-lag], a[lag:]
                parts.append(np.column_stack((x,y,x*x,y*y,x*y)))
        pairs = sum(map(len, parts))
        row = dict(lag=lag, pairs=pairs, acf=None, lower=None, upper=None)
        result["rows"].append(row)
        if pairs < config.min_pairs:
            continue
        estimate = _pearson(sum(v.sum(axis=0) for v in parts), pairs)
        if np.isfinite(estimate):
            row["acf"] = float(estimate)
            if intervals:
                row["lower"], row["upper"] = _pair_interval(parts, pairs, block, reps, rng)

    rows = result["rows"][4:]
    if any(r["acf"] is None for r in rows):
        result["summary"] = f"lag 5–{end} 的配对或方差不足，无法评估完整范围。"
        return result
    result["status"] = "computed"
    acf = np.array([r["acf"] for r in rows])
    if np.any(acf <= 0):
        result.update(conclusion="mixed", summary=f"lag 5–{end} 中有 {int(sum(acf <= 0))} 个绝对收益相关系数为零或负，未见全范围持续正相关。")
        return result
    k = np.arange(5, end+1)
    y = np.log(acf)
    slope, intercept = np.polyfit(np.log(k), y, 1)
    residual = y - (intercept + slope*np.log(k))
    total = np.sum((y-y.mean())**2)
    beta = float(-slope)
    result.update(beta=beta, amplitude=float(np.exp(intercept)),
                  r_squared=float(1-residual@residual/total) if total > 0 else None)
    summary = f"lag 5–{end} 的绝对收益自相关始终为正，从 {acf[0]:.3f} 到 {acf[-1]:.3f}。"
    endpoint = rows[-1]["lower"]
    if 0 < beta < 1 and acf[-1] < acf[0]:
        if endpoint is not None and endpoint > 0:
            result.update(conclusion="indicative", summary=summary+"远端仍有正相关，衰减的具体形式尚不明确。")
        else:
            result.update(conclusion="inconclusive", summary=summary+"远端的正相关缺少区间支持。")
    else:
        result.update(conclusion="mixed", summary=summary+"拟合未呈现预设的缓慢下降形态。")
    return result
