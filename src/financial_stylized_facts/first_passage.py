"""Symmetric log-return first passage with explicit finite-horizon censoring.

No interpolation, detrending, independent-start inference or censoring model.
Main CDF uses one common, fully observed H-step cohort for both directions.
All-start bounds retain incomplete follow-up; they are not confidence intervals.
"""
import numpy as np


def price_segments(sampled):
    segments = []
    for _, frame in sampled.groupby("session_id",sort=False):
        prices = frame.price.to_numpy(float)
        good = np.isfinite(prices)
        edges = np.flatnonzero(np.diff(np.r_[False,good,False])).reshape(-1,2)
        for start,end in edges:
            segments.append((np.log(prices[start:end]), frame.timestamp.iloc[start:end].tolist()))
    return segments


def path_extrema(segments):
    """Largest observed log drawdown/up within an uninterrupted session segment."""
    result = {"status":"not_computable","reason":"没有至少两个连续价格的片段",
              "drawdown":None,"drawup":None,"segment_count":len(segments)}
    for number,(logs,times) in enumerate(segments,1):
        if len(logs)<2:
            continue
        for direction, changes, extreme in [
            ("drawdown",np.maximum.accumulate(logs)-logs,np.argmax),
            ("drawup",logs-np.minimum.accumulate(logs),np.argmin)]:
            end = int(np.argmax(changes))
            start = int(extreme(logs[:end+1]))
            magnitude = float(changes[end])
            old = result[direction]
            if old is None or magnitude>old["log_magnitude"]:
                pct = float(-np.expm1(-magnitude)*100) if direction=="drawdown" else float(np.expm1(magnitude)*100) if magnitude<np.log(np.finfo(float).max/100) else None
                result[direction] = {"log_magnitude":magnitude,"simple_percent":pct,"segment":number,
                                     "simple_percent_reason":None if pct is not None else "百分比超出有限浮点数表示范围；对数幅度仍可用",
                                     "start":str(times[start]),"end":str(times[end]),"steps":end-start}
        result.update(status="computed",reason=None)
    return result


def first_hit_steps(logs, threshold, horizon):
    """Each start separately seeks both barriers, not a competing first exit."""
    n = len(logs)
    followup = np.minimum(horizon,np.arange(n-1,-1,-1))
    up, down = np.zeros(n,dtype=int), np.zeros(n,dtype=int)
    for h in range(1,min(horizon,n-1)+1):
        move = logs[h:]-logs[:-h]
        up[:n-h][(up[:n-h]==0)&(move>=threshold)] = h
        down[:n-h][(down[:n-h]==0)&(move<=-threshold)] = h
    return up,down,followup


def _direction_summary(hits, followups, horizon, min_starts):
    n = sum(map(len,hits))
    full_n = sum(int(np.sum(f==horizon)) for f in followups)
    all_hist = np.zeros(horizon+1,dtype=int)
    full_hist = np.zeros(horizon+1,dtype=int)
    censored_hist = np.zeros(horizon+1,dtype=int)
    for tau,followup in zip(hits,followups):
        all_hist += np.bincount(tau,minlength=horizon+1)
        full_hist += np.bincount(tau[followup==horizon],minlength=horizon+1)
        censored_hist += np.bincount(followup[tau==0],minlength=horizon+1)
    all_cumulative = np.cumsum(all_hist[1:])
    full_cumulative = np.cumsum(full_hist[1:])
    # At h, a censor at h still tells us the threshold was not reached by h.
    unknown = np.cumsum(censored_hist[:-1])
    rows = []
    for h in range(1,horizon+1):
        rows.append({"horizon":h,"full_hits":int(full_cumulative[h-1]),
                     "full_cdf":float(full_cumulative[h-1]/full_n) if full_n>=min_starts else None,
                     "observed_hits":int(all_cumulative[h-1]),"early_censored":int(unknown[h-1]),
                     "all_start_lower_bound":float(all_cumulative[h-1]/n),
                     "all_start_upper_bound":float((all_cumulative[h-1]+unknown[h-1])/n)})
    median = next((r["horizon"] for r in rows if r["full_cdf"] is not None and r["full_cdf"]>=.5),None)
    return {"all_starts":n,"full_horizon_starts":full_n,"full_horizon_hits":int(full_cumulative[-1]),
            "full_horizon_nonhits":int(full_hist[0]),"observed_hits":int(all_cumulative[-1]),
            "early_censored":int(unknown[-1]),"horizon_censored":int(censored_hist[-1]),
            "full_hit_probability":rows[-1]["full_cdf"],"full_median_steps":median,
            "median_reason":None if median is not None else "完整窗口起点不足" if full_n<min_starts else "窗口内累计达到比例不足一半，不能估计中位首达时间",
            "curve":rows}


def first_passage_diagnostics(sampled, config):
    result = {"status":"disabled","reason":"本次关闭首达时间分析","horizon":config.first_passage_horizon,
              "threshold_unit":config.first_passage_unit,"return_std":None,"thresholds":[],
              "main_cohort":"same starts with uninterrupted H-step follow-up in one session",
              "detrending":"none","uncertainty":"not_estimated; overlapping starts are dependent",
              "censor_bounds":"finite observed-start bounds, not confidence intervals or estimated population probabilities"}
    if config.first_passage=="off":
        return result
    segments = price_segments(sampled)
    result["path_extrema"] = path_extrema(segments)
    logs = [s for s,_ in segments]
    n = sum(map(len,logs))
    full_n = sum(max(0,len(a)-config.first_passage_horizon) for a in logs)
    result.update(all_starts=n,full_horizon_starts=full_n,segment_count=len(logs),
                  zero_followup_starts=len(logs),early_window_starts=n-full_n)
    if not n:
        result.update(status="not_computable",reason="没有可用价格")
        return result
    returns = sampled.log_return.to_numpy(float)
    finite = returns[np.isfinite(returns)]
    std = float(np.std(finite)) if len(finite)>=2 else None
    result["return_std"] = std
    if config.first_passage_unit=="sigma" and (std is None or std==0):
        result.update(status="not_computable",reason="收益标准差不可计算或为零，无法定义 sigma 阈值；绝对对数阈值可另行显式配置")
        return result
    work = 2*n*config.first_passage_horizon*len(config.first_passage_thresholds)
    result["estimated_work"] = work
    if work>config.first_passage_max_work:
        result.update(status="resource_limit",reason="首达时间工作量超过上限；没有抽取起点或缩短窗口")
        return result
    for value in config.first_passage_thresholds:
        threshold = float(value*std if config.first_passage_unit=="sigma" else value)
        if not np.isfinite(threshold) or threshold<=0:
            raise ValueError("首达时间实际对数阈值超出有限正数范围")
        estimates = [first_hit_steps(a,threshold,config.first_passage_horizon) for a in logs]
        followups = [row[2] for row in estimates]
        row = {"configured_threshold":float(value),"log_threshold":threshold}
        for index,direction in enumerate(["up","down"]):
            row[direction] = _direction_summary([e[index] for e in estimates],followups,
                                               config.first_passage_horizon,config.first_passage_min_starts)
        result["thresholds"].append(row)
    result.update(status="computed" if full_n>=config.first_passage_min_starts else "partially_computed",
                  reason=None if full_n>=config.first_passage_min_starts else "完整窗口起点不足，主曲线留空；保留所有起点的命中和截断计数")
    return result
