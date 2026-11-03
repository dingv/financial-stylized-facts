"""Deterministic, traceable observations for people, not an automatic pass/fail judge."""
import numpy as np
import pandas as pd


def number(value):
    return "不可计算" if value is None else f"{value:.4g}"


def lag_label(config, lag=1, factor=1):
    count = lag * factor
    if config.sampling == "observations":
        units = {"trading-day": "交易日", "available-price-observation": "可用报价", "source-date-slot": "日频观测"}
        return f"{count} 个{units.get(config.observation_unit, '观测（'+str(config.observation_unit)+'）')}"
    seconds = pd.Timedelta(config.frequency).total_seconds() * count
    for divisor, unit in [(86400, "天"), (3600, "小时"), (60, "分钟")]:
        if seconds >= divisor and seconds % divisor == 0:
            return f"{seconds/divisor:g} {unit}"
    return f"{seconds:g} 秒"


def at_lag(estimate, lag):
    """Never substitute a more favourable or merely available lag."""
    if lag not in estimate.get("lags", []):
        return None
    return estimate["values"][estimate["lags"].index(lag)]


def human_timestamp(value, config):
    stamp = pd.Timestamp(value)
    if config.sampling == "observations" and config.observation_unit in {"trading-day", "available-price-observation", "source-date-slot"}:
        return str(stamp.date())
    return str(stamp).replace("+00:00", " UTC")


def extreme_concentration(sampled):
    """One observation's share of the fourth central moment, not a causal attribution.

    The maximizing row is deterministic (first at a tie). Scaling avoids overflow;
    no observation is removed and kurtosis is not recomputed on a cleaner sample.
    """
    values = sampled["log_return"].to_numpy(float)
    positions = np.flatnonzero(np.isfinite(values))
    result = {"status": "not_computable", "fourth_moment_share": None, "timestamp": None,
              "log_return": None, "simple_return_percent": None,
              "definition": "max((r-mean(r))**4) / sum((r-mean(r))**4)"}
    if len(positions) < 4:
        return result
    x = values[positions]
    y = x / (float(np.max(np.abs(x))) or 1.)
    deviations = y-y.mean()
    scale = float(np.max(np.abs(deviations)))
    if scale == 0:
        return result
    weights = (deviations/scale)**4
    winner = int(np.argmax(weights))
    r = float(x[winner])
    pct = float(np.expm1(r)*100) if r < np.log(np.finfo(float).max/100) else None
    result.update(status="computed", fourth_moment_share=float(weights[winner]/weights.sum()),
                  timestamp=str(sampled.iloc[positions[winner]]["timestamp"]), log_return=r, simple_return_percent=pct)
    return result


