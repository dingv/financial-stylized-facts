"""Self-contained HTML plus reusable numerical exports; no external services."""
import base64
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
from io import BytesIO
import json
from pathlib import Path
import platform

from jinja2 import Environment, FileSystemLoader, select_autoescape
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg
import matplotlib.dates as mdates
import numpy as np
import pandas as pd
from scipy.stats import gaussian_kde

from . import __version__
from .data import AnalysisConfig, read_prices, sample_path
from .statistics import distribution, three_acfs
from .tails import tail_diagnostics
from .diagnostics import analyze_diagnostics
from .dependence import dependence_diagnostics
from .activity import activity_diagnostics
from .conditional import conditional_diagnostics
from .uncertainty import uncertainty_diagnostics
from .inference import dependence_uncertainty
from .first_passage import first_passage_diagnostics
from .findings import summarize, lag_label, human_timestamp
from .assessment import assess, RULE_VERSION


FACT_NAMES = ["收益自相关", "厚尾", "涨跌不对称", "聚合高斯化", "间歇性", "波动聚集", "条件厚尾", "波动相关的慢衰减", "杠杆效应", "成交量与波动", "时间尺度不对称"]


def _figure(width=9.6, height=3.6):
    fig = Figure(figsize=(width, height), layout="constrained", facecolor="white")
    FigureCanvasAgg(fig)
    return fig


def _style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(alpha=.18)
    ax.tick_params(labelsize=9)


def _save(fig, path):
    buffer = BytesIO()
    fig.savefig(buffer, format="png", dpi=140)
    path.write_bytes(buffer.getvalue())
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _align_inference(inference, acfs, diagnostics):
    """Respect the report's numerical availability gates and verify estimands."""
    for row in inference["rows"]:
        if row["family"] == "acf":
            estimate = acfs[row["proxy"]]
            values = dict(zip(estimate["lags"], estimate["values"]))
        elif row["family"] == "leverage":
            estimate = diagnostics["leverage"][row["proxy"]]
            values = dict(zip(estimate["lags"], estimate["values"]))
        else:
            values = {r["lag"]:r["difference"] for r in diagnostics["timescale_asymmetry"]["differences"]}
        expected = values.get(row["lag"])
        if expected is None:
            row.update(estimate=None, status="not_computable", reason="对应报告点估计不可计算；不对缺失点另作推断",
                       standard_error=None, lower=None, upper=None, familywise_lower=None, familywise_upper=None)
        elif row["estimate"] is not None and not np.isclose(row["estimate"],expected,rtol=1e-7,atol=1e-9):
            raise ValueError("HAC 与报告点估计不一致，停止生成推断报告")
    if inference["rows"]:
        available = sum(r["status"] == "computed" for r in inference["rows"])
        inference["status"] = "computed" if available == len(inference["rows"]) else "partially_computed" if available else "not_computable"
        if not available:
            inference["reason"] = "没有满足样本、带宽和方差条件的区间；查看逐项原因"


def _inference_band(ax, inference, family, proxy, factor, color="#2563a6"):
    """Show the predeclared primary bandwidth only; unavailable rows stay gaps."""
    rows = [r for r in inference["rows"] if r["family"] == family and r["proxy"] == proxy
            and r["bandwidth"] == inference["plot_bandwidth"]]
    if not any(r["status"] == "computed" for r in rows):
        return
    # Separate signs: do not draw a band across the omitted lag zero.
    for sign in [-1, 1]:
        selected = sorted([r for r in rows if r["lag"]*sign > 0], key=lambda r:r["lag"])
        if not selected:
            continue
        x = [r["lag"]*factor for r in selected]
        low = [r["lower"] if r["status"] == "computed" else np.nan for r in selected]
        high = [r["upper"] if r["status"] == "computed" else np.nan for r in selected]
        centers = np.array([r["estimate"] if r["status"] == "computed" else np.nan for r in selected])
        ax.fill_between(x, low, high, color=color, alpha=.14)
        ax.errorbar(x, centers, yerr=[centers-low, np.asarray(high)-centers],
                    fmt="none", color=color, alpha=.35, linewidth=.7)
    ax.text(.98, .98, f"95% pointwise HAC (B={inference['plot_bandwidth']})",
            transform=ax.transAxes, ha="right", va="top", fontsize=7)


