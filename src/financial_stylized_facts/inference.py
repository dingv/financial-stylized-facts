"""Delta-method + Bartlett/Newey-West HAC for the actual reported estimators.

Influence contributions keep original observation slots and session edges.
This is short-memory asymptotic inference, not a long-memory test. Missingness
must be non-informative; separate sessions are treated as independent blocks.
"""
import numpy as np
from scipy.stats import norm

from .diagnostics import _arrays
from .activity import coarse_fine_blocks


def _scaled(segments):
    arrays = _arrays(segments)
    scale = max((float(np.max(abs(a[np.isfinite(a)]))) for a in arrays if np.isfinite(a).any()), default=1.) or 1.
    return [a/scale for a in arrays]


def acf_influence(segments, lag):
    """Derivative of the global-mean fixed-denominator ACF w.r.t. row weights.

    Contributions are already divided by the full denominator (order 1/N).
    Mean estimation is included, also when missing/edge pairs have unequal means.
    """
    if isinstance(lag,bool) or not isinstance(lag,(int,np.integer)) or lag<1:
        raise ValueError("ACF lag 必须为正整数")
    arrays = _scaled(segments)
    eligible_pairs = sum(int((np.isfinite(a[:-lag])&np.isfinite(a[lag:])).sum()) for a in arrays if len(a)>lag)
    n = sum(int(np.isfinite(a).sum()) for a in arrays)
    if n < 2:
        return None, [], eligible_pairs
    mu = sum(float(np.nansum(a)) for a in arrays)/n
    centered = [np.where(np.isfinite(a), a-mu, 0.) for a in arrays]
    denominator = sum(float(np.dot(a,a)) for a in centered)
    if denominator == 0:
        return None, [], eligible_pairs
    products, pair_sum, pairs = [], 0., 0
    for a, z in zip(arrays, centered):
        product = np.zeros(len(a))
        if len(a)>lag:
            valid = np.isfinite(a[:-lag]) & np.isfinite(a[lag:])
            product[:-lag] = np.where(valid, z[:-lag]*z[lag:], 0.)
            pair_sum += float(np.sum((z[:-lag]+z[lag:])[valid]))
            pairs += int(valid.sum())
        products.append(product)
    estimate = float(np.clip(sum(float(p.sum()) for p in products)/denominator,-1.,1.))
    scores = [(p-estimate*z*z-pair_sum/n*z)/denominator for p,z in zip(products,centered)]
    return float(estimate), scores, pairs


def pearson_influence(x_segments, y_segments, lag):
    """corr(x[t], y[t+lag]); assign each pair's contribution to original t."""
    if isinstance(lag,bool) or not isinstance(lag,(int,np.integer)):
        raise ValueError("Pearson lag 必须为整数")
    xs, ys = _scaled(x_segments), _scaled(y_segments)
    if len(xs)!=len(ys) or any(len(x)!=len(y) for x,y in zip(xs,ys)):
        raise ValueError("配对序列的 session 和长度必须一致")
    paired = []
    for x,y in zip(xs,ys):
        indices = np.arange(max(0,-lag), min(len(x),len(x)-lag))
        valid = np.isfinite(x[indices]) & np.isfinite(y[indices+lag])
        indices = indices[valid]
        paired.append((indices, x[indices], y[indices+lag]))
    n = sum(len(p[0]) for p in paired)
    if n < 2:
        return None, [], n
    mx = sum(float(x.sum()) for _,x,_ in paired)/n
    my = sum(float(y.sum()) for _,_,y in paired)/n
    dxs, dys = [x-mx for _,x,_ in paired], [y-my for _,_,y in paired]
    vx, vy = sum(float(x@x) for x in dxs), sum(float(y@y) for y in dys)
    if min(vx,vy) <= n*np.finfo(float).eps**2:
        return None, [], n
    denom = np.sqrt(vx*vy)
    estimate = float(np.clip(sum(float(x@y) for x,y in zip(dxs,dys))/denom,-1.,1.))
    scores = []
    for original,(indices,_,_),dx,dy in zip(xs,paired,dxs,dys):
        a = np.zeros(len(original))
        a[indices] = dx*dy/denom-estimate*.5*(dx*dx/vx+dy*dy/vy)
        scores.append(a)
    return float(estimate), scores, n


def hac_variances(scores, bandwidths):
    """Scalar Bartlett sandwich, no cross-session terms and no degrees correction."""
    maximum = max(bandwidths)
    gamma = np.zeros(maximum+1)
    for s in scores:
        if not np.isfinite(s).all():
            raise ValueError("HAC influence 必须有限；缺失槽应为零贡献")
        gamma[0] += float(s@s)
        for h in range(1, min(maximum,len(s)-1)+1):
            gamma[h] += float(s[h:]@s[:-h])
    variances = {}
    for bandwidth in bandwidths:
        weights = 1-np.arange(1,bandwidth+1)/(bandwidth+1)
        value = gamma[0]+2*float(weights@gamma[1:bandwidth+1])
        tolerance = 128*np.finfo(float).eps*gamma[0]*(bandwidth+1)
        if value < -tolerance:
            raise ArithmeticError("Bartlett HAC 出现非数值误差范围的负方差")
        variances[bandwidth] = max(0., value)
    return variances


