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


def _plots(sampled, metrics, acfs, config, directory, group_id):
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


def analyze_csv(input_path, output_dir, config=None, title="金融市场 · 基础统计诊断"):
    """Analyze canonical price CSV, writing a new output directory only.

    Returns are non-overlapping. No model simulation or market download occurs.
    """
    config = config or AnalysisConfig()
    input_path, output_dir = Path(input_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("输出目录已存在；请选一个新目录，避免覆盖已有报告")
    raw = input_path.read_bytes()
    input_hash = hashlib.sha256(raw).hexdigest()
    prices = read_prices(BytesIO(raw), config)
    groups = []
    for (asset, path), frame in prices.groupby(["asset_id", "path_id"], sort=True):
        sampled, quality = sample_path(frame, config)
        metrics = distribution(sampled["log_return"])
        acfs = three_acfs(sampled, config.max_lag, config.min_pairs)
        groups.append((str(asset), str(path), sampled, quality, metrics, acfs))
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "figures").mkdir()
    result = {
        "schema_version": "0.1", "title": title, "created_at": datetime.now(timezone.utc).isoformat(),
        "config": asdict(config),
        "provenance": {"input_sha256": input_hash, "input_name": input_path.name, "input_rows": len(prices),
                       "package_version": __version__, "python": platform.python_version(),
                       "dependencies": {p: version(p) for p in ["numpy", "pandas", "scipy", "matplotlib", "jinja2"]}},
        "coverage": [{"fact_id": i, "name": name, "status": "descriptive_only" if i in [1, 2, 6] else "not_implemented"} for i, name in enumerate(FACT_NAMES, 1)],
        "groups": [],
    }
    source = Path(__file__).parent
    code_files = sorted(source.glob("*.py")) + sorted((source / "templates").glob("*.html"))
    digest = hashlib.sha256()
    for p in code_files:
        digest.update(str(p.relative_to(source)).encode())
        digest.update(p.read_bytes())
    result["provenance"]["source_sha256"] = digest.hexdigest()
    views, summary_rows, acf_rows = [], [], []
    for index, (asset, path, sampled, quality, metrics, acfs) in enumerate(groups):
        group_id = f"g{index:04d}"
        paths, embedded, density = _plots(sampled, metrics, acfs, config, output_dir, group_id)
        item = {"asset_id": asset, "path_id": path, "quality": quality, "distribution": metrics, "acf": acfs, "density": density, "figures": paths}
        result["groups"].append(item)
        warnings = []
        if metrics["n"] < 100:
            warnings.append("有效收益少于 100 条，仅作小样本描述；100 是本项目的提示阈值，不是统计保证。")
        if quality["missing_prices"]:
            warnings.append(f"有 {quality['missing_prices']} 个网格价格缺失：未跨缺口计算收益，也未压缩 ACF 的时间轴。")
        if quality["carried_prices"]:
            warnings.append(f"有 {quality['carried_prices']} 个价格沿用较早观测，可能增加零收益；最大沿用时长为 {config.max_staleness}。")
        if quality["duplicate_rows_last_wins"]:
            warnings.append("同时间的多条价格按 CSV 原始行顺序取最后一条。")
        views.append({**item, "images": embedded, "id": group_id, "warnings": warnings})
        summary_rows.append({"asset_id": asset, "path_id": path, **quality, **{k: metrics[k] for k in ["mean", "std", "zero_fraction", "excess_kurtosis", "status", "reason"]}})
        for name, estimate in acfs.items():
            for lag, value, count in zip(estimate["lags"], estimate["values"], estimate["pair_counts"]):
                acf_rows.append({"asset_id": asset, "path_id": path, "series": name, "lag": lag,
                                 "lag_seconds": lag * pd.Timedelta(config.frequency).total_seconds() if config.sampling == "grid" else None,
                                 "observation_unit": config.observation_unit, "acf": value, "pair_count": count})
    # Strict JSON forbids silently writing NaN or Infinity as a statistical answer.
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    (output_dir / "results.json").write_text(serialized, encoding="utf-8")
    pd.DataFrame(summary_rows).to_csv(output_dir / "summary.csv", index=False)
    pd.DataFrame(acf_rows, columns=["asset_id", "path_id", "series", "lag", "lag_seconds", "observation_unit", "acf", "pair_count"]).to_csv(output_dir / "acf.csv", index=False)
    env = Environment(loader=FileSystemLoader(source / "templates"), autoescape=select_autoescape(["html"]))
    env.filters["number"] = _fmt
    html = env.get_template("report.html").render(result=result, groups=views, config=config)
    # The HTML is written last, so an interrupted run cannot look complete.
    (output_dir / "index.html").write_text(html, encoding="utf-8")
    return result
