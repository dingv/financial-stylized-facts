import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.report import analyze_csv, _align_inference


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
    assert text.count("data:image/png;base64,") == 20
    assert "path-select" in text and "评估总览" in text
    numerical = (out / "results.json").read_text()
    assert "NaN" not in numerical and "Infinity" not in numerical
    assert json.loads(numerical)["coverage"][6]["status"] == "descriptive_only"
    assert result["schema_version"] == "0.14"
    assert len(pd.read_csv(out / "summary.csv")) == 2
    assessments = pd.read_csv(out / "assessment.csv", keep_default_na=False)
    assert len(assessments) == 22
    for g in result["groups"]:
        assert len(g["assessment"]["by_fact"]) == 11
        for a in g["assessment"]["by_fact"].values():
            row = assessments[(assessments.path_id == g["path_id"]) & (assessments.fact_id == a["fact_id"])].iloc[0]
            assert row.conclusion == a["conclusion"]
            assert json.loads(row.metrics) == a["metrics"]
            assert row.summary == a["summary"] and a["summary"] in text
            assert a["label"] in text
    assert all(a["conclusion"] != "supported" for a in result["groups"][0]["assessment"]["by_fact"].values())
    observations = pd.read_csv(out/"observations.csv")
    assert len(observations) == 22
    assert observations.groupby("path_id").size().to_dict() == {"constant": 11, "gauss": 11}
    assert "通用教学文档" in text
    assert all(len(g["findings"]["by_fact"]) == 11 for g in result["groups"])
    assert result["groups"][0]["findings"]["by_fact"]["2"]["status"] == "zero_variance"
    assert len(list((out / "figures").glob("*.png"))) == 22
    tail = pd.read_csv(out/"tail_diagnostics.csv")
    assert set(tail.path_id) == {"constant", "gauss"}
    assert tail[tail.path_id == "constant"].status.eq("zero_variance").all()
    assert "<details>" not in text
    assert all((out/g["figures"]["tail_diagnostics"]).exists() for g in result["groups"])
    assert len(pd.read_csv(out / "scales.csv")) == 8
    assert result["groups"][1]["aggregation"]["scales"][1]["n"] == 16
    assert all(x["status"] == "descriptive_only" for x in result["coverage"][:6])
    assert result["coverage"][7]["status"] == "descriptive_with_optional_short_memory_test"
    lm = pd.read_csv(out/"long_memory.csv")
    assert lm["statistic"].isna().all()
    assert lm["status"].eq("insufficient_data").all()
    assert "波动相关缓慢衰减" in text
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
    assert (out/"index.html").read_text().count("data:image/png;base64,") == 11
    assert pd.read_csv(out/"timescale.csv").separation_seconds.iloc[0] == 180


def test_conditional_report_exports_aligned_residuals(tmp_path):
    p = tmp_path/"garch-input.csv"
    rng = np.random.default_rng(33)
    returns = rng.normal(0, .001, 700)
    pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=701, freq="min", tz="UTC"),
                  "price": 100*np.exp(np.r_[0, returns.cumsum()])}).to_csv(p, index=False)
    out = tmp_path/"garch-report"
    result = analyze_csv(p, out, AnalysisConfig(frequency="1min", coarse_factor=2))
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
    assert text.count("data:image/png;base64,") == 11
    fp = pd.read_csv(out/"first_passage.csv")
    assert len(fp) == 120 and set(fp.direction) == {"up","down"}
    assert fp.elapsed_seconds.iloc[-1] == 1200
    assert result["groups"][0]["first_passage"]["full_horizon_starts"] == 681
    assert "达到相同涨跌幅" in text and "<details>" not in text
    dependence = pd.read_csv(out/"dependence_intervals.csv")
    assert len(dependence) == 240
    computed = dependence[dependence.status == "computed"]
    assert set(computed.family) == {"acf", "leverage", "timescale"}
    assert (computed.familywise_lower <= computed.lower).all()
    assert (computed.familywise_upper >= computed.upper).all()
    g = result["groups"][0]
    assert g["dependence_uncertainty"]["plot_bandwidth"] == 10
    for row in dependence.itertuples():
        if row.family == "acf":
            expected = g["acf"][row.proxy]["values"][row.lag]
        elif row.family == "leverage":
            est = g["leverage"][row.proxy]
            expected = est["values"][est["lags"].index(row.lag)]
        else:
            expected = g["timescale_asymmetry"]["differences"][row.lag-1]["difference"]
        assert row.estimate == pytest.approx(expected, abs=1e-12)
        assert row.lag_seconds == row.lag*(120 if row.family == "timescale" else 60)
    assert "Bonferroni" in text and "ACF 尚未提供置信区间" not in text
    assert g["leverage"]["squared"]["uncertainty"]["reference"] == "group.dependence_uncertainty"
    assert g["timescale_asymmetry"]["uncertainty"]["family"] == "timescale"


def test_inference_cannot_draw_a_band_for_an_unavailable_reported_point():
    inference = {"rows":[{"family":"acf","proxy":"return","lag":1,"estimate":.1,
                           "status":"computed","lower":0,"upper":.2}]}
    _align_inference(inference,{"return":{"lags":[1],"values":[None]}},{})
    assert inference["rows"][0]["estimate"] is None
    assert inference["rows"][0]["lower"] is None
    assert inference["status"] == "not_computable"
    inference["rows"][0]["estimate"] = .1
    with pytest.raises(ValueError,match="点估计不一致"):
        _align_inference(inference,{"return":{"lags":[1],"values":[.2]}},{})
