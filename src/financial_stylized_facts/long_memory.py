"""Lo modified R/S on absolute returns; a conditional short-memory diagnostic.

Never infer a Hurst exponent, a power law, or long memory from rejection alone.
See docs/internal/long-memory.md for assumptions, references and finite-q limits.
"""
from math import pi, sqrt

import numpy as np

from .conditional import continuous_segments


def bridge_range_tails(value):
    """CDF and survival of the range of a standard Brownian bridge.

    Equivalent theta-series forms avoid cancellation in the lower tail.
    These are limiting probabilities, not a finite-sample exact distribution.
    """
    if not np.isfinite(value) or value < 0:
        raise ValueError("bridge range must be finite and nonnegative")
    if value == 0:
        return 0., 1.
    k = np.arange(1., 65.)
    if value < 1:
        if value < .01:
            return 0., 1.  # Below floating-point range, handled explicitly by caller.
        terms = k*k*np.exp(-pi*pi*k*k/(2*value*value))
        cdf = float(sqrt(2*pi)*pi*pi/value**3*np.sum(terms))
        return cdf, 1-cdf
    if value > 20:
        return 1., 0.
    z = k*k*value*value
    sf = float(2*np.sum((4*z-1)*np.exp(-2*z)))
    return 1-sf, sf


def modified_rs(values, bandwidth):
    """V = range(cumulative centered values) / sqrt(n * Bartlett LRV).

    Accepts one complete finite segment. Caller chooses |r| and sample gates.
    q=0 is an iid reference, not a short-dependence adjustment.
    """
    x = np.asarray(values, dtype=float)
    if x.ndim != 1 or len(x)<2 or not np.isfinite(x).all():
        raise ValueError("modified R/S requires a complete finite segment")
    if isinstance(bandwidth, bool) or not isinstance(bandwidth, (int, np.integer)) or not 0 <= bandwidth < len(x):
        raise ValueError("bandwidth must be an integer from 0 to n-1")
    result = {"status":"zero_variance", "reason":"窗口内波动没有足够变化",
              "n":len(x), "bandwidth":int(bandwidth), "statistic":None,
              "asymptotic_p":None, "p_is_numerical_upper_bound":False,
              "position":"unavailable"}
    scale = float(np.max(np.abs(x))) or 1.
    y = x/scale
    y -= y.mean()
    gamma0 = float(y@y/len(y))
    if gamma0 <= (64*np.finfo(float).eps)**2:
        return result
    long_variance = gamma0 + 2*sum((1-j/(bandwidth+1))*float(y[j:]@y[:-j]/len(y))
                                  for j in range(1,bandwidth+1))
    if long_variance <= 64*np.finfo(float).eps*gamma0:
        result.update(status="invalid_long_run_variance", reason="长期方差估计过小，统计量不稳定")
        return result
    cumulative = np.r_[0.,np.cumsum(y)]
    # Force the theoretical zero endpoint; no artificial round-off range.
    cumulative[-1] = 0.
    statistic = float(np.ptp(cumulative)/sqrt(len(y)*long_variance))
    lower, upper = bridge_range_tails(statistic)
    raw_p = min(1.,2*min(lower,upper))
    result.update(status="computed", reason=None, statistic=statistic,
                  asymptotic_p=max(1e-300,raw_p), p_is_numerical_upper_bound=raw_p<1e-300,
                  position="below" if lower<.025 else "above" if upper<.025 else "inside")
    return result


def long_memory_diagnostics(sampled, config):
    """Every contiguous segment, each whole/half/quarter window; no data selection."""
    result = {"method":"lo_modified_rescaled_range", "proxy":"absolute_return",
              "status":"insufficient_data", "reason":"连续窗口太短，不能使用预设的检验口径",
              "rows":[], "planned_windows":0, "planned_family_size":0,
              "adjustment":"bonferroni_all_positive_q_windows_within_path",
              "alpha":.05, "bandwidths":list(config.long_memory_bandwidths),
              "partitions":[1,2,4], "unadjusted_reference_95":[.809,1.862],
              "verified_long_memory":False,
              "scope":"短期依赖零假设的渐近对照；q=0 仅作独立序列参照，拒绝不等于证实长记忆"}
    if config.long_memory == "off":
        result.update(status="disabled", reason="配置关闭修正 R/S 对照")
        return result
    segments = list(continuous_segments(sampled))
    window_count = sum(min(parts,len(g)) for _,g in segments for parts in [1,2,4])
    family_size = window_count*sum(q>0 for q in config.long_memory_bandwidths)
    work = sum(len(g) for _,g in segments)*3*sum(q+1 for q in config.long_memory_bandwidths)
    result.update(planned_windows=window_count, planned_family_size=family_size, estimated_work=work)
    if window_count>config.long_memory_max_windows or work>config.long_memory_max_work:
        result.update(status="budget_exceeded", reason="窗口数或预计工作量超过上限，整项跳过，不挑选较长或更显著的片段")
        return result
    for segment,(session,g) in enumerate(segments,1):
        for parts in [1,2,4]:
            # No empty windows; tiny segments remain explicit insufficient rows.
            for block,positions in enumerate(np.array_split(np.arange(len(g)),min(parts,len(g))),1):
                window = g.iloc[positions]
                for q in config.long_memory_bandwidths:
                    required = max(config.long_memory_min_points,20*(q+1))
                    row = {"segment":segment,"session_id":session,"partition":parts,"window":block,
                           "start":str(window.timestamp.iloc[0]),"end":str(window.timestamp.iloc[-1]),
                           "n":len(window),"bandwidth":q,"required_n":required,
                           "reference_only":q==0,"statistic":None,"asymptotic_p":None,
                           "p_is_numerical_upper_bound":False,"family_adjusted_p":None,
                           "reject_short_memory_family":None,"position":"unavailable",
                           "status":"insufficient_data","reason":f"该窗口需要至少 {required} 条连续收益"}
                    if len(window)>=required:
                        row.update(modified_rs(np.abs(window.log_return.to_numpy(dtype=float)),q))
                        if q>0 and row["asymptotic_p"] is not None:
                            row["family_adjusted_p"] = min(1.,row["asymptotic_p"]*family_size)
                            row["reject_short_memory_family"] = row["family_adjusted_p"]<.05
                    result["rows"].append(row)
    formal = [r for r in result["rows"] if r["status"]=="computed" and not r["reference_only"]]
    result["computed_tests"] = len(formal)
    result["family_rejections"] = sum(r["reject_short_memory_family"] for r in formal)
    if formal:
        result.update(status="computed",reason=None)
    elif any(r["status"]=="computed" for r in result["rows"]):
        result.update(status="reference_only",reason="仅 q=0 的独立序列参照可计算，不能用于排除短期依赖")
    elif result["rows"] and all(r["status"]=="zero_variance" for r in result["rows"]):
        result.update(status="zero_variance",reason="全部窗口的波动均为常数")
    return result