def _plots(sampled, metrics, acfs, inference, config, directory, group_id):
    paths, embedded = {}, {}
    fig = _figure(height=4.6)
    axes = fig.subplots(2, 1, sharex=True)
    for _, g in sampled.groupby("session_id", sort=False):
        axes[0].plot(g["timestamp"], g["price"], color="#2563a6", linewidth=.9)
        axes[1].plot(g["timestamp"], g["log_return"], color="#598778", linewidth=.6)
    axes[0].set_ylabel("Price")
    axes[1].set_ylabel("Log return")
    axes[1].set_xlabel("Time (UTC)")
    locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
    axes[1].xaxis.set_major_locator(locator)
    axes[1].xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    for ax in axes:
        _style(ax)
    paths["timeline"] = f"figures/{group_id}-timeline.png"
    embedded["timeline"] = _save(fig, directory / paths["timeline"])

    fig = _figure()
    ax = fig.subplots()
    x = sampled["log_return"].dropna().to_numpy(dtype=float)
    density = {"status": "not_computed", "method": "scipy_gaussian_kde", "bandwidth_rule": "scott", "bandwidth_factor": None}
    if len(x) >= 2 and np.std(x) > 0:
        try:
            estimate = gaussian_kde(x, bw_method="scott")
            margin = max(float(np.ptp(x)) * .05, float(np.std(x)))
            grid = np.linspace(x.min()-margin, x.max()+margin, 384)
            y = estimate(grid)
            ax.plot(grid, y, color="#2563a6", linewidth=2)
            ax.fill_between(grid, y, color="#2563a6", alpha=.08)
            density.update(status="computed", bandwidth_factor=float(estimate.factor))
        except (ValueError, np.linalg.LinAlgError) as exc:
            density.update(status="failed", reason=str(exc))
            ax.text(.5, .5, "KDE unavailable; see numerical output", transform=ax.transAxes, ha="center")
    elif len(x):
        ax.axvline(x[0], color="#2563a6")
        ax.text(.5, .85, "Constant / single observation: no density estimate", transform=ax.transAxes, ha="center", fontsize=9)
        density.update(status="zero_variance", reason="单点或常数序列不绘制平滑密度")
    else:
        ax.text(.5, .5, "No valid returns at this sampling frequency", transform=ax.transAxes, ha="center")
        density.update(status="insufficient_data", reason="没有有效收益")
    ax.set_xlabel("Log return")
    ax.set_ylabel("Density")
    _style(ax)
    paths["density"] = f"figures/{group_id}-density.png"
    embedded["density"] = _save(fig, directory / paths["density"])

    fig = _figure(height=3.3)
    axes = fig.subplots(1, 3, sharey=True)
    if config.sampling == "grid":
        seconds = pd.Timedelta(config.frequency).total_seconds()
        divisor, unit = (60, "min") if seconds < 3600 else (3600, "hours")
        if seconds < 60:
            divisor, unit = 1, "seconds"
        factor = seconds / divisor
        xlabel = f"Lag ({unit})"
    else:
        factor, xlabel = 1, "Lag (observations)"
    for ax, name, label in zip(axes, acfs, ["Return", "Absolute return", "Squared return"]):
        result = acfs[name]
        lags = np.asarray(result["lags"])[1:] * factor
        values = np.array([np.nan if v is None else v for v in result["values"][1:]])
        ax.axhline(0, color="#9aa3ad", linewidth=.8)
        if np.isfinite(values).any():
            ax.plot(lags, values, "o-", color="#2563a6", markersize=3, linewidth=1)
            _inference_band(ax, inference, "acf", name, factor)
        else:
            ax.text(.5, .5, "Not computable", transform=ax.transAxes, ha="center", fontsize=9)
        ax.set(title=label, xlabel=xlabel)
        _style(ax)
    axes[0].set_ylabel("Autocorrelation")
    paths["acf"] = f"figures/{group_id}-acf.png"
    embedded["acf"] = _save(fig, directory / paths["acf"])
    return paths, embedded, density


def _fmt(value):
    return "不可计算" if value is None else f"{value:.4g}"


def _tail_plot(diagnostic, directory, group_id):
    fig = _figure(height=3.6)
    axes = fig.subplots(1, 2)
    if diagnostic["status"] == "computed":
        rows = diagnostic["ccdf"]
        axes[0].plot([r["threshold_sigma"] for r in rows],
                     [r["probability"] if r["count"] else np.nan for r in rows],
                     color="#2563a6", linewidth=1.5)
        axes[0].set_yscale("log")
        axes[0].axhline(1/diagnostic["n"], color="#9aa3ad", linestyle=":", label="One observation / N")
        axes[0].legend(fontsize=8)
        qq = diagnostic["qq"]
        a = [r["normal_quantile"] for r in qq]
        b = [r["sample_quantile"] for r in qq]
        axes[1].plot(a, b, ".", color="#2563a6", markersize=3)
        low, high = min(a[0], b[0]), max(a[-1], b[-1])
        axes[1].plot([low, high], [low, high], "--", color="#9aa3ad", linewidth=1)
    else:
        for ax in axes:
            ax.text(.5, .5, "Not computable", transform=ax.transAxes, ha="center")
    axes[0].set(xlabel="Threshold (path standard deviations)", ylabel="P(|z| > threshold)", title="Empirical tail probabilities")
    axes[1].set(xlabel="Standard normal quantile", ylabel="Standardized return order statistic", title="Normal Q-Q comparison")
    for ax in axes:
        _style(ax)
    path = f"figures/{group_id}-tail-diagnostics.png"
    return {"tail_diagnostics": path}, {"tail_diagnostics": _save(fig, directory/path)}


def _first_passage_plot(result, config, directory, group_id):
    thresholds = result["thresholds"]
    fig = _figure(height=3.5)
    axes = np.atleast_1d(fig.subplots(1,max(1,len(thresholds)),sharey=True))
    if config.sampling == "grid":
        seconds = pd.Timedelta(config.frequency).total_seconds()
        divisor,unit = (86400,"days") if seconds>=86400 else (3600,"hours") if seconds>=3600 else (60,"min") if seconds>=60 else (1,"seconds")
        factor,xlabel = seconds/divisor,f"Elapsed time ({unit})"
    else:
        factor,xlabel = 1.,"Elapsed observations"
    for ax,row in zip(axes,thresholds):
        for direction,label,color in [("up","Gain", "#2563a6"),("down","Loss", "#c77d55")]:
            values = row[direction]["curve"]
            if row[direction]["full_hit_probability"] is not None:
                ax.step([0]+[r["horizon"]*factor for r in values], [0]+[r["full_cdf"] for r in values],
                        where="post",label=label,color=color,linewidth=1.7)
        if ax.lines:
            ax.legend(frameon=False,fontsize=8)
        else:
            ax.text(.5,.5,"Too few full-window starts",transform=ax.transAxes,ha="center",fontsize=8)
        unit = "sigma" if config.first_passage_unit=="sigma" else "log return"
        ax.set_title(f"+/- {row['configured_threshold']:g} {unit}",fontsize=11)
    if not thresholds:
        axes[0].text(.5,.5,"First passage unavailable; see explanation",transform=axes[0].transAxes,ha="center",fontsize=9)
    for ax in axes:
        ax.set(xlabel=xlabel,ylim=(0,1.03))
        _style(ax)
    axes[0].set_ylabel("Fraction reaching threshold")
    path = f"figures/{group_id}-first-passage.png"
    return {"first_passage":path},{"first_passage":_save(fig,directory/path)}


