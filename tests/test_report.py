import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.report import analyze_csv


def write_input(tmp_path):
    rng = np.random.default_rng(2)
    frames = []
    for path, returns in [("gauss", rng.normal(0, .001, 80)), ("constant", np.zeros(80))]:
        frames.append(pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=81, freq="min", tz="UTC"),
                                    "price": 100*np.exp(np.r_[0, returns.cumsum()]), "asset_id": '<script>alert("x")</script>', "path_id": path}))
    p = tmp_path / "input.csv"
    pd.concat(frames).to_csv(p, index=False)
    return p


def test_end_to_end_reports_are_separate_and_safe(tmp_path):
    p = write_input(tmp_path)
    out = tmp_path / "report"
    result = analyze_csv(p, out, AnalysisConfig(frequency="1min", max_lag=10))
    assert len(result["groups"]) == 2
    assert [g["distribution"]["n"] for g in result["groups"]] == [80, 80]
    assert result["groups"][0]["distribution"]["status"] == "zero_variance"
    text = (out / "index.html").read_text()
    assert '<script>alert("x")</script>' not in text
    assert "&lt;script&gt;" in text
    assert text.count("data:image/png;base64,") == 18
    assert "path-select" in text and "正式统计检验仍待补齐" in text
    numerical = (out / "results.json").read_text()
    assert "NaN" not in numerical and "Infinity" not in numerical
    assert json.loads(numerical)["coverage"][6]["status"] == "descriptive_only"
    assert len(pd.read_csv(out / "summary.csv")) == 2
    observations = pd.read_csv(out/"observations.csv")
    assert len(observations) == 22
    assert observations.groupby("path_id").size().to_dict() == {"constant": 11, "gauss": 11}
    assert "这条路径先看三件事" in text
    assert all(len(g["findings"]["by_fact"]) == 11 for g in result["groups"])
    assert result["groups"][0]["findings"]["by_fact"]["2"]["status"] == "zero_variance"
    assert len(list((out / "figures").glob("*.png"))) == 18
    assert len(pd.read_csv(out / "scales.csv")) == 8
    assert result["groups"][1]["aggregation"]["scales"][1]["n"] == 16
    assert all(x["status"] == "descriptive_only" for x in result["coverage"][:6])
    assert result["coverage"][7]["status"] == "descriptive_only"
    assert result["coverage"][8]["status"] == "descriptive_only"
    assert len(pd.read_csv(out / "leverage.csv")) > 0
    assert len(pd.read_csv(out / "volatility_acf.csv")) > 0
    assert result["coverage"][9]["status"] == "descriptive_only"
    assert result["coverage"][10]["status"] == "descriptive_only"
    assert all(g["volume_volatility"]["status"] == "not_applicable" for g in result["groups"])
    assert len(pd.read_csv(out / "volume.csv")) == 2
    assert "coarse_factor" in pd.read_csv(out / "timescale.csv").columns
    with pytest.raises(FileExistsError):
        analyze_csv(p, out)


def test_empty_sampled_grid_produces_readable_insufficiency(tmp_path):
    p = tmp_path / "short.csv"
    p.write_text("timestamp,price\n2024-01-01T00:01:00Z,100\n2024-01-01T00:02:00Z,110\n")
    r = analyze_csv(p, tmp_path / "out", AnalysisConfig(frequency="5min"))
    assert r["groups"][0]["distribution"]["status"] == "insufficient_data"
    assert "没有有效收益" in (tmp_path / "out/index.html").read_text()


def test_cli_reports_invalid_data_without_traceback(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("timestamp,price\n2024-01-01,0\n")
    proc = subprocess.run([sys.executable, "-m", "financial_stylized_facts", "analyze", str(p), "--output", str(tmp_path / "report")], capture_output=True, text=True)
    assert proc.returncode == 2
    assert "无法生成报告" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert not (tmp_path / "report").exists()


def test_cli_accepts_scale_window_and_threshold_settings(tmp_path):
    p = tmp_path / "prices.csv"
    pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=61, freq="min", tz="UTC"),
                  "price": 100*np.exp(.001*np.sin(np.arange(61))), "volume": np.arange(61)}).to_csv(p, index=False)
    out = tmp_path / "cli-report"
    proc = subprocess.run([sys.executable, "-m", "financial_stylized_facts", "analyze", str(p),
                           "--output", str(out), "--frequency", "1min", "--aggregation-factors", "1", "3", "6",
                           "--rms-window", "4", "--burst-threshold", "2", "--volatility-max-lag", "40",
                           "--stability-blocks", "3", "--volume-kind", "interval", "--volume-unit", "shares",
                           "--coarse-factor", "3", "--min-pairs", "4"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    result = json.loads((out / "results.json").read_text())
    assert result["config"]["aggregation_factors"] == [1, 3, 6]
    assert [r["n"] for r in result["groups"][0]["aggregation"]["scales"]] == [60, 20, 10]
    assert result["groups"][0]["intermittency"]["window"] == 4
    assert len(result["groups"][0]["volatility_persistence"]["blocks"]) == 3
    assert result["groups"][0]["volume_volatility"]["n"] == 60
    assert result["groups"][0]["timescale_asymmetry"]["status"] == "computed"
    assert (out/"index.html").read_text().count("data:image/png;base64,") == 10
    assert pd.read_csv(out/"timescale.csv").separation_seconds.iloc[0] == 180


def test_conditional_report_exports_aligned_residuals(tmp_path):
    p = tmp_path/"garch-input.csv"
    rng = np.random.default_rng(33)
    returns = rng.normal(0, .001, 700)
    pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=701, freq="min", tz="UTC"),
                  "price": 100*np.exp(np.r_[0, returns.cumsum()])}).to_csv(p, index=False)
    out = tmp_path/"garch-report"
    result = analyze_csv(p, out, AnalysisConfig(frequency="1min"))
    conditional = result["groups"][0]["conditional_tails"]
    assert conditional["status"] == "computed"
    segment = conditional["segments"][0]
    residuals = pd.read_csv(out/segment["residual_file"])
    assert len(residuals) == 650
    np.testing.assert_allclose(residuals.standardized_residual,
                               (residuals.log_return-residuals.fitted_mean)/residuals.conditional_volatility, atol=1e-10)
    assert pd.Timestamp(residuals.timestamp.iloc[0]) == pd.Timestamp("2024-01-01T00:51Z")
    assert (out/segment["figure"]).exists()
    assert pd.read_csv(out/"conditional.csv").n_evaluated.iloc[0] == 650
    intervals = pd.read_csv(out/"uncertainty.csv")
    assert "excess_kurtosis" in set(intervals.metric)
    assert set(intervals.block_length) == {10, 20}
    assert result["groups"][0]["distribution"]["uncertainty"]["reference"] == "group.uncertainty"
    assert result["groups"][0]["asymmetry"]["uncertainty"]["metrics"] == ["skewness"]
    text = (out/"index.html").read_text()
    assert "连续段 1" in text
    assert text.count("data:image/png;base64,") == 10
