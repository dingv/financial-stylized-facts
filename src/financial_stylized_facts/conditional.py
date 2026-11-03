"""Gaussian QMLE GARCH(1,1) residual diagnostics, never bridging missing data."""
from importlib.metadata import version
import warnings

import numpy as np

from .statistics import distribution, autocorrelation


def continuous_segments(sampled):
    """Keep chronological sessions and split at every missing return slot."""
    for session, group in sampled.groupby("session_id", sort=False):
        group = group.sort_values("timestamp", kind="stable").reset_index(drop=True)
        valid = np.isfinite(group["log_return"].to_numpy(dtype=float))
        edges = np.diff(np.r_[False, valid, False].astype(int))
        for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            yield str(session), group.iloc[start:end].copy()


def fit_garch(returns, max_iter=500, burn=50, max_lag=30, min_pairs=20):
    """Return auditable summaries and aligned post-initialization arrays.

    Explicit centering/scaling gives the optimizer order-one inputs; rescale=False
    prevents a hidden second transformation. Original units are restored below.
    """
    from arch import arch_model

    r = np.asarray(returns, dtype=float)
    if r.ndim != 1 or not np.isfinite(r).all() or len(r)-burn < 4:
        raise ValueError("GARCH requires a complete finite segment and at least four retained values")
    center, scale = float(r.mean()), float(r.std())
    if not np.isfinite(scale) or scale <= np.finfo(float).eps*max(float(np.max(np.abs(r))), np.finfo(float).tiny):
        return {"status": "zero_variance", "reason": "收益没有足够变化，无法拟合波动模型"}, None
    y = (r-center)/scale
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = arch_model(y, mean="Constant", vol="GARCH", p=1, o=0, q=1, dist="normal", rescale=False)
        fit = model.fit(disp="off", update_freq=0, show_warning=False, options={"maxiter": max_iter, "ftol": 1e-8})
    result = {"status": "fit_failed", "reason": None, "n_fit": len(r), "burn": burn,
              "optimizer_status": int(fit.convergence_flag), "optimizer_message": str(fit.optimization_result.message),
              "optimizer_iterations": int(fit.optimization_result.get("nit", 0)),
              "input_center": center, "input_scale": scale,
              "warnings": [str(w.message) for w in caught], "flags": []}
    if fit.convergence_flag != 0:
        result["reason"] = "优化未收敛，不输出残差分布结论"
        return result, None
    p = fit.params
    sigma = np.asarray(fit.conditional_volatility, dtype=float)
    z = np.asarray(fit.std_resid, dtype=float)
    if not np.isfinite(p).all() or not np.isfinite(sigma).all() or (sigma <= 0).any() or not np.isfinite(z).all():
        result["reason"] = "拟合参数或条件波动无效，不输出残差分布结论"
        return result, None
    alpha, beta = float(p["alpha[1]"]), float(p["beta[1]"])
    if min(alpha, beta) < 1e-6:
        result["flags"].append("coefficient_near_zero_boundary")
    if alpha+beta >= .995:
        result["flags"].append("near_unit_persistence")
    if alpha < -1e-7 or beta < -1e-7 or alpha+beta > 1+1e-6 or p["omega"] <= 0:
        result["reason"] = "参数不满足 GARCH 方差约束"
        return result, None
    mu = center+float(p["mu"])*scale
    raw, residual = r[burn:], z[burn:]
    result.update(status="computed", n_evaluated=len(raw),
                  parameters={"mu": mu, "omega": float(p["omega"])*scale**2, "alpha": alpha, "beta": beta,
                              "persistence": alpha+beta},
                  raw_distribution=distribution(raw), residual_distribution=distribution(residual),
                  raw_squared_acf=autocorrelation([((raw-raw.mean())/raw.std())**2], max_lag, min_pairs)
                  if raw.std() > 0 else autocorrelation([raw*0], max_lag, min_pairs),
                  residual_squared_acf=autocorrelation([residual**2], max_lag, min_pairs),
                  interpretation="in_sample_descriptive_only")
    arrays = {"raw": raw, "standardized_residual": residual, "conditional_volatility": sigma[burn:]*scale,
              "fitted_mean": np.full(len(raw), mu)}
    return result, arrays


def conditional_diagnostics(sampled, config, seed_key=""):
    result = {"status": "disabled", "reason": "本次关闭条件厚尾模块", "model": "constant_mean_gaussian_qmle_garch_1_1",
              "arch_version": None, "segments": [], "n_fit": 0, "n_evaluated": 0,
              "total_valid_returns": int(sampled["log_return"].notna().sum()),
              "uncertainty": "not_implemented", "selection": "chronological_complete_segments_with_explicit_limits"}
    plots = []
    if config.conditional_model == "off":
        return result, plots
    try:
        from arch import arch_model  # noqa: F401; verify optional runtime dependency.
        result["arch_version"] = version("arch")
    except ImportError:
        result.update(status="dependency_missing", reason="未安装可选依赖 arch；安装本库的 conditional 扩展后可启用")
        return result, plots
    from .conditional_inference import conditional_reference, finalize_conditional
    attempted, consumed = 0, 0
    reference_budget = [0]
    planned_family = sum(len(g)>=config.garch_min_points for _,g in continuous_segments(sampled))
    for number, (session, frame) in enumerate(continuous_segments(sampled), 1):
        row = {"segment": number, "session_id": session, "n": len(frame),
               "start": str(frame.timestamp.iloc[0]), "end": str(frame.timestamp.iloc[-1])}
        if len(frame) < config.garch_min_points:
            row.update(status="insufficient_data", reason=f"连续收益少于 {config.garch_min_points} 条")
        elif attempted >= config.garch_max_segments or consumed+len(frame) > config.garch_max_points:
            row.update(status="resource_limit", reason="超过本路径 GARCH 拟合段数或总样本上限；未截断或抽取该段")
        else:
            attempted += 1
            consumed += len(frame)
            try:
                fit, arrays = fit_garch(frame.log_return.to_numpy(), config.garch_max_iter, config.garch_burn, config.max_lag, config.min_pairs)
                row.update(fit)
                if arrays is not None:
                    row["reference_test"] = conditional_reference(frame.log_return.to_numpy(), fit, arrays, config,
                                                                  seed_key+f":{number}", reference_budget)
                    row['interpretation'] = 'in_sample_metrics_with_refitted_gaussian_reference' if row['reference_test']['status']=='computed' else 'in_sample_descriptive_reference_unavailable'
                    result["n_fit"] += len(frame)
                    result["n_evaluated"] += len(arrays["raw"])
                    plots.append({"segment": number, "timestamps": frame.timestamp.iloc[config.garch_burn:].tolist(), **arrays})
            except (ValueError, RuntimeError, FloatingPointError, np.linalg.LinAlgError) as exc:
                row.update(status="fit_failed", reason=f"拟合失败：{exc}")
        result["segments"].append(row)
    successful = sum(s["status"] == "computed" for s in result["segments"])
    result["attempted_segments"] = attempted
    result["attempted_points"] = consumed
    result["evaluated_fraction"] = result["n_evaluated"]/result["total_valid_returns"] if result["total_valid_returns"] else None
    if successful:
        result.update(status="computed" if successful == len(result["segments"]) else "partially_computed", reason=None)
    else:
        result.update(status="not_computable", reason="没有完成可用的 GARCH 拟合；请查看各段原因")
    finalize_conditional(result, planned_family)
    result['uncertainty'] = {'method':'gaussian_garch_simulate_refit', 'planned_segment_family':planned_family,
                             'estimated_work':reference_budget[0], 'replications':config.conditional_bootstrap_reps}
    return result, plots
