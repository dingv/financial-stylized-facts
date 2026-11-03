"""Volume/volatility lead-lag correlations on original slots within sessions."""
import numpy as np
from scipy.stats import norm

from .inference import _scaled, pearson_influence, interval_rows


def volume_lag_diagnostics(sampled, config):
    """corr(V[t], |r[t+k]| or r[t+k]**2); positive k = volume earlier.

    A separate Bonferroni family keeps existing dependence results unchanged.
    All requested proxies, signed lags (including zero), and bandwidths count.
    """
    limit = min(config.max_lag, config.inference_max_lag)
    result = {"status": "not_applicable", "reason": "未提供区间成交量", "rows": [],
              "definition": "corr(volume[t], volatility[t+k]); positive k = volume earlier",
              "estimator": "lag_specific_pairwise_pearson", "unit": config.volume_unit,
              "requested_max_lag": config.max_lag,
              "inference": {"status": "disabled", "reason": "本次关闭量价滞后的近似区间",
                  "method": "delta_bartlett_hac", "max_lag": limit, "rows": [],
                  "plot_bandwidth": config.hac_bandwidths[0], "confidence_level": .95,
                  "family_size": 2*(2*limit+1)*len(config.hac_bandwidths),
                  "familywise_method": "Bonferroni across both proxies, all requested signed lags including zero, and bandwidths within this asset/path",
                  "assumptions": "共同稳定矩、短记忆弱依赖和足够高阶矩；缺失非信息性；session 之间不估计协方差"}}
    if config.volume_kind == "none":
        result["inference"].update(status="not_applicable", reason=result["reason"])
        return result
    groups = list(sampled.groupby("session_id", sort=False))
    xs = [g.volume.to_numpy(float) for _, g in groups]
    returns = _scaled([g.log_return.to_numpy(float) for _, g in groups])
    slots = sum(map(len, xs))
    point_work = slots*2*(2*config.max_lag+1)
    inference_work = slots*2*(2*limit+1)*(max(config.hac_bandwidths)+1)
    result["estimated_point_work"] = point_work
    result["inference"]["estimated_work"] = inference_work
    if point_work > config.inference_max_work:
        result.update(status="resource_limit", reason="量价滞后点估计工作量超过 inference_max_work；未缩短样本")
        result["inference"].update(status="resource_limit", reason=result["reason"])
        return result
    infer = config.dependence_inference != "off" and inference_work <= config.inference_max_work
    if config.dependence_inference != "off" and not infer:
        result["inference"].update(status="resource_limit", reason="量价滞后 HAC 工作量超过 inference_max_work；保留点估计")
    for proxy, transform in [("absolute", np.abs), ("squared", np.square)]:
        ys = [transform(r) for r in returns]
        for lag in range(-config.max_lag, config.max_lag+1):
            estimate, scores, pairs = pearson_influence(xs, ys, lag)
            status = "computed" if estimate is not None and pairs >= config.min_pairs else "insufficient_pairs" if pairs < config.min_pairs else "zero_variance"
            reason = None if status == "computed" else "有效配对不足" if status == "insufficient_pairs" else "配对序列零方差"
            result["rows"].append({"proxy": proxy, "lag": lag,
                "correlation": estimate if status == "computed" else None,
                "pair_count": pairs, "status": status, "reason": reason})
            if infer and abs(lag) <= limit:
                result["inference"]["rows"].extend(interval_rows(
                    estimate, scores, pairs, family="volume_lag", proxy=proxy, lag=lag, config=config))
    if infer:
        intervals = result["inference"]["rows"]
        critical = float(norm.ppf(1-.05/(2*result["inference"]["family_size"])))
        for row in intervals:
            if row["status"] == "computed":
                margin = critical*row["standard_error"]
                row.update(familywise_lower=max(-1., row["estimate"]-margin),
                           familywise_upper=min(1., row["estimate"]+margin))
        available = sum(r["status"] == "computed" for r in intervals)
        result["inference"].update(status="computed" if available == len(intervals) else "partially_computed" if available else "not_computable",
            reason=None if available else "没有满足样本、带宽和方差条件的区间", familywise_critical_value=critical)
    available = sum(r["status"] == "computed" for r in result["rows"])
    result.update(status="computed" if available == len(result["rows"]) else "partially_computed" if available else "not_computable",
                  reason=None if available else "所有滞后的配对不足或方差为零")
    return result


def volume_lag_evidence(result, config):
    """Two volatility proxies and every configured bandwidth must agree."""
    lookup = {(r["proxy"], r["lag"], r["bandwidth"]): r for r in result["inference"]["rows"]}
    positive, negative, incomplete = [], [], []
    limit = result["inference"]["max_lag"]
    for lag in range(-limit, limit+1):
        rows = [lookup.get((p, lag, b), {}) for p in ("absolute", "squared") for b in config.hac_bandwidths]
        if not all(r.get("status") == "computed" for r in rows):
            incomplete.append(lag)
        elif all(r["familywise_lower"] > 0 for r in rows):
            positive.append(lag)
        elif all(r["familywise_upper"] < 0 for r in rows):
            negative.append(lag)
    return {"positive_lags": positive, "negative_lags": negative, "incomplete_lags": incomplete,
            "positive_volume_earlier_lags": [k for k in positive if k > 0],
            "positive_volatility_earlier_lags": [k for k in positive if k < 0],
            "same_interval_positive": 0 in positive, "complete": not incomplete,
            "scope": "both volatility proxies and all bandwidths; own corrected family; association, not causation"}