def _conditional_plots(result, arrays, config, directory, group_id):
    paths, embedded = {}, {}
    rows = {r["segment"]: r for r in result["segments"]}
    for data in arrays:
        number = data["segment"]
        row = rows[number]
        raw = data["raw"]
        standardized = (raw-raw.mean())/raw.std() if raw.std() > 0 else raw*0
        fig = _figure(height=3.6)
        axes = fig.subplots(1, 2)
        for values, label, color in [(standardized, "Raw (standardized)", "#9aa3ad"),
                                      (data["standardized_residual"], "GARCH residual", "#2563a6")]:
            if len(values) >= 2 and np.std(values) > 0:
                try:
                    kde = gaussian_kde(values, bw_method="scott")
                    grid = np.linspace(values.min()-values.std(), values.max()+values.std(), 384)
                    axes[0].plot(grid, kde(grid), color=color, label=label, linewidth=1.6)
                except (ValueError, np.linalg.LinAlgError):
                    row.setdefault("plot_warnings", []).append(f"KDE unavailable: {label}")
        axes[0].set(xlabel="Standardized return / residual", ylabel="Density", title="Before and after filtering")
        if axes[0].lines:
            axes[0].legend(frameon=False, fontsize=8)
        if config.sampling == "grid":
            seconds = pd.Timedelta(config.frequency).total_seconds()
            divisor, unit = (3600, "hours") if seconds >= 3600 else (60, "min") if seconds >= 60 else (1, "seconds")
            factor, xlabel = seconds/divisor, f"Lag ({unit})"
        else:
            factor, xlabel = 1, "Lag (observations)"
        for key, label, color in [("raw_squared_acf", "Raw squared", "#9aa3ad"),
                                  ("residual_squared_acf", "Residual squared", "#2563a6")]:
            estimate = row[key]
            values = [np.nan if v is None else v for v in estimate["values"][1:]]
            axes[1].plot(np.asarray(estimate["lags"])[1:]*factor, values, color=color, label=label, linewidth=1.2)
        axes[1].axhline(0, color="#9aa3ad", linewidth=.8)
        axes[1].legend(frameon=False, fontsize=8)
        axes[1].set(xlabel=xlabel, ylabel="Autocorrelation", title="Remaining volatility dependence")
        for ax in axes:
            _style(ax)
        key = f"conditional_{number}"
        paths[key] = f"figures/{group_id}-{key}.png"
        embedded[key] = _save(fig, directory/paths[key])
        row["figure_key"] = key
        row["figure"] = paths[key]
        (directory/"conditional").mkdir(exist_ok=True)
        row["residual_file"] = f"conditional/{group_id}-s{number:04d}.csv"
        pd.DataFrame({"timestamp": data["timestamps"], "log_return": raw,
                      "fitted_mean": data["fitted_mean"], "conditional_volatility": data["conditional_volatility"],
                      "standardized_residual": data["standardized_residual"]}).to_csv(directory/row["residual_file"], index=False)
    return paths, embedded


def _activity_plots(diagnostics, config, directory, group_id):
    paths, embedded = {}, {}
    volume = diagnostics["volume_volatility"]
    if volume["status"] != "not_applicable":
        fig = _figure(height=3.5)
        ax = fig.subplots()
        bins = volume["bins"]
        if bins:
            ax.plot([b["mean_volume"] for b in bins], [b["mean_absolute_return"] for b in bins],
                    "o-", color="#2563a6")
            for b in bins:
                ax.annotate(f"n={b['n']}", (b["mean_volume"], b["mean_absolute_return"]),
                            xytext=(0, 7), textcoords="offset points", ha="center", fontsize=8)
            ax.margins(y=.25)
        else:
            ax.text(.5, .5, "Insufficient paired intervals", transform=ax.transAxes, ha="center")
        # Units are displayed in HTML, so arbitrary Unicode units don't break fonts.
        ax.set(xlabel="Mean interval volume (declared unit)", ylabel="Mean absolute return")
        _style(ax)
        paths["volume"] = f"figures/{group_id}-volume.png"
        embedded["volume"] = _save(fig, directory/paths["volume"])

    fig = _figure(height=3.6)
    axes = fig.subplots(1, 2)
    estimate = diagnostics["timescale_asymmetry"]
    rows = estimate["differences"]
    if config.sampling == "grid":
        seconds = pd.Timedelta(config.frequency).total_seconds()*config.coarse_factor
        divisor, unit = (3600, "hours") if seconds >= 3600 else (60, "min") if seconds >= 60 else (1, "seconds")
        factor, xlabel = seconds/divisor, f"Separation ({unit})"
    else:
        factor, xlabel = config.coarse_factor, "Separation (observations)"
    x = [r["lag"]*factor for r in rows]
    for key, label, color in [("coarse_leads_fine", "Coarse earlier / fine later", "#2563a6"),
                               ("fine_leads_coarse", "Fine earlier / coarse later", "#c77d55")]:
        axes[0].plot(x, [np.nan if r[key] is None else r[key] for r in rows], color=color, label=label, linewidth=1.4)
    axes[1].plot(x, [np.nan if r["difference"] is None else r["difference"] for r in rows], color="#598778", linewidth=1.4)
    _inference_band(axes[1], diagnostics["dependence_uncertainty"], "timescale", "difference", factor, "#598778")
    if estimate["status"] == "computed":
        axes[0].legend(frameon=False, fontsize=8)
    for ax in axes:
        ax.axhline(0, color="#9aa3ad", linewidth=.8)
        ax.set_xlabel(xlabel)
        if estimate["status"] != "computed":
            ax.text(.5, .5, "Insufficient pairs / zero variance", transform=ax.transAxes, ha="center", fontsize=8)
        _style(ax)
    axes[0].set_ylabel("Correlation")
    axes[1].set_ylabel("Difference (orange minus blue)")
    axes[0].set_title("Two time directions")
    axes[1].set_title("Time-scale asymmetry")
    paths["timescale"] = f"figures/{group_id}-timescale.png"
    embedded["timescale"] = _save(fig, directory/paths["timescale"])
    return paths, embedded


