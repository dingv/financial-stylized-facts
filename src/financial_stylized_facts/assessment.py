"""Versioned evidence summaries built from existing estimates, not a market score.

No fitting, hypothesis selection, or data transformation happens here. Interval
claims require the same sign across every configured sensitivity setting.
"""
from math import erfc, sqrt

from .decay import persistence_evidence

from .findings import at_lag, lag_label, number

RULE_VERSION = "2"
NORMAL_TAIL_3 = erfc(3 / sqrt(2))
FACT_NAMES = ["收益线性相关较弱", "厚尾", "涨跌不对称", "聚合高斯化", "间歇性", "波动聚集",
              "条件厚尾", "波动相关缓慢衰减", "杠杆效应", "成交量与波动相关", "时间尺度不对称"]
LEVELS = {"asymptotic": "渐近检验与模型比较", "test": "模拟参照检验", "model": "衰减模型比较", "interval": "区间证据", "descriptive": "描述性结果", "unavailable": "未评估"}


def block_evidence(group, config, metric, reference=0.):
    """Missing/degenerate blocks cannot be silently dropped from sensitivity."""
    blocks = {b["block_length"]: b for b in group["uncertainty"]["blocks"]}
    rows = []
    for length in config.bootstrap_block_lengths:
        block = blocks.get(length, {})
        row = next((r for r in block.get("intervals", []) if r["metric"] == metric), {})
        rows.append({"block_length": length, **row})
    complete = bool(rows) and all(r.get("status") == "computed" and r.get("lower") is not None
                                  and r.get("upper") is not None for r in rows)
    return {"complete": complete, "positive": complete and all(r["lower"] > reference for r in rows),
            "negative": complete and all(r["upper"] < reference for r in rows),
            "reference": reference, "intervals": rows}


def lag_evidence(group, config, family, proxy):
    """Bonferroni intervals, positive lags, all predeclared HAC bandwidths."""
    maximum = min(config.inference_max_lag, config.max_lag)
    all_rows = group["dependence_uncertainty"]["rows"]
    results = []
    for lag in range(1, maximum + 1):
        rows = [r for r in all_rows if r["family"] == family and r["proxy"] == proxy and r["lag"] == lag]
        by_bandwidth = {r["bandwidth"]: r for r in rows}
        chosen = [by_bandwidth.get(b, {}) for b in config.hac_bandwidths]
        complete = bool(chosen) and all(r.get("status") == "computed" and r.get("familywise_lower") is not None
                                        and r.get("familywise_upper") is not None for r in chosen)
        positive = complete and all(r["familywise_lower"] > 0 for r in chosen)
        negative = complete and all(r["familywise_upper"] < 0 for r in chosen)
        any_exclusion = any(r.get("status") == "computed" and
                            (r.get("familywise_lower", 0) > 0 or r.get("familywise_upper", 0) < 0) for r in rows)
        results.append({"lag": lag, "complete": complete, "positive": positive, "negative": negative,
                        "sensitivity": any_exclusion and not (positive or negative)})
    return {"lags": results, "positive_lags": [r["lag"] for r in results if r["positive"]],
            "negative_lags": [r["lag"] for r in results if r["negative"]],
            "sensitive_lags": [r["lag"] for r in results if r["sensitivity"]],
            "complete": bool(results) and all(r["complete"] for r in results),
            "requested_lags": maximum, "bandwidths": list(config.hac_bandwidths)}


def metric(label, value, unit=""):
    return {"label": label, "value": value, "unit": unit}


