import numpy as np
import pandas as pd
import pytest
from scipy import stats

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.diagnostics import (
    asymmetry, signed_runs, aggregate_returns, scale_diagnostics,
    rolling_rms, intermittency, analyze_diagnostics,
)


def test_asymmetry_hand_case_and_quote_inversion():
    r = asymmetry([[0, 0, 0, 4]])
    assert r["skewness"] == pytest.approx(2.)
    assert r["quantiles"]["0.95"] == pytest.approx(3.4)
    assert r["tails"][0]["right_probability"] == .25
    x = np.random.default_rng(91).exponential(size=300)-1
    a, b = asymmetry([x]), asymmetry([-x])
    assert a["skewness"] == pytest.approx(stats.skew(x, bias=False))
    assert b["skewness"] == pytest.approx(-a["skewness"])
    for left, right in zip(a["tails"], b["tails"]):
        assert left["left_count"] == right["right_count"]


def test_signed_runs_break_on_zero_gap_and_sessions():
    runs = signed_runs([[0, .1, .2, -.1, 0, -.2, np.nan, .3], [-.2, -.1, 0]])
    assert [r["length"] for r in runs] == [2, 1, 1, 1, 2]
    assert [r["log_return"] for r in runs] == pytest.approx([.3, -.1, -.2, .3, -.3])
    assert runs[0]["left_censored"] == runs[0]["right_censored"] == False
    assert runs[2]["right_censored"]
    assert runs[3]["left_censored"] and runs[3]["right_censored"]
    assert runs[4]["left_censored"] and not runs[4]["right_censored"]
    result = asymmetry([[0, .1, .2, -.1, 0, -.2, np.nan, .3], [-.2, -.1, 0]])
    assert result["runs"]["up"]["complete_count"] == 1
    assert result["runs"]["up"]["median_abs_log_return"] == pytest.approx(.3)
    assert result["runs"]["down"]["complete_count"] == 1


def test_aggregation_keeps_block_alignment_and_rejects_gaps():
    values, meta = aggregate_returns([[1, 2, np.nan, 4, 5, 6, 7], [10, 20, 30]], 2)
    np.testing.assert_allclose(values[0], [3, np.nan, 11], equal_nan=True)
    np.testing.assert_allclose(values[1], [30])
    assert meta == {"total_blocks": 4, "invalid_blocks": 1, "discarded_partial_slots": 2}


def test_scale_sums_match_price_endpoint_returns():
    returns = np.array([.01, -.02, .04, -.01, .03, -.02])
    log_prices = np.r_[np.log(100), np.log(100)+returns.cumsum()]
    aggregate, _ = aggregate_returns([returns], 2)
    np.testing.assert_allclose(aggregate[0], np.diff(log_prices[::2]), atol=1e-14)
    sampled = pd.DataFrame({"session_id": "one", "log_return": np.r_[np.nan, returns]})
    result, _ = analyze_diagnostics(sampled, AnalysisConfig(aggregation_factors=(1, 2)))
    assert result["aggregation"]["scales"][1]["n"] == 3
    # Removing every NaN would shift later blocks; only structural first NaN is removed.
    sampled.loc[2, "log_return"] = np.nan
    result, _ = analyze_diagnostics(sampled, AnalysisConfig(aggregation_factors=(1, 2)))
    assert result["aggregation"]["scales"][1]["invalid_blocks"] == 1
    assert result["aggregation"]["scales"][1]["n"] == 2


def test_rms_hand_values_and_missing_windows():
    values = rolling_rms([[3, 4, np.nan, 0, 0, 6], [8, 6]], 2)
    np.testing.assert_allclose(values[0], [np.nan, np.sqrt(12.5), np.nan, np.nan, 0, np.sqrt(18)], equal_nan=True)
    np.testing.assert_allclose(values[1], [np.nan, np.sqrt(50)], equal_nan=True)


def test_bursts_count_episodes_not_just_large_observations():
    a = [0.]*30 + [10., 10., 0., 10., np.nan, 10.] + [0.]*30
    result, _ = intermittency([a], 3, 2)
    assert result["exceedance_count"] == 4
    assert result["episodes"]["observed_count"] == 3
    assert result["episodes"]["max_observed_length"] == 2
    assert result["episodes"]["boundary_censored_count"] == 2
    assert result["episodes"]["mean_complete_length"] == 2


def test_iid_laplace_aggregation_approaches_gaussian_in_moments():
    x = np.random.default_rng(219).laplace(size=160000)
    result = scale_diagnostics([x], (1, 5, 20))
    first, _, last = result["scales"]
    assert first["excess_kurtosis"] == pytest.approx(3., abs=.3)
    assert abs(last["excess_kurtosis"]) < .5
    assert last["normal_quantile_rmse"] < first["normal_quantile_rmse"]
    assert last["n"] == 8000


@pytest.mark.parametrize("factor", [1e-100, 1e100])
def test_new_metrics_have_expected_scale_invariance(factor):
    x = np.array([0., .1, -.3, .4, .2, 0., -.1]*20)
    assert asymmetry([x*factor])["skewness"] == pytest.approx(asymmetry([x])["skewness"])
    a = scale_diagnostics([x], (1, 5))["scales"]
    b = scale_diagnostics([x*factor], (1, 5))["scales"]
    for v, w in zip(a, b):
        assert v["normal_quantile_rmse"] == pytest.approx(w["normal_quantile_rmse"])
    np.testing.assert_allclose(rolling_rms([x*factor], 5)[0]/factor, rolling_rms([x], 5)[0], equal_nan=True)


def test_new_metrics_handle_constant_missing_and_short_series():
    assert asymmetry([[1, 1, 1]])["status"] == "zero_variance"
    assert asymmetry([[np.nan]])["skewness"] is None
    assert scale_diagnostics([[1, 2]], (1, 5))["scales"][1]["n"] == 0
    assert intermittency([[0, 0, 0]])[0]["status"] == "zero_variance"
    assert intermittency([])[0]["status"] == "insufficient_data"
    with pytest.raises(ValueError):
        asymmetry([[1, np.inf]])


@pytest.mark.parametrize("kwargs", [
    {"aggregation_factors": (5, 1)}, {"aggregation_factors": (1, 1)},
    {"aggregation_factors": ()}, {"aggregation_factors": (1, 2.5)},
    {"rms_window": 1}, {"rms_window": 2.5}, {"burst_threshold": float("nan")},
    {"max_lag": 1.5},
])
def test_invalid_diagnostic_config_is_rejected(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs).validate()
