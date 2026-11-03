from copy import deepcopy

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.statistics import distribution, three_acfs
from financial_stylized_facts.diagnostics import analyze_diagnostics
from financial_stylized_facts.dependence import dependence_diagnostics
from financial_stylized_facts.activity import activity_diagnostics
from financial_stylized_facts.conditional import conditional_diagnostics
from financial_stylized_facts.findings import summarize, extreme_concentration, at_lag, lag_label, human_timestamp


def fixture(returns, config=None):
    config = config or AnalysisConfig(frequency="1min", conditional_model="off", min_pairs=2, max_lag=5, volatility_max_lag=10)
    sampled = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(returns), freq="min", tz="UTC"),
                            "log_return": returns, "session_id": "s"})
    diagnostics, _ = analyze_diagnostics(sampled, config)
    group = {"distribution": distribution(returns), "acf": three_acfs(sampled, config.max_lag, config.min_pairs),
             "quality": {"missing_prices": 0, "carried_prices": 0}, **diagnostics,
             **dependence_diagnostics(sampled, config), **activity_diagnostics(sampled, config),
             "conditional_tails": conditional_diagnostics(sampled, config)[0]}
    return group, config, sampled


def test_extreme_share_matches_fourth_central_moment_and_is_scale_invariant():
    returns = np.r_[np.nan, np.linspace(-.01, .01, 100), -.7]
    _, _, sampled = fixture(returns)
    result = extreme_concentration(sampled)
    x = returns[np.isfinite(returns)]
    expected = (x-x.mean())**4
    assert result["fourth_moment_share"] == pytest.approx(expected.max()/expected.sum())
    assert result["timestamp"] == str(sampled.timestamp.iloc[-1])
    assert result["simple_return_percent"] == pytest.approx(100*np.expm1(-.7))
    bigger = sampled.copy()
    bigger["log_return"] *= 1e100
    other = extreme_concentration(bigger)
    assert other["fourth_moment_share"] == pytest.approx(result["fourth_moment_share"])
    assert other["timestamp"] == result["timestamp"]
    assert sampled.log_return.iloc[-1] == -.7


def test_all_fixed_facts_are_present_without_pass_fail_and_extreme_is_disclosed():
    group, config, sampled = fixture(np.r_[np.nan, np.linspace(-.01, .01, 100), -.7])
    result = summarize(group, config, sampled)
    assert set(result["by_fact"]) == {str(i) for i in range(1,12)}
    assert not result["automatic_pass_fail"]
    assert "一次变化特别敏感" in result["by_fact"]["2"]["text"]
    assert result["by_fact"]["10"]["status"] == "not_applicable"
    assert "未提供" in result["by_fact"]["10"]["text"]
    assert "关闭" in result["by_fact"]["7"]["text"]
    assert all(r["references"] and r["limitation"] for r in result["by_fact"].values())
    assert len(result["overview"]) == 3


@pytest.mark.parametrize("returns", [[np.nan], [np.nan, 0, 0, 0, 0], [np.nan, .1, -.1]])
def test_unavailable_is_not_reported_as_zero_or_success(returns):
    group, config, sampled = fixture(returns)
    result = summarize(group, config, sampled)
    assert "不可计算" in result["by_fact"]["2"]["text"]
    assert result["extreme_concentration"]["status"] == "not_computable"
    assert "None" not in " ".join(r["text"] for r in result["by_fact"].values())


def test_requested_lag_not_replaced_by_an_available_favourable_lag():
    group, config, sampled = fixture([np.nan, .1, -.2, .3, -.1])
    group["volatility_persistence"]["full"] = {"lags": [0,1,2], "values": [1,.9,.8]}
    result = summarize(group, config, sampled)
    assert "10 分钟" in result["by_fact"]["8"]["text"]
    assert result["by_fact"]["8"]["status"] == "not_computable"
    assert at_lag({"lags": [0,1,2], "values": [1,None,.9]}, 1) is None


def test_conditional_summary_compares_same_fit_window_and_does_not_assume_improvement():
    group, config, sampled = fixture(np.r_[np.nan, np.sin(np.arange(100))*.01])
    group["distribution"]["excess_kurtosis"] = 100
    group["conditional_tails"] = {"status": "partially_computed", "reason": None, "total_valid_returns": 100,
                                   "n_evaluated": 50, "segments": [
                                       {"status": "computed", "raw_distribution": {"excess_kurtosis": 4}, "residual_distribution": {"excess_kurtosis": 9}},
                                       {"status": "insufficient_data"}]}
    f = summarize(group, config, sampled)["by_fact"]["7"]
    assert "50/100" in f["text"]
    assert "原始超额峰度为 4" in f["text"] and "残差为 9" in f["text"]
    assert "升高" in f["limitation"] and f["status"] == "partially_computed"


def test_path_summaries_do_not_mutate_or_pool_other_paths():
    group, config, sampled = fixture(np.r_[np.nan, np.sin(np.arange(100))*.01])
    before = deepcopy(group)
    result = summarize(group, config, sampled)
    other, _, other_sampled = fixture(np.r_[np.nan, np.zeros(100)])
    summarize(other, config, other_sampled)
    assert summarize(group, config, sampled) == result and group == before


def test_time_labels_and_coarse_scale_are_not_confused():
    assert lag_label(AnalysisConfig(frequency="5min"), 2) == "10 分钟"
    assert lag_label(AnalysisConfig(frequency="5min"), 1, 6) == "30 分钟"
    assert lag_label(AnalysisConfig(sampling="observations", observation_unit="available-price-observation"), 2) == "2 个可用报价"
    assert lag_label(AnalysisConfig(frequency="1d"), 2) == "2 天"
    daily = AnalysisConfig(sampling="observations", observation_unit="source-date-slot")
    assert human_timestamp("2024-01-01T00:00Z", daily) == "2024-01-01"
    assert human_timestamp("2024-01-01T00:00:00.123Z", AnalysisConfig()) == "2024-01-01 00:00:00.123000 UTC"
