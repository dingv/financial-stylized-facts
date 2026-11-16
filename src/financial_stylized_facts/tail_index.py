"""Separate continuous Pareto fits for gains and losses (Clauset et al., 2009)."""
import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import log_ndtr
from scipy.stats import norm

from .diagnostics import aggregate_returns
from .intermittency import seed_for


def fit_side(values):
    values = np.asarray(values, dtype=float)
    x, counts = np.unique(values[np.isfinite(values) & (values > 0)], return_counts=True)
    if len(x) < 2:
        return {"k": None, "reason": "不同尾部幅度不足两个", "n": 0}
    # Summing adjacent log gaps avoids cancellation when a tail range is narrow.
    logs = np.log(x)
    gaps = np.log1p(np.diff(x) / x[:-1])
    sizes = np.cumsum(counts[::-1])[::-1]
    sums = np.cumsum((gaps * sizes[1:])[::-1])[::-1]
    k = sizes[:-1] / sums
    # KS on a subset of ranks bounds the full KS from below. This prunes
    # candidates without changing the minimum over all distinct thresholds.
    bounds = np.zeros(len(k))
    i = np.arange(len(k))
    for fraction in np.linspace(0, 1, 33):
        j = i + ((len(x) - 1 - i) * fraction).astype(int)
        gap = np.abs(sizes[j] / sizes[i] - np.exp(-k * (logs[j] - logs[i])))
        bounds = np.maximum(bounds, gap)
    best, winner = np.inf, 0
    for i in np.argsort(bounds):
        if bounds[i] > best:
            break
        model = np.exp(-k[i] * (logs[i:] - logs[i]))
        distance = float(np.max(np.abs(sizes[i:] / sizes[i] - model)))
        if distance < best or (distance == best and i < winner):
            best, winner = distance, i
    return {"xmin": float(x[winner]), "k": float(k[winner]), "n": int(sizes[winner]),
            "ks": best, "reason": None}


def sides(values):
    return {side: fit_side(sign * values) for side, sign in (("loss", -1), ("gain", 1))}


def compare_models(x, fit):
    """Relative log likelihood on the same tail; work in log(x/xmin) units."""
    if fit["k"] is None:
        return {}
    y = np.log(x[x >= fit["xmin"]] / fit["xmin"])
    k = fit["k"]
    pareto = np.log(k) - k*y
    excess = np.expm1(y)
    exponential = y - np.log(excess.mean()) - excess/excess.mean()

    def comparison(alternative):
        delta = pareto - alternative
        spread = delta.std()
        ratio = float(delta.sum())
        p = float(2*norm.sf(abs(ratio)/(np.sqrt(len(y))*spread))) if spread > 0 else None
        return {"log_ratio": ratio, "p": p}

    # Profile the scale of the lower-truncated normal on log magnitudes.
    # t is the standardized truncation point. As t -> infinity the fitted
    # distribution approaches the Pareto boundary in the original units.
    mean, second = y.mean(), np.mean(y*y)
    def lognormal(t):
        v = 2 / (np.hypot(t*mean, 2*np.sqrt(second)) + t*mean)
        return np.log(v) - 0.5*(v*y+t)**2 - 0.5*np.log(2*np.pi) - log_ndtr(-t)
    search = minimize_scalar(lambda t: -lognormal(t).sum(), bounds=(-100,100), method="bounded")
    alternative = comparison(lognormal(search.x))
    if search.x > 99.9 or not search.success:
        alternative = {"log_ratio": None, "p": None, "reason": "对数正态拟合接近极限或未收敛"}
    return {"exponential": comparison(exponential), "lognormal": alternative}


def tail_diagnostics_by_scale(sampled, config, key):
    segments = [g.log_return.to_numpy()[1:] for _,g in sampled.groupby("session_id", sort=False)]
    raw = sampled.log_return.to_numpy()
    observed = sides(raw)
    for side, sign in (("loss",-1), ("gain",1)):
        observed[side]["comparisons"] = compare_models(sign*raw, observed[side])

    comparisons = []
    available = 0
    for side, label in (("loss", "下跌尾"), ("gain", "上涨尾")):
        for alt, test in observed[side]["comparisons"].items():
            if test["p"] is None:
                continue
            available += 1
            if test["p"] < .05:
                model = "指数" if alt == "exponential" else "对数正态"
                comparisons.append(f"{label}：幂律优于{model}" if test["log_ratio"] > 0
                                   else f"{label}：{model}优于幂律")
    note = "；".join(comparisons) if comparisons else (
        "已完成的分布比较均未分出胜者" if available else "分布比较不可计算")
    note += f"（幂律与指数、对数正态；可计算 {available}/4 项）。"

    scales = {}
    for factor in config.aggregation_factors:
        chunks, _ = aggregate_returns(segments, factor)
        runs = []
        for chunk in chunks:
            valid = np.isfinite(chunk)
            edges = np.flatnonzero(np.diff(np.r_[False,valid,False]))
            runs.extend(chunk[start:end] for start,end in edges.reshape(-1,2))
        x = np.concatenate(runs) if runs else np.empty(0)
        block = max(1, round(len(x)**(1/3)))
        row = {"point": sides(x), "block": block, "reps": config.bootstrap_reps,
               "draws": {"loss": [], "gain": []}, "reason": None}
        scales[factor] = row
        if not len(x) or not config.bootstrap_reps:
            row["reason"] = "无有效收益或已关闭重抽样"
            continue
        if len(x)*config.bootstrap_reps > config.bootstrap_max_work:
            row["reason"] = "超过重抽样工作量预算"
            continue
        if not any(r["k"] is not None for r in row["point"].values()):
            row["reason"] = "尾部样本不足"
            continue
        rng = np.random.default_rng(seed_for(config,key,f"tail-index-{factor}"))
        plans = [(a, np.arange(min(len(a),block))) for a in runs]
        for _ in range(config.bootstrap_reps):
            blocks = []
            for a, offsets in plans:
                n = len(a)
                starts = rng.integers(n, size=(n+len(offsets)-1)//len(offsets))
                blocks.append(a[((starts[:,None]+offsets)%n).ravel()[:n]])
            for side, fit in sides(np.concatenate(blocks)).items():
                if fit["k"] is not None:
                    row["draws"][side].append(fit["k"])
    return {"daily_or_base": observed, "scales": scales, "comparison_note": note}