def interval_rows(estimate, scores, pairs, *, family, proxy, lag, config, bounds=(-1.,1.)):
    rows = []
    variances = hac_variances(scores, config.hac_bandwidths) if estimate is not None else {}
    for bandwidth in config.hac_bandwidths:
        row = {"family":family,"proxy":proxy,"lag":lag,"bandwidth":bandwidth,"estimate":estimate,
               "pair_count":pairs,"status":"not_computable","reason":None,"standard_error":None,
               "lower":None,"upper":None,"familywise_lower":None,"familywise_upper":None}
        if estimate is None:
            row["reason"] = "统计量不可计算：配对不足或零方差"
        elif bandwidth < abs(lag):
            row["reason"] = "带宽小于所评估 lag，未覆盖由共享观测引入的依赖范围"
        elif pairs < max(config.min_pairs,config.inference_min_pairs,20*(bandwidth+1)):
            row["reason"] = "配对数不足推断门槛，或不足二十倍带宽窗口"
        elif abs(estimate)>=bounds[1]-1e-12:
            row["reason"] = "估计接近参数边界，常规渐近区间不适用"
        elif variances[bandwidth] <= 0:
            row["reason"] = "线性化方差为零，不能生成有信息的区间"
        else:
            se = float(np.sqrt(variances[bandwidth]))
            row.update(status="computed", standard_error=se,
                       lower=float(max(bounds[0],estimate-norm.ppf(.975)*se)),
                       upper=float(min(bounds[1],estimate+norm.ppf(.975)*se)))
        rows.append(row)
    return rows


def dependence_uncertainty(sampled, config):
    """Bounded inference for ACF, signed leverage and coarse/fine differences."""
    result = {"status":"disabled","reason":"本次关闭时间依赖指标的近似区间",
              "method":"delta_bartlett_hac","confidence_level":.95,"small_sample_correction":False,
              "bandwidths":list(config.hac_bandwidths),"plot_bandwidth":config.hac_bandwidths[0],
              "max_lag":min(config.inference_max_lag,config.max_lag),"rows":[],"family_size":0,
              "familywise_method":"Bonferroni normal intervals across all requested rows and bandwidths within one asset/path",
              "assumptions":"共同稳定矩、短记忆弱依赖和足够高阶矩；缺失非信息性，session 之间不估计协方差；不是长记忆检验",
              "limitations":"平方收益相关尤其依赖高阶矩；状态变化、强远尾、长记忆和跨 session 依赖会使覆盖率失效。多资产未联合校正。"}
    if config.dependence_inference == "off":
        return result
    arrays = [g.log_return.to_numpy(float) for _,g in sampled.groupby("session_id",sort=False)]
    nslots = sum(map(len,arrays))
    limit = result["max_lag"]
    work = nslots*limit*(7+1/config.coarse_factor)*(max(config.hac_bandwidths)+1)
    result["estimated_work"] = int(np.ceil(work))
    if work>config.inference_max_work:
        result.update(status="resource_limit",reason="HAC 工作量超过上限；未截短样本或删减配置")
        return result
    # Rescaling once before powers avoids overflow without changing correlations.
    arrays = _scaled(arrays)
    rows = []
    for proxy,transform in [("return",lambda x:x),("absolute_return",np.abs),("squared_return",np.square)]:
        series = [transform(a) for a in arrays]
        for lag in range(1,limit+1):
            estimate,scores,pairs = acf_influence(series,lag)
            rows.extend(interval_rows(estimate,scores,pairs,family="acf",proxy=proxy,lag=lag,config=config))
    for proxy,transform in [("absolute",np.abs),("squared",np.square)]:
        series = [transform(a) for a in arrays]
        for lag in list(range(-limit,0))+list(range(1,limit+1)):
            estimate,scores,pairs = pearson_influence(arrays,series,lag)
            rows.extend(interval_rows(estimate,scores,pairs,family="leverage",proxy=proxy,lag=lag,config=config))
    blocks,_ = coarse_fine_blocks([a[1:] for a in arrays],config.coarse_factor)
    coarse, fine = [c for c,f in blocks],[f for c,f in blocks]
    for lag in range(1,limit+1):
        forward,sf,nf = pearson_influence(fine,coarse,lag)
        reverse,sr,nr = pearson_influence(fine,coarse,-lag)
        estimate = forward-reverse if forward is not None and reverse is not None else None
        scores = [f-r for f,r in zip(sf,sr)] if estimate is not None else []
        rows.extend(interval_rows(estimate,scores,min(nf,nr),family="timescale",proxy="difference",lag=lag,config=config,bounds=(-2.,2.)))
    m = len(rows)
    critical = float(norm.ppf(1-.05/(2*m))) if m else None
    for row in rows:
        if row["status"] == "computed":
            bound = 2. if row["family"] == "timescale" else 1.
            margin = critical*row["standard_error"]
            row.update(familywise_lower=float(max(-bound,row["estimate"]-margin)),
                       familywise_upper=float(min(bound,row["estimate"]+margin)))
    available = sum(r["status"]=="computed" for r in rows)
    result.update(rows=rows,family_size=m,familywise_critical_value=critical,
                  status="computed" if available==len(rows) and rows else "partially_computed" if available else "not_computable",
                  reason=None if available else "没有满足样本、带宽和方差条件的区间；查看逐项原因")
    return result