def summarize(group, config, sampled):
    """All 11 fixed questions; evidence links name the source metrics in results.json."""
    facts = {}

    def add(fact_id, status, text, limitation, references):
        facts[str(fact_id)] = {"fact_id": fact_id, "status": status, "text": text,
                               "limitation": limitation, "references": references}

    d = group["distribution"]
    k = d["excess_kurtosis"]
    concentration = extreme_concentration(sampled)
    if k is None:
        text = f"本路径有 {d['n']} 条有效收益；峰度不可计算：{d['reason']}。"
    else:
        relation = "高于" if k > 0 else "低于" if k < 0 else "等于"
        text = f"本路径的修正超额峰度为 {number(k)}，{relation}高斯分布的 0 基准。"
        tail = d["tail_counts"]["3"]
        text += f" 偏离均值超过 3 个标准差的收益有 {tail['count']} 条（{number(tail['probability']*100)}%）。"
        if concentration["status"] == "computed" and concentration["fourth_moment_share"] >= .5:
            label = human_timestamp(concentration["timestamp"], config)
            text += (f" 峰度对 {label} 的一次变化特别敏感："
                     f"用于计算峰度的四次方偏差总量中，{number(concentration['fourth_moment_share']*100)}% 来自这一条。")
    add(2, d["status"], text, "峰度与尾部计数是样本描述；不能单凭正峰度证明稳定远尾或幂律。", ["distribution", "findings.extreme_concentration"])

    acfs = group["acf"]
    r, a, s = [at_lag(acfs[name], 1) for name in ["return", "absolute_return", "squared_return"]]
    distance = lag_label(config)
    add(1, "computed" if r is not None else "not_computable",
        f"间隔 {distance}的收益相关为 {number(r)}。" if r is not None else f"间隔 {distance}的收益相关不可计算，可能缺少配对或收益没有变化。",
        "这是固定 lag 1 的点估计；既不证明独立，也不代替整个滞后范围的检验。", ["acf.return"])
    add(6, "computed" if a is not None and s is not None else "not_computable",
        f"同样间隔 {distance}，绝对收益相关为 {number(a)}，平方收益相关为 {number(s)}。",
        "正值可作为波动持续的描述线索；不自动称为显著聚集，固定日内规律也可能贡献相关。", ["acf.absolute_return", "acf.squared_return"])

    asym = group["asymmetry"]
    skew = asym["skewness"]
    text = f"修正偏度为 {number(skew)}。" if skew is not None else f"偏度不可计算：{asym['reason']}。"
    if asym["tails"]:
        tail = next(t for t in asym["tails"] if t["sigma"] == 3)
        text += f" 均值两侧超过 3 个标准差的变化分别有 {tail['left_count']} 条（左侧）、{tail['right_count']} 条（右侧）。"
    add(3, asym["status"], text, "左右尾围绕样本均值比较；不是上涨概率。首达时间另比较固定阈值和观察窗口，不把两种问题混同。", ["asymmetry"])

    scales = group["aggregation"]["scales"]
    first, last = scales[0], scales[-1]
    text = (f"从 {lag_label(config, factor=first['factor'])} 拉长到 {lag_label(config, factor=last['factor'])}，"
            f"超额峰度由 {number(first['excess_kurtosis'])} 变为 {number(last['excess_kurtosis'])}；"
            f"有效收益数由 {first['n']} 降至 {last['n']}。")
    if len(scales) == 1:
        text = "本次只设置一个聚合尺度，无法比较拉长间隔后的变化。"
    add(4, "computed" if len(scales) > 1 and last["excess_kurtosis"] is not None else "not_computable", text,
        "固定比较配置中的首尾尺度，不选择最接近高斯的一点；样本减少及分组起点都可能影响结果。", ["aggregation.scales"])

    intermittent = group["intermittency"]
    if intermittent["exceedance_count"] is not None:
        episodes = intermittent["episodes"]
        text = (f"超过设定 {config.burst_threshold:g}σ 阈值的收益有 {intermittent['exceedance_count']} 条，"
                f"形成 {episodes['observed_count']} 个连续片段；完整 RMS 窗口有 {intermittent['rms_valid_windows']} 个。")
    else:
        text = f"标准化的大幅变化统计不可计算：{intermittent['reason']}。"
    add(5, intermittent["status"], text, "这里记录观察到的片段，边界可能截断；RMS 也会受到持续漂移的影响。", ["intermittency"])

    leverage = group["leverage"]
    ls, la = at_lag(leverage["squared"], 1), at_lag(leverage["absolute"], 1)
    add(9, "computed" if ls is not None and la is not None else "not_computable",
        f"当前收益与 {distance} 后平方收益的相关为 {number(ls)}，与之后绝对收益的相关为 {number(la)}。",
        "负值表示较低收益与较大后续波动相伴；相关不是因果，外汇倒数报价还会改变收益符号。", ["leverage"])

    persistence = group["volatility_persistence"]
    endpoint = config.volatility_max_lag
    last_acf = at_lag(persistence["full"], endpoint)
    text = f"在设定的 {lag_label(config, endpoint)} 滞后处，绝对收益相关为 {number(last_acf)}。"
    if last_acf is None:
        text += " 该终点不具备足够有效配对或序列方差；没有改用更短的滞后来代替。"
    memory = persistence["long_memory_test"]
    if memory["status"] == "computed":
        text += (f" 修正 R/S 的 {memory['computed_tests']} 个可计算窗口/带宽组合中，"
                 f"{memory['family_rejections']} 个在单路径多重比较修正后拒绝短期依赖零假设。")
    else:
        text += f" 修正 R/S 对照：{memory['reason']}。"
    add(8, "computed" if last_acf is not None else "not_computable", text,
        "远端 ACF 或修正 R/S 拒绝都不能单独证明长记忆；结构变化、重尾和带宽不足也会影响结果。不拒绝也不代表没有长记忆。", ["volatility_persistence"])

    volume = group["volume_volatility"]
    if volume["status"] == "computed":
        v = volume["correlations"]["absolute"]
        text = f"{v['pair_count']} 个配对区间中，成交量与绝对收益的 Pearson 相关为 {number(v['pearson'])}，Spearman 相关为 {number(v['spearman'])}。"
    else:
        text = f"本次量价关系不可计算：{volume['reason']}。"
    add(10, volume["status"], text, "使用已声明的量单位；未自动去除日内规律，也不把相关解释为交易量导致波动。", ["volume_volatility"])

    timescale = group["timescale_asymmetry"]
    row = next((x for x in timescale["differences"] if x["lag"] == 1), None)
    if row and row["difference"] is not None:
        text = (f"两个粗区间相隔 {lag_label(config, factor=config.coarse_factor)} 时，"
                f"粗波动在前的相关为 {number(row['coarse_leads_fine'])}，细波动在前为 {number(row['fine_leads_coarse'])}，"
                f"后者减前者为 {number(row['difference'])}。")
        status = "computed"
    else:
        text, status = "相邻粗区间的双向比较不可计算，完整配对不足或波动没有变化。", "not_computable"
    add(11, status, text, "固定报告粗区间 lag 1，不选择差异最大的滞后；这里不是因果或预测能力检验。", ["timescale_asymmetry"])

    conditional = group["conditional_tails"]
    fitted = [x for x in conditional["segments"] if x["status"] == "computed"]
    evaluated = conditional["n_evaluated"]
    text = f"{len(fitted)} 个连续段拟合可用，{evaluated}/{conditional['total_valid_returns']} 条收益进入调整后的分布比较。"
    if not conditional["total_valid_returns"]:
        text = "没有有效收益，无法比较 GARCH 调整前后的分布。"
    if len(fitted) == 1:
        segment = fitted[0]
        text += (f" 在相同区间，原始超额峰度为 {number(segment['raw_distribution']['excess_kurtosis'])}，"
                 f"GARCH 残差为 {number(segment['residual_distribution']['excess_kurtosis'])}。")
    elif not fitted:
        text += f" 原因：{conditional['reason']}。"
    add(7, conditional["status"], text,
        "只比较同段同范围；拟合成功不等于模型充分，残差的峰度也可能升高。不同段不合并成一个结论。", ["conditional_tails"])

    quality = group["quality"]
    coverage = f"有效收益 {d['n']} 条；缺失价格 {quality['missing_prices']} 个，沿用价格 {quality['carried_prices']} 个。"
    coverage += (f" GARCH 残差比较覆盖 {evaluated}/{conditional['total_valid_returns']} 条收益。" if conditional['total_valid_returns'] else " 没有有效收益可用于 GARCH 比较。")
    overview = [facts["2"]["text"], facts["1"]["text"]+" "+facts["6"]["text"], coverage]
    return {"method": "fixed_rules_from_current_path_metrics", "automatic_pass_fail": False,
            "overview": overview, "by_fact": dict(sorted(facts.items(), key=lambda item: int(item[0]))), "extreme_concentration": concentration,
            "display_rules": {"acf_and_leverage_lag": 1, "coarse_comparison_lag": 1,
                              "persistence_lag": endpoint, "extreme_share_notice_threshold": .5,
                              "extreme_threshold_is_statistical_test": False}}