def _dependence_plots(diagnostics, config, directory, group_id):
    paths, embedded = {}, {}
    if config.sampling == "grid":
        seconds = pd.Timedelta(config.frequency).total_seconds()
        divisor, unit = (3600, "hours") if seconds >= 3600 else (60, "min") if seconds >= 60 else (1, "seconds")
        factor, xlabel = seconds/divisor, f"Lag ({unit})"
    else:
        factor, xlabel = 1., "Lag (observations)"
    fig = _figure(height=3.6)
    axes = fig.subplots(1, 2, sharey=True)
    for ax, proxy, title in zip(axes, ["squared", "absolute"], ["Squared-return proxy", "Absolute-return proxy"]):
        estimate = diagnostics["leverage"][proxy]
        values = [np.nan if v is None else v for v in estimate["values"]]
        ax.axhline(0, color="#9aa3ad", linewidth=.8)
        ax.axvline(0, color="#9aa3ad", linestyle=":", linewidth=.8)
        if np.isfinite(values).any():
            ax.plot(np.asarray(estimate["lags"])*factor, values, color="#2563a6", linewidth=1, marker=".", markersize=3)
            _inference_band(ax, diagnostics["dependence_uncertainty"], "leverage", proxy, factor)
        else:
            ax.text(.5, .5, "Not computable", transform=ax.transAxes, ha="center")
        ax.set(title=title, xlabel=xlabel)
        _style(ax)
    axes[0].set_ylabel("Return / volatility correlation")
    paths["leverage"] = f"figures/{group_id}-leverage.png"
    embedded["leverage"] = _save(fig, directory/paths["leverage"])

    fig = _figure(height=3.6)
    axes = fig.subplots(1, 2, sharey=True)
    persistence = diagnostics["volatility_persistence"]
    estimates = [[("Full path", persistence["full"])], [(f"Block {b['block']}", b["acf"]) for b in persistence["blocks"]]]
    for ax, curves, title in zip(axes, estimates, ["Full-path absolute-return ACF", "Chronological blocks"]):
        plotted = False
        for label, estimate in curves:
            lags = np.asarray(estimate["lags"])[1:]*factor
            values = [np.nan if v is None else v for v in estimate["values"][1:]]
            if np.isfinite(values).any():
                ax.plot(lags, values, linewidth=1., label=label)
                plotted = True
        ax.axhline(0, color="#9aa3ad", linewidth=.8)
        if not plotted:
            ax.text(.5, .5, "Insufficient pairs / zero variance", transform=ax.transAxes, ha="center", fontsize=9)
        elif len(curves) > 1:
            ax.legend(frameon=False, fontsize=8, ncol=2)
        ax.set(title=title, xlabel=xlabel)
        _style(ax)
    axes[0].set_ylabel("Absolute-return autocorrelation")
    paths["persistence"] = f"figures/{group_id}-persistence.png"
    embedded["persistence"] = _save(fig, directory/paths["persistence"])
    return paths, embedded


def _diagnostic_plots(sampled, diagnostics, rms, config, directory, group_id):
    paths, embedded = {}, {}
    fig = _figure(height=3.5)
    ax = fig.subplots()
    tails = diagnostics["asymmetry"]["tails"]
    if tails:
        thresholds = np.array([row["sigma"] for row in tails])
        ax.bar(thresholds-.17, [r["left_probability"] for r in tails], .34, label="Left tail", color="#c77d55")
        ax.bar(thresholds+.17, [r["right_probability"] for r in tails], .34, label="Right tail", color="#2563a6")
        ax.set_xticks(thresholds)
        ax.legend(frameon=False)
    else:
        ax.text(.5, .5, "Insufficient data / zero variance", transform=ax.transAxes, ha="center")
    ax.set(xlabel="Distance from path mean (standard deviations)", ylabel="Fraction of returns")
    _style(ax)
    paths["asymmetry"] = f"figures/{group_id}-asymmetry.png"
    embedded["asymmetry"] = _save(fig, directory/paths["asymmetry"])

    fig = _figure(height=3.5)
    axes = fig.subplots(1, 2)
    rows = diagnostics["aggregation"]["scales"]
    locations = np.asarray([r["factor"] for r in rows])
    labels = [str(pd.Timedelta(config.frequency)*r["factor"]) if config.sampling == "grid"
              else f"{r['factor']} obs." for r in rows]
    # Use compact elapsed units rather than long Timedelta strings on the axis.
    if config.sampling == "grid":
        seconds = [pd.Timedelta(config.frequency).total_seconds()*r["factor"] for r in rows]
        labels = [f"{s/3600:g}h" if s >= 3600 else f"{s/60:g}m" if s >= 60 else f"{s:g}s" for s in seconds]
    for ax, key, title in zip(axes, ["excess_kurtosis", "normal_quantile_rmse"], ["Excess kurtosis", "Normal quantile RMSE"]):
        values = [np.nan if r[key] is None else r[key] for r in rows]
        ax.plot(locations, values, "o-", color="#2563a6", markersize=4)
        ax.axhline(0, linewidth=.8, color="#9aa3ad")
        ax.set_xticks(locations, labels, rotation=35 if len(rows)>5 else 0)
        ax.set(title=title, xlabel="Return interval")
        if not np.isfinite(values).any():
            ax.text(.5, .5, "Not computable", transform=ax.transAxes, ha="center")
        _style(ax)
    paths["aggregation"] = f"figures/{group_id}-aggregation.png"
    embedded["aggregation"] = _save(fig, directory/paths["aggregation"])

    fig = _figure(height=3.5)
    ax = fig.subplots()
    for (_, frame), values in zip(sampled.groupby("session_id", sort=False), rms):
        ax.plot(frame["timestamp"], values, color="#598778", linewidth=1)
    if not any(np.isfinite(a).any() for a in rms):
        ax.text(.5, .5, "No complete rolling window", transform=ax.transAxes, ha="center")
    locator = mdates.AutoDateLocator(minticks=3, maxticks=6)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(locator))
    ax.set(xlabel="Time (UTC)", ylabel=f"Rolling RMS ({config.rms_window} returns)")
    _style(ax)
    paths["intermittency"] = f"figures/{group_id}-intermittency.png"
    embedded["intermittency"] = _save(fig, directory/paths["intermittency"])
    return paths, embedded