def assess(group, config):
    """Return eleven independent records; statuses never mean pass/fail."""
    rows = {}
    def add(i, conclusion, label, summary, metrics=(), *, level="descriptive", evidence=None, notes=()):
        old = group["findings"]["by_fact"][str(i)]
        rows[str(i)] = {"fact_id": i, "name": FACT_NAMES[i-1], "rule_id": f"sf{i}.v{RULE_VERSION}",
                       "conclusion": conclusion, "label": label, "summary": summary,
                       "evidence_level": level, "evidence_label": LEVELS[level],
                       "metrics": list(metrics), "evidence": evidence or {}, "notes": list(notes),
                       "computation_status": old["status"], "references": old["references"]}
    def unavailable(i, reason, status="insufficient_data"):
        add(i, status, "不适用" if status == "not_applicable" else "未启用" if status == "disabled" else "无法评估",
            reason, level="unavailable")

    acf = group["acf"]
    r = at_lag(acf["return"], 1)
    ev = lag_evidence(group, config, "acf", "return")
    scope = f"lag 1–{ev['requested_lags']}（每步 {lag_label(config)}）"
    selected = sorted(ev["positive_lags"] + ev["negative_lags"])
    if r is None:
        unavailable(1, "收益没有变化或有效配对不足。")
    else:
        if selected:
            c, label, text, level = "correlation_detected", "检出线性相关", f"{scope} 中，lag {', '.join(map(str, selected))} 的相关在各带宽下均有区间支持。", "interval"
        elif ev["sensitive_lags"]:
            c, label, text, level = "mixed", "依赖带宽选择", f"{scope} 的相关结论随 HAC 带宽变化。", "interval"
        elif ev["complete"]:
            c, label, text, level = "not_detected", "未检出线性相关", f"{scope} 的校正区间均包含零；尚不能据此断言收益独立。", "interval"
        else:
            c, label, text, level = "descriptive", "仅有描述性结果", f"{scope} 的区间覆盖不足，保留收益 ACF 点估计。", "descriptive"
        add(1, c, label, text, [metric("收益 ACF(1)", r)], level=level, evidence=ev)

    d = group["distribution"]
    k, tail = d["excess_kurtosis"], d["tail_counts"].get("3", {}).get("probability")
    if k is None or tail is None:
        unavailable(2, d["reason"] or "尾部统计不可计算。")
    else:
        bk = block_evidence(group, config, "excess_kurtosis")
        bt = block_evidence(group, config, "tail_probability_3sigma", NORMAL_TAIL_3)
        point = k > 0 and tail > NORMAL_TAIL_3
        supported = point and bk["positive"] and bt["positive"]
        concentration = group["findings"]["extreme_concentration"]
        notes = []
        if (concentration.get("fourth_moment_share") or 0) >= .5:
            notes.append(f"单次变化贡献 {number(concentration['fourth_moment_share']*100)}% 的四次方偏差，峰度受该观测主导。")
        if supported:
            c, label, text = "supported", "厚尾指标有支持", "峰度高于零，3σ 尾概率高于高斯基准 0.270%；各块长的近似区间方向一致。"
        elif point:
            c, label, text = "indicative", "有厚尾迹象", "超额峰度和 3σ 尾概率均高于高斯基准；区间尚未给出一致支持。"
        elif k > 0 or tail > NORMAL_TAIL_3:
            c, label, text = "mixed", "尾部指标不一致", "峰度与 3σ 尾概率没有同时高于高斯基准。"
        else:
            c, label, text = "not_detected", "未见厚尾迹象", "本样本的超额峰度和 3σ 尾概率均未高于高斯基准。"
        add(2, c, label, text, [metric("超额峰度", k), metric("超过 3σ", 100*tail, "%"),
                               metric("尾部观测数", d["tail_counts"]["3"]["count"])],
            level="interval" if supported else "descriptive", evidence={"kurtosis": bk, "tail": bt}, notes=notes)

    asym = group["asymmetry"]
    skew = asym["skewness"]
    if skew is None:
        unavailable(3, asym["reason"] or "偏度不可计算。")
    else:
        e = block_evidence(group, config, "skewness")
        supported = e["positive"] or e["negative"]
        direction = "右偏" if skew > 0 else "左偏" if skew < 0 else "对称"
        text = f"收益分布{direction}；" + ("偏度的区间在各块长下均不含零。" if supported else "偏度区间未给出一致的不对称证据。")
        add(3, "supported" if supported else "descriptive", f"{direction}有区间支持" if supported else "不对称证据不足",
            text, [metric("偏度", skew)], level="interval" if supported else "descriptive", evidence=e)

    scales = group["aggregation"]["scales"]
    if len(scales) < 2 or any(s["excess_kurtosis"] is None or s["normal_quantile_rmse"] is None or s["n"] < 100 for s in scales):
        unavailable(4, "需要至少两个配置尺度，且每个尺度至少 100 条可计算收益。")
    else:
        first, last = scales[0], scales[-1]
        closer = abs(last["excess_kurtosis"]) < abs(first["excess_kurtosis"]) and last["normal_quantile_rmse"] < first["normal_quantile_rmse"]
        monotonic = all(abs(b["excess_kurtosis"]) <= abs(a["excess_kurtosis"]) and b["normal_quantile_rmse"] <= a["normal_quantile_rmse"] for a,b in zip(scales, scales[1:]))
        text = f"从 {lag_label(config, factor=first['factor'])} 到 {lag_label(config, factor=last['factor'])}，"
        text += "峰度与分位数距离都趋近高斯" if closer else "峰度与分位数距离没有共同趋近高斯"
        text += "；中间尺度存在反复。" if closer and not monotonic else "。"
        add(4, "indicative" if closer else "mixed", "有聚合高斯化迹象" if closer else "未见一致趋势", text,
            [metric("最短尺度超额峰度", first["excess_kurtosis"]), metric("最长尺度超额峰度", last["excess_kurtosis"])],
            evidence={"monotonic": monotonic, "scales": scales, "minimum_returns_per_scale": 100})

    it = group["intermittency"]
    fi = it.get('inference', {})
    tested = [r for r in fi.get('rows',[]) if r['status']=='computed']
    significant = [r['window'] for r in tested if r['reject']]
    if tested:
        supported = len(significant)>=2
        text = f"{len(significant)}/{len(fi['rows'])} 个预设窗口的极端事件计数比随机排列更集中（校正 p≤0.05）。"
        add(5, 'supported' if supported else 'indicative' if significant else 'not_detected',
            '极端波动集中出现' if supported else '局部集中迹象' if significant else '未检出超出随机排列的集中', text,
            [metric('显著窗口数',len(significant)),metric('极端事件数',fi['total_events']),
             metric('最小校正 p',min(r['family_adjusted_p'] for r in tested))],level='test',evidence=fi)
    else:
        reasons = list(dict.fromkeys(r['reason'] for r in fi.get('rows',[]) if r.get('reason')))
        add(5, 'insufficient_data', '间歇性检验不可用', '；'.join(reasons) or fi.get('reason') or '未运行极端事件置换检验。',
            [metric('完整 RMS 窗口',it['rms_valid_windows'])],level='unavailable',evidence=fi)

    a, s = at_lag(acf["absolute_return"], 1), at_lag(acf["squared_return"], 1)
    ea, es = [lag_evidence(group, config, "acf", p) for p in ("absolute_return", "squared_return")]
    common = sorted(set(ea["positive_lags"]) & set(es["positive_lags"]))
    sustained = any(x+1 in common for x in common)
    if a is None or s is None:
        unavailable(6, "绝对收益或平方收益的相关不可计算。")
    else:
        if sustained:
            c, label, text, level = "supported", "短期波动聚集有支持", f"两种波动指标在 lag {', '.join(map(str, common))} 均有正相关区间支持，包含连续两个滞后。", "interval"
        elif common:
            c, label, text, level = "indicative", "局部正相关", f"两种指标仅在 lag {', '.join(map(str, common))} 共同获得正相关区间支持。", "interval"
        else:
            c, label, text, level = "inconclusive", "聚集证据不足", "在所检滞后内，两种波动指标尚未给出共同且持续的正相关区间证据。", "descriptive"
        add(6, c, label, text, [metric("绝对收益 ACF(1)", a), metric("平方收益 ACF(1)", s)],
            level=level, evidence={"absolute": ea, "squared": es, "common_positive_lags": common, "minimum_consecutive_lags": 2})

    ct = group["conditional_tails"]
    fitted = [x for x in ct["segments"] if x["status"] == "computed"]
    if not fitted:
        unavailable(7, ct["reason"] or "没有可用 GARCH 残差。", "disabled" if ct["status"] == "disabled" else "insufficient_data")
    else:
        signs = []
        for segment in fitted:
            rd = segment["residual_distribution"]
            rk = rd.get("excess_kurtosis")
            rp = rd.get("tail_counts", {}).get("3", {}).get("probability")
            signs.append(None if rk is None or rp is None else rk > 0 and rp > NORMAL_TAIL_3)
        known = [s for s in signs if s is not None]
        missing = len(signs) - len(known)
        conclusion = "insufficient_data" if not known else "mixed" if missing else "indicative" if all(signs) else "mixed" if any(signs) else "not_detected"
        label = "残差尾部不可评估" if not known else "部分段无法评估" if missing else "残差仍有厚尾迹象" if all(signs) else "各段结果不同" if any(signs) else "残差未见共同厚尾迹象"
        text = f"{sum(known)}/{len(fitted)} 个可用拟合段的残差同时呈正超额峰度和偏高的 3σ 尾概率。"
        if missing:
            text += f" 其中 {missing} 段的尾部统计不可计算。"
        references=[x.get('reference_test',{}) for x in fitted]
        computed=[r for r in references if r.get('status')=='computed']
        supported=sum(r.get('tail_supported',False) for r in references)
        failed_adequacy=sum(r.get('adequacy_rejected',False) for r in computed)
        if computed:
            complete=len(computed)==len(ct['segments'])
            conclusion='supported' if complete and supported==len(computed) else 'mixed' if supported or failed_adequacy else 'not_detected' if complete else 'inconclusive'
            label='条件厚尾有检验支持' if conclusion=='supported' else '部分段支持 / 模型需检查' if conclusion=='mixed' else '未拒绝高斯 GARCH 尾部参照' if conclusion=='not_detected' else '检验覆盖不完整'
            text=f"{supported}/{len(ct['segments'])} 个连续段在重新拟合的高斯 GARCH 参照下，同时检出偏高峰度和 3σ 尾概率。"
            if failed_adequacy:
                text+=f" {failed_adequacy} 段残差仍有相关，不能归因于创新项厚尾。"
        unavailable_reasons=list(dict.fromkeys(r.get('reason') for r in references if r.get('reason')))
        if not computed and unavailable_reasons:
            text+=' 检验未完成：'+'；'.join(unavailable_reasons)+'。'
        add(7, conclusion, label, text,
            [metric('评估收益数',ct['n_evaluated']),metric('完成模拟检验段数',len(computed)),
             metric('最小校正尾部 p',min((r['family_adjusted_tail_p'] for r in computed),default=None))],
            level='test' if computed else 'descriptive' if known else 'unavailable',
            evidence={'segments':[{'segment':x['segment'],'tail_pattern':flag,'reference_test':ref} for x,flag,ref in zip(fitted,signs,references)]})

    vp = group["volatility_persistence"]
    endpoint = at_lag(vp["full"], config.volatility_max_lag)
    lm = vp["long_memory_test"]
    decay=vp.get('decay_comparison',{})
    full=[r for r in decay.get('rows',[]) if r['period']=='full' and r['status']=='computed']
    if full:
        primary=full[0];power=primary['models']['power'];exp=primary['models']['exponential']
        stable=decay['stable_slow_power_pattern']
        persistence_test=persistence_evidence(lm)
        preference=[r['preferred'] for r in full]
        label='跨区间、分段均偏向缓慢幂律衰减' if stable else '全路径偏向幂律，分段支持不足' if len(full)==2 and all(r.get('slow_power_pattern') for r in full) else '全路径更符合指数衰减' if len(full)==2 and all(p=='exponential' for p in preference) else '衰减形式未分出稳定优劣'
        text=f"预设 lag {primary['start_lag']}–{primary['end_lag']} 的幂律指数 β={number(power['shape'])}；幂律 / 指数拟合 RMSE 分别为 {number(power['rmse'])} / {number(exp['rmse'])}。"
        text+=' 比较同时检查远端滞后预测误差和时间分段稳定性。'
        if persistence_test['stable_upper_rejection']:
            label='长程持续性有检验支持'
            text+=' 全段及半段的各带宽修正 R/S 均拒绝短期依赖参照，方向为持续性偏强。'
        elif persistence_test['full_upper_rejection']:
            text+=' 全段 R/S 有持续性证据，但半段结果未一致支持。'

        add(8,'supported' if persistence_test['stable_upper_rejection'] else 'indicative' if stable else 'mixed',label,text,
            [metric('终点 ACF',endpoint),metric('R/S 修正后拒绝数',lm.get('family_rejections')),
             metric('幂律指数 β',power['shape']),metric('幂律 R²',power['r_squared'])],
            level='asymptotic' if persistence_test['stable_upper_rejection'] else 'model',evidence={**decay,'persistence_test':persistence_test},
            notes=['有限滞后内的曲线比较；长期记忆的辅助检验另保存在 R/S 结果中。'])
    elif endpoint is None:
        unavailable(8, decay.get('reason') or '配置范围的相关不可计算。')
    else:
        add(8,'insufficient_data','衰减拟合数据不足',decay.get('reason') or '未运行预设范围的衰减比较。',
            [metric('终点 ACF',endpoint),metric('R/S 修正后拒绝数',lm.get('family_rejections'))],level='unavailable',evidence=decay)

    ev = [lag_evidence(group, config, "leverage", p) for p in ("absolute", "squared")]
    negative = sorted(set(ev[0]["negative_lags"]) & set(ev[1]["negative_lags"]))
    lv = [at_lag(group["leverage"][p], 1) for p in ("absolute", "squared")]
    if any(v is None for v in lv):
        unavailable(9, "收益与未来波动的有效配对不足或方差为零。")
    else:
        add(9, "supported" if negative else "inconclusive", "负向关系有支持" if negative else "杠杆效应证据不足",
            f"两种波动指标在 lag {', '.join(map(str, negative))} 均有负相关区间支持。" if negative else "所检滞后内，两种波动指标未共同给出负相关区间证据。",
            [metric("收益与下期绝对收益", lv[0]), metric("收益与下期平方收益", lv[1])],
            level="interval" if negative else "descriptive", evidence={"absolute":ev[0], "squared":ev[1]})

    vol = group["volume_volatility"]
    if vol["status"] != "computed":
        unavailable(10, vol["reason"] or "量价关系不可计算。", "not_applicable" if vol["status"] == "not_applicable" else "insufficient_data")
    else:
        va = vol["correlations"]["absolute"]
        ep = block_evidence(group, config, "volume_abs_pearson")
        er = block_evidence(group, config, "volume_abs_spearman")
        supported = ep["positive"] and er["positive"]
        point = va["pearson"] is not None and va["spearman"] is not None and va["pearson"] > 0 and va["spearman"] > 0
        add(10, "supported" if supported else "indicative" if point else "mixed", "量价正相关有支持" if supported else "有正相关迹象" if point else "未见一致正相关",
            "成交量与绝对收益的 Pearson、Spearman 区间在各块长下均为正。" if supported else "保留 Pearson 与 Spearman 对照；近似区间未给出一致正相关支持。",
            [metric("Pearson", va["pearson"]), metric("Spearman", va["spearman"]), metric("配对数", va["pair_count"])],
            level="interval" if supported else "descriptive", evidence={"pearson":ep, "spearman":er})

    ts = group["timescale_asymmetry"]
    ev = lag_evidence(group, config, "timescale", "difference")
    row = next((x for x in ts["differences"] if x["lag"] == 1), {})
    if row.get("difference") is None:
        unavailable(11, ts.get("reason") or "粗细波动的配对不足或方差为零。")
    else:
        neg, pos = ev["negative_lags"], ev["positive_lags"]
        c = "mixed" if neg and pos else "supported" if neg or pos else "inconclusive"
        label = "方向随滞后变化" if neg and pos else "粗在前更强" if neg else "细在前更强" if pos else "方向差异证据不足"
        text = f"每步 {lag_label(config, factor=config.coarse_factor)}。"
        if neg:
            text += f" lag {', '.join(map(str, neg))} 的区间支持粗波动在前更强。"
        if pos:
            text += f" lag {', '.join(map(str, pos))} 的区间支持细波动在前更强。"
        if not (neg or pos):
            text += " 所检滞后内，两种先后顺序尚未取得跨带宽一致的方向差异证据。"
        add(11, c, label, text, [metric("相邻粗区间方向差", row["difference"])],
            level="interval" if neg or pos else "descriptive", evidence=ev)

    for key,status in [('5',fi.get('status','not_computable')),('7',ct['status']),('8',decay.get('status','not_computable'))]:
        rows[key]['computation_status']=status
    # Put the actual supporting lags beside the verdict, rather than letting a
    # lag-1 display value appear to be the evidence for a multi-lag conclusion.
    for i, supporting in [(1, selected), (6, common), (9, negative), (11, sorted(neg + pos) if row.get("difference") is not None else [])]:
        rows[str(i)]["scope_note"] = "区间支持的 lag：" + ", ".join(map(str, supporting)) if supporting else ""
    return {"rule_version": RULE_VERSION, "automatic_pass_fail": False,
            "method": "fixed_evidence_rules", "by_fact": dict(sorted(rows.items(), key=lambda x: int(x[0])))}
