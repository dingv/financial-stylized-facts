import numpy as np
import pandas as pd
import pytest
from scipy.stats import pearsonr

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.dependence import lagged_volatility_correlation, dependence_diagnostics


def direct_pairs(segments, lag, proxy):
    xs, ys = [], []
    for a in segments:
        for t in range(len(a)):
            if 0 <= t+lag < len(a) and np.isfinite(a[t]) and np.isfinite(a[t+lag]):
                xs.append(a[t])
                ys.append(abs(a[t+lag]) if proxy == "absolute" else a[t+lag]**2)
    return np.array(xs), np.array(ys)


@pytest.mark.parametrize("proxy", ["absolute", "squared"])
def test_fft_pairwise_moments_agree_with_direct_scipy(proxy):
    rng = np.random.default_rng(71)
    arrays = [rng.normal(size=71), rng.normal(size=53)]
    arrays[0][[0, 8, 19, 70]] = np.nan
    result = lagged_volatility_correlation(arrays, 8, 3, proxy)
    for lag, estimate, count in zip(result["lags"], result["values"], result["pair_counts"]):
        x, y = direct_pairs(arrays, lag, proxy)
        assert count == len(x)
        assert estimate == pytest.approx(pearsonr(x, y).statistic, abs=1e-12)


def test_lag_orientation_by_hand_and_session_edges():
    arrays = [np.array([-2., 1., 3., -1.]), np.array([1., -3., 2.])]
    result = lagged_volatility_correlation(arrays, 1, 2, "squared")
    assert result["pair_counts"] == [5, 7, 5]
    # k=+1 pairs r[t] with r[t+1]^2; no end-of-session to next start pair.
    assert result["values"][2] == pytest.approx(pearsonr([-2, 1, 3, 1, -3], [1, 9, 1, 9, 4]).statistic)
    assert result["values"][0] == pytest.approx(pearsonr([1, 3, -1, -3, 2], [4, 1, 9, 1, 9]).statistic)


def test_quote_inversion_and_time_reversal():
    x = np.random.default_rng(11).normal(size=200)
    a = lagged_volatility_correlation([x], 5, 2)
    b = lagged_volatility_correlation([-x], 5, 2)
    c = lagged_volatility_correlation([x[::-1]], 5, 2)
    np.testing.assert_allclose(b["values"], -np.array(a["values"]), atol=1e-12)
    np.testing.assert_allclose(c["values"], a["values"][::-1], atol=1e-12)


@pytest.mark.parametrize("scale", [1e-150, 1e150])
def test_leverage_scale_invariance_without_squared_overflow(scale):
    x = np.random.default_rng(13).normal(size=200)
    a = lagged_volatility_correlation([x], 4, 2)
    b = lagged_volatility_correlation([x*scale], 4, 2)
    np.testing.assert_allclose(a["values"], b["values"], atol=1e-12)


def test_symmetric_iid_has_no_directional_leverage():
    x = np.random.default_rng(18).normal(size=30000)
    result = lagged_volatility_correlation([x], 5)
    assert max(abs(v) for v in result["values"]) < .03


def test_known_forward_volatility_response_is_not_reversed():
    shocks = np.random.default_rng(42).normal(size=30001)
    x = shocks[1:]*(1-.5*np.tanh(shocks[:-1]))
    result = lagged_volatility_correlation([x], 3)
    values = dict(zip(result["lags"], result["values"]))
    assert values[1] < -.12
    assert abs(values[-1]) < .03


def test_missing_short_constant_and_pairwise_zero_variance():
    assert lagged_volatility_correlation([])["status"] == "insufficient_data"
    assert lagged_volatility_correlation([[1]*30])["status"] == "zero_variance"
    assert lagged_volatility_correlation([[-1, 1]*20])["status"] == "zero_variance"
    result = lagged_volatility_correlation([[1., 2., np.nan, 3.]], 2, 3)
    assert result["values"] == [None, None, result["values"][2], None, None]
    assert result["pair_counts"] == [1, 1, 3, 1, 1]
    with pytest.raises(ValueError):
        lagged_volatility_correlation([[1, np.inf]])
    # At k=1 only constant x/y pairs survive, despite nonconstant full data.
    result = lagged_volatility_correlation([[1., 2.], [1., 2.], [1., 2.]], 1, 2)
    assert result["values"][0] is None and result["values"][2] is None


def frame_from_returns(x):
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(x), freq="min", tz="UTC"),
                         "log_return": x, "session_id": "continuous"})


def test_regime_mixture_does_not_automatically_become_long_memory():
    x = np.random.default_rng(817).normal(size=16000)*np.repeat([1., 5., 1., 5.], 4000)
    result = dependence_diagnostics(frame_from_returns(x), AnalysisConfig(volatility_max_lag=100, stability_blocks=4))
    p = result["volatility_persistence"]
    assert p["full"]["values"][100] > .2
    assert all(abs(b["acf"]["values"][100]) < .1 for b in p["blocks"])
    assert p["long_memory_test"]["status"] == "computed"
    assert p["long_memory_test"]["verified_long_memory"] is False
    assert [b["acf"]["n"] for b in p["blocks"]] == [4000]*4


def test_stability_blocks_preserve_missing_slots_and_sessions():
    frame = frame_from_returns([np.nan, 1., 2., np.nan, 2., 4., 3., 1.])
    frame["session_id"] = ["a"]*4+["b"]*4
    # Input order is not trusted for time-based diagnostic splits.
    result = dependence_diagnostics(frame.iloc[::-1], AnalysisConfig(stability_blocks=2, min_pairs=2))
    p = result["volatility_persistence"]
    assert [b["slots"] for b in p["blocks"]] == [4, 4]
    assert [b["acf"]["n"] for b in p["blocks"]] == [2, 4]
    assert p["full"]["pair_counts"][1] == 4
    assert p["blocks"][0]["acf"]["pair_counts"][1] == 1


@pytest.mark.parametrize("kwargs", [{"volatility_max_lag": 0}, {"volatility_max_lag": 2001}, {"stability_blocks": 1}, {"stability_blocks": 2.5}])
def test_invalid_dependence_config(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs).validate()