def _evidence_plots(diagnostics, config, directory, group_id):
    paths,images={},{}
    fig=_figure(height=3.2);ax=fig.subplots()
    rows=[r for r in diagnostics['intermittency']['inference']['rows'] if r['status']=='computed']
    if rows:
        x=[r['window'] for r in rows]
        ax.fill_between(x,[r['null_lower'] for r in rows],[r['null_upper'] for r in rows],color='#dce7ef',label='95% random-order reference')
        ax.plot(x,[r['fano'] for r in rows],'o-',color='#2563a6',label='Observed')
        ax.legend(frameon=False,fontsize=9)
    else:
        ax.text(.5,.5,'Permutation test unavailable; see reason',transform=ax.transAxes,ha='center')
    ax.set(xlabel='Window (base return observations)',ylabel='Count variance / mean',title='Extreme-event concentration')
    _style(ax);paths['fano']=f'figures/{group_id}-fano.png';images['fano']=_save(fig,directory/paths['fano'])
    fig=_figure(height=3.5);axes=fig.subplots(1,2)
    comparison=diagnostics['volatility_persistence']['decay_comparison']
    acf=diagnostics['volatility_persistence']['full']
    for ax,start in zip(axes,(1,5)):
        row=next(r for r in comparison['rows'] if r['period']=='full' and r['start_lag']==start)
        if row['status']=='computed':
            k=np.arange(start,row['end_lag']+1)
            y=dict(zip(acf['lags'],acf['values']))
            ax.plot(k,[y[i] for i in k],color='#9aa3ad',label='Observed ACF',linewidth=1)
            for kind,color in [('power','#2563a6'),('exponential','#c77d55')]:
                f=row['models'][kind]
                label=f"Power: beta={f['shape']:.2f}" if kind=='power' else f"Exp: lambda={f['shape']:.3f}"
                ax.plot(f['lags'],f['predicted'],color=color,label=label,linewidth=1.7)
            ax.axvline(row['train_end_lag'],color='#aaa',linestyle=':',linewidth=.8)
            ax.legend(frameon=False,fontsize=8)
        else:
            ax.text(.5,.5,'Insufficient range / pairs',transform=ax.transAxes,ha='center',fontsize=9)
        ax.axhline(0,color='#ccc',linewidth=.7);ax.set(xlabel='Lag (base return observations)',ylabel='Absolute-return ACF',title=f'Predefined range: {start}–{config.volatility_max_lag}')
        _style(ax)
    paths['decay']=f'figures/{group_id}-decay.png';images['decay']=_save(fig,directory/paths['decay'])
    return paths,images


def analyze_csv(input_path, output_dir, config=None, title="金融市场 · 统计评估报告", source_provenance=None):
    """Analyze canonical price CSV, writing a new output directory only.

    Returns are non-overlapping. No model simulation or market download occurs.
    """
    config = config or AnalysisConfig()
    input_path, output_dir = Path(input_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("输出目录已存在；请选一个新目录，避免覆盖已有报告")
    raw = input_path.read_bytes()
    input_hash = hashlib.sha256(raw).hexdigest()
    if source_provenance is not None:
        if not isinstance(source_provenance, dict) or source_provenance.get("canonical_sha256") != input_hash:
            raise ValueError("来源清单与输入 CSV 的 SHA256 不一致")
        if not isinstance(source_provenance.get("notes"), list) or not all(isinstance(n, str) for n in source_provenance["notes"]):
            raise ValueError("来源清单 notes 必须为字符串列表")
    prices = read_prices(BytesIO(raw), config)
    groups = []
    for (asset, path), frame in prices.groupby(["asset_id", "path_id"], sort=True):
        sampled, quality = sample_path(frame, config)
        metrics = distribution(sampled["log_return"])
        acfs = three_acfs(sampled, config.max_lag, config.min_pairs)
        diagnostics, rms = analyze_diagnostics(sampled, config)
        diagnostics["tail_diagnostics"] = tail_diagnostics(sampled["log_return"])
        diagnostics.update(dependence_diagnostics(sampled, config))
        diagnostics.update(activity_diagnostics(sampled, config))
        diagnostics["first_passage"] = first_passage_diagnostics(sampled, config)
        from .intermittency import intermittency_test
        diagnostics['intermittency']['inference'] = intermittency_test(sampled,config,str(asset)+"\0"+str(path))
        diagnostics['intermittency']['uncertainty'] = {'status':diagnostics['intermittency']['inference']['status'],
            'reference':'group.intermittency.inference','scope':'极端事件 Fano 置换检验；不覆盖 RMS 或 3σ 片段长度'}
        conditional, residual_arrays = conditional_diagnostics(sampled, config, str(asset)+"\0"+str(path))
        diagnostics["conditional_tails"] = conditional
        diagnostics["uncertainty"] = uncertainty_diagnostics(sampled, config, seed_key=str(asset)+"\0"+str(path))
        diagnostics["dependence_uncertainty"] = dependence_uncertainty(sampled, config)
        _align_inference(diagnostics["dependence_uncertainty"], acfs, diagnostics)
        for estimate in acfs.values():
            estimate["uncertainty"] = {"reference": "group.dependence_uncertainty", "scope": "仅指定早期滞后；HAC 近似区间，非长记忆检验"}
        for proxy, estimate in diagnostics["leverage"].items():
            estimate["uncertainty"] = {"reference": "group.dependence_uncertainty", "family":"leverage", "proxy":proxy, "scope":"仅指定非零滞后"}
        diagnostics["timescale_asymmetry"]["uncertainty"] = {"reference":"group.dependence_uncertainty", "family":"timescale", "scope":"仅指定早期滞后的方向差值，含两向协方差"}
        metrics["uncertainty"] = {"status": diagnostics["uncertainty"]["status"], "reference": "group.uncertainty", "reason": diagnostics["uncertainty"]["reason"]}
        diagnostics["asymmetry"]["uncertainty"] = {**metrics["uncertainty"], "metrics": ["skewness"], "scope": "偏度的近似区间，不覆盖涨跌段或首达时间"}
        diagnostics["volume_volatility"]["uncertainty"] = {**metrics["uncertainty"], "metrics": ["volume_abs_pearson", "volume_abs_spearman", "volume_squared_pearson"], "scope": "仅已声明的量与收益联合重采样，不覆盖季节性调整"} if config.volume_kind == "interval" else {"status": "not_applicable", "reason": "未提供成交量"}
        groups.append((str(asset), str(path), sampled, quality, metrics, acfs, diagnostics, rms, residual_arrays))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "figures").mkdir()
    result = {
        "schema_version": "0.15", "assessment_rule_version": RULE_VERSION, "title": title, "created_at": datetime.now(timezone.utc).isoformat(),
        "config": asdict(config),
        "data_source": source_provenance,
        "provenance": {"input_sha256": input_hash, "input_name": input_path.name, "input_rows": len(prices),
                       "package_version": __version__, "python": platform.python_version(),
                       "dependencies": {p: version(p) for p in ["numpy", "pandas", "scipy", "matplotlib", "jinja2"]}},
        "coverage": [{"fact_id": i, "name": name, "status": "finite_range_model_comparison_and_short_memory_test" if i==8 else "randomization_test" if i==5 else "parametric_bootstrap_test" if i==7 else "descriptive_and_interval_assessment"} for i, name in enumerate(FACT_NAMES, 1)],
        "groups": [],
    }
    source = Path(__file__).parent
    code_files = sorted(source.glob("*.py")) + sorted((source / "templates").glob("*.html"))
    digest = hashlib.sha256()
    for p in code_files:
        digest.update(str(p.relative_to(source)).encode())
        digest.update(p.read_bytes())
    result["provenance"]["source_sha256"] = digest.hexdigest()
    views, summary_rows, acf_rows, scale_rows = [], [], [], []
    leverage_rows, persistence_rows = [], []
    volume_rows, timescale_rows = [], []
    conditional_rows = []
    uncertainty_rows = []
    dependence_rows = []
    first_passage_rows = []
    long_memory_rows = []
    observation_rows = []
    assessment_rows = []
    tail_rows = []
    fano_rows, reference_rows, decay_rows = [], [], []
    for index, (asset, path, sampled, quality, metrics, acfs, diagnostics, rms, residual_arrays) in enumerate(groups):
        group_id = f"g{index:04d}"
        paths, embedded, density = _plots(sampled, metrics, acfs, diagnostics["dependence_uncertainty"], config, output_dir, group_id)
        new_paths, new_images = _tail_plot(diagnostics["tail_diagnostics"], output_dir, group_id)
        paths.update(new_paths)
        embedded.update(new_images)
        new_paths, new_images = _diagnostic_plots(sampled, diagnostics, rms, config, output_dir, group_id)
        paths.update(new_paths)
        embedded.update(new_images)
        new_paths,new_images = _first_passage_plot(diagnostics["first_passage"],config,output_dir,group_id)
        paths.update(new_paths)
        embedded.update(new_images)
        new_paths, new_images = _dependence_plots(diagnostics, config, output_dir, group_id)
        paths.update(new_paths)
        embedded.update(new_images)
        new_paths, new_images = _activity_plots(diagnostics, config, output_dir, group_id)
        paths.update(new_paths)
        embedded.update(new_images)
        new_paths, new_images = _conditional_plots(diagnostics["conditional_tails"], residual_arrays, config, output_dir, group_id)
        paths.update(new_paths)
        embedded.update(new_images)
        new_paths,new_images = _evidence_plots(diagnostics,config,output_dir,group_id)
        paths.update(new_paths);embedded.update(new_images)
        item = {"asset_id": asset, "path_id": path, "quality": quality, "distribution": metrics, "acf": acfs, "density": density, "figures": paths, **diagnostics}
        for row in diagnostics['intermittency']['inference']['rows']:
            fano_rows.append({'asset_id':asset,'path_id':path,**row})
        for segment in diagnostics['conditional_tails']['segments']:
            ref=segment.get('reference_test',{})
            for test in ref.get('tests',[]) or [{}]:
                reference_rows.append({'asset_id':asset,'path_id':path,'segment':segment['segment'],
                    'status':ref.get('status',segment['status']),'reason':ref.get('reason',segment.get('reason')),
                    'replications':ref.get('reps'),'failed_refits':ref.get('failed_reps'),
                    'joint_tail_p':ref.get('joint_tail_p'),'family_adjusted_tail_p':ref.get('family_adjusted_tail_p'),
                    'adequacy_p':ref.get('adequacy_p'),'tail_supported':ref.get('tail_supported'),**test})
        for row in diagnostics['volatility_persistence']['decay_comparison']['rows']:
            for kind,fit in row.get('models',{}).items() or [('unavailable',{})]:
                decay_rows.append({'asset_id':asset,'path_id':path,**{k:v for k,v in row.items() if k!='models'},
                    'model':kind,**{k:v for k,v in fit.items() if k not in ['lags','predicted','heldout_fit','status','reason']}})
        td = diagnostics["tail_diagnostics"]
        for kind in ["ccdf", "qq"]:
            for row in td[kind] or [{}]:
                tail_rows.append({"asset_id": asset, "path_id": path, "kind": kind,
                                  "n": td["n"], "status": td["status"], "reason": td["reason"], **row})
        item["findings"] = summarize(item, config, sampled)
        item["assessment"] = assess(item, config)
        for row in item["assessment"]["by_fact"].values():
            assessment_rows.append({"asset_id": asset, "path_id": path, **{
                k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v
                for k, v in row.items()}})
        for finding in item["findings"]["by_fact"].values():
            observation_rows.append({"asset_id": asset, "path_id": path, **finding,
                                     "references": json.dumps(finding["references"], ensure_ascii=False)})
        result["groups"].append(item)
        memory = diagnostics["volatility_persistence"]["long_memory_test"]
        for row in memory["rows"] or [{"status":memory["status"],"reason":memory["reason"]}]:
            long_memory_rows.append({"asset_id":asset,"path_id":path,"planned_family_size":memory["planned_family_size"],
                "bandwidth_seconds":row.get("bandwidth",0)*pd.Timedelta(config.frequency).total_seconds() if config.sampling=="grid" and "bandwidth" in row else None,
                "observation_unit":config.observation_unit,**row})
        warnings = []
        if metrics["n"] < 100:
            warnings.append("有效收益少于 100 条，属于小样本。")
        if quality["missing_prices"]:
            warnings.append(f"有 {quality['missing_prices']} 个网格价格缺失：未跨缺口计算收益，也未压缩 ACF 的时间轴。")
        if quality["carried_prices"]:
            warnings.append(f"有 {quality['carried_prices']} 个价格沿用较早观测，可能增加零收益；最大沿用时长为 {config.max_staleness}。")
        if quality["duplicate_rows_last_wins"]:
            warnings.append("同时间的多条价格按 CSV 原始行顺序取最后一条。")
        views.append({**item, "images": embedded, "id": group_id, "warnings": warnings,
                      "passage_window":lag_label(config,config.first_passage_horizon),
                      "range_label": human_timestamp(quality["start"], config)+" — "+human_timestamp(quality["end"], config)})
        summary_rows.append({"asset_id": asset, "path_id": path, **quality, **{k: metrics[k] for k in ["mean", "std", "zero_fraction", "excess_kurtosis", "status", "reason"]}})
        summary_rows[-1].update(skewness=diagnostics["asymmetry"]["skewness"],
                                exceedance_fraction=diagnostics["intermittency"]["exceedance_fraction"])
        volume = diagnostics["volume_volatility"]
        for proxy, estimate in volume["correlations"].items():
            volume_rows.append({"asset_id": asset, "path_id": path, "proxy": proxy, "unit": volume["unit"], **estimate})
        if not volume["correlations"]:
            volume_rows.append({"asset_id": asset, "path_id": path, "status": volume["status"]})
        asym = diagnostics["timescale_asymmetry"]
        for row in asym["differences"]:
            timescale_rows.append({"asset_id": asset, "path_id": path, "coarse_factor": asym["factor"],
                                   "separation_seconds": row["lag"]*asym["factor"]*pd.Timedelta(config.frequency).total_seconds() if config.sampling == "grid" else None,
                                   "observation_unit": config.observation_unit, **row})
        conditional = diagnostics["conditional_tails"]
        for threshold in diagnostics["first_passage"]["thresholds"]:
            for direction in ["up","down"]:
                stats = threshold[direction]
                for row in stats["curve"]:
                    first_passage_rows.append({"asset_id":asset,"path_id":path,"direction":direction,
                        "configured_threshold":threshold["configured_threshold"],"threshold_unit":config.first_passage_unit,
                        "log_threshold":threshold["log_threshold"],"all_starts":stats["all_starts"],
                        "full_horizon_starts":stats["full_horizon_starts"],"configured_horizon":config.first_passage_horizon,
                        "elapsed_seconds":row["horizon"]*pd.Timedelta(config.frequency).total_seconds() if config.sampling=="grid" else None,
                        "observation_unit":config.observation_unit,**row})
        for row in diagnostics["dependence_uncertainty"]["rows"]:
            factor = config.coarse_factor if row["family"] == "timescale" else 1
            seconds = factor*pd.Timedelta(config.frequency).total_seconds() if config.sampling == "grid" else None
            dependence_rows.append({"asset_id":asset, "path_id":path, **row,
                                    "lag_seconds":row["lag"]*seconds if seconds is not None else None,
                                    "bandwidth_seconds":row["bandwidth"]*seconds if seconds is not None else None,
                                    "base_observations_per_slot":factor, "observation_unit":config.observation_unit})
        for block in diagnostics["uncertainty"]["blocks"]:
            for row in block["intervals"]:
                uncertainty_rows.append({"asset_id": asset, "path_id": path, "block_length": block["block_length"],
                                         "confidence_level": diagnostics["uncertainty"]["confidence_level"],
                                         "seed": block["seed"], **row})
        for row in conditional["segments"]:
            conditional_rows.append({"asset_id": asset, "path_id": path, "segment": row["segment"], "session_id": row["session_id"],
                                     "start": row["start"], "end": row["end"], "n": row["n"], "status": row["status"], "reason": row.get("reason"),
                                     "n_evaluated": row.get("n_evaluated"), "optimizer_status": row.get("optimizer_status"),
                                     "raw_excess_kurtosis": row.get("raw_distribution", {}).get("excess_kurtosis"),
                                     "residual_excess_kurtosis": row.get("residual_distribution", {}).get("excess_kurtosis"),
                                     "flags": ";".join(row.get("flags", [])), **row.get("parameters", {})})
        for row in diagnostics["aggregation"]["scales"]:
            scale_rows.append({"asset_id": asset, "path_id": path, **row,
                               "interval_seconds": pd.Timedelta(config.frequency).total_seconds()*row["factor"] if config.sampling == "grid" else None,
                               "observation_unit": config.observation_unit})
        for proxy, estimate in diagnostics["leverage"].items():
            for lag, value, count, status in zip(estimate["lags"], estimate["values"], estimate["pair_counts"], estimate["point_status"]):
                leverage_rows.append({"asset_id": asset, "path_id": path, "proxy": proxy, "lag": lag,
                                      "lag_seconds": lag*pd.Timedelta(config.frequency).total_seconds() if config.sampling == "grid" else None,
                                      "observation_unit": config.observation_unit, "correlation": value, "pair_count": count, "status": status})
        persistence = diagnostics["volatility_persistence"]
        for label, estimate in [("full", persistence["full"])] + [(f"block_{b['block']}", b["acf"]) for b in persistence["blocks"]]:
            for lag, value, count in zip(estimate["lags"], estimate["values"], estimate["pair_counts"]):
                persistence_rows.append({"asset_id": asset, "path_id": path, "period": label, "lag": lag,
                                         "lag_seconds": lag*pd.Timedelta(config.frequency).total_seconds() if config.sampling == "grid" else None,
                                         "observation_unit": config.observation_unit, "acf": value, "pair_count": count})
        for name, estimate in acfs.items():
            for lag, value, count in zip(estimate["lags"], estimate["values"], estimate["pair_counts"]):
                acf_rows.append({"asset_id": asset, "path_id": path, "series": name, "lag": lag,
                                 "lag_seconds": lag * pd.Timedelta(config.frequency).total_seconds() if config.sampling == "grid" else None,
                                 "observation_unit": config.observation_unit, "acf": value, "pair_count": count})
    # Strict JSON forbids silently writing NaN or Infinity as a statistical answer.
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    (output_dir / "results.json").write_text(serialized, encoding="utf-8")
    pd.DataFrame(assessment_rows).to_csv(output_dir / "assessment.csv", index=False)
    pd.DataFrame(fano_rows).to_csv(output_dir/'intermittency.csv',index=False)
    pd.DataFrame(reference_rows).to_csv(output_dir/'conditional_inference.csv',index=False)
    pd.DataFrame(decay_rows).to_csv(output_dir/'decay_models.csv',index=False)
    pd.DataFrame(summary_rows).to_csv(output_dir / "summary.csv", index=False)
    pd.DataFrame(tail_rows).to_csv(output_dir / "tail_diagnostics.csv", index=False)
    pd.DataFrame(observation_rows, columns=["asset_id", "path_id", "fact_id", "status", "text", "limitation", "references"]).to_csv(output_dir/"observations.csv", index=False)
    pd.DataFrame(scale_rows).to_csv(output_dir / "scales.csv", index=False)
    pd.DataFrame(volume_rows, columns=["asset_id", "path_id", "proxy", "unit", "pearson", "spearman", "pair_count", "status", "rank_status"]).to_csv(output_dir/"volume.csv", index=False)
    pd.DataFrame(timescale_rows, columns=["asset_id", "path_id", "coarse_factor", "lag", "separation_seconds", "observation_unit", "fine_leads_coarse", "coarse_leads_fine", "difference", "forward_pairs", "reverse_pairs"]).to_csv(output_dir/"timescale.csv", index=False)
    pd.DataFrame(conditional_rows, columns=["asset_id", "path_id", "segment", "session_id", "start", "end", "n", "status", "reason", "n_evaluated", "optimizer_status", "raw_excess_kurtosis", "residual_excess_kurtosis", "mu", "omega", "alpha", "beta", "persistence", "flags"]).to_csv(output_dir/"conditional.csv", index=False)
    pd.DataFrame(uncertainty_rows, columns=["asset_id", "path_id", "block_length", "metric", "estimate", "lower", "upper", "bootstrap_se", "confidence_level", "valid_reps", "seed", "status", "reason"]).to_csv(output_dir/"uncertainty.csv", index=False)
    pd.DataFrame(dependence_rows, columns=["asset_id", "path_id", "family", "proxy", "lag", "bandwidth", "lag_seconds", "bandwidth_seconds", "base_observations_per_slot", "observation_unit", "estimate", "pair_count", "standard_error", "lower", "upper", "familywise_lower", "familywise_upper", "status", "reason"]).to_csv(output_dir/"dependence_intervals.csv", index=False)
    pd.DataFrame(first_passage_rows,columns=["asset_id","path_id","direction","configured_threshold","threshold_unit","log_threshold","all_starts","full_horizon_starts","configured_horizon","horizon","elapsed_seconds","observation_unit","full_hits","full_cdf","observed_hits","early_censored","all_start_lower_bound","all_start_upper_bound"]).to_csv(output_dir/"first_passage.csv",index=False)
    pd.DataFrame(long_memory_rows,columns=["asset_id","path_id","segment","session_id","partition","window","start","end","n","bandwidth","bandwidth_seconds","observation_unit","required_n","reference_only","statistic","asymptotic_p","p_is_numerical_upper_bound","planned_family_size","family_adjusted_p","reject_short_memory_family","position","status","reason"]).to_csv(output_dir/"long_memory.csv",index=False)
    pd.DataFrame(leverage_rows, columns=["asset_id", "path_id", "proxy", "lag", "lag_seconds", "observation_unit", "correlation", "pair_count", "status"]).to_csv(output_dir / "leverage.csv", index=False)
    pd.DataFrame(persistence_rows, columns=["asset_id", "path_id", "period", "lag", "lag_seconds", "observation_unit", "acf", "pair_count"]).to_csv(output_dir / "volatility_acf.csv", index=False)
    pd.DataFrame(acf_rows, columns=["asset_id", "path_id", "series", "lag", "lag_seconds", "observation_unit", "acf", "pair_count"]).to_csv(output_dir / "acf.csv", index=False)
    env = Environment(loader=FileSystemLoader(source / "templates"), autoescape=select_autoescape(["html"]))
    env.filters["number"] = _fmt
    html = env.get_template("report.html").render(result=result, groups=views, config=config, clock_label=lag_label(config))
    # The HTML is written last, so an interrupted run cannot look complete.
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    return result
