import sys

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.conditional import continuous_segments, fit_garch, conditional_diagnostics
from financial_stylized_facts.data import AnalysisConfig


def garch_returns(seed=7, n=6000, student=False):
    rng = np.random.default_rng(seed)
    shocks = rng.standard_t(5, n+1000)*np.sqrt(3/5) if student else rng.normal(size=n+1000)
    out = np.empty(n+1000)
    variance = 1.
    for i, e in enumerate(shocks):
        out[i] = np.sqrt(variance)*e
        variance = .05+.15*out[i]**2+.8*variance
    return .001*out[1000:]


def sampled(returns, sessions=None):
    return pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(returns), freq="min", tz="UTC"),
                         "log_return": returns, "session_id": sessions if sessions is not None else "s"})


def test_gaussian_garch_filter_reduces_kurtosis_and_volatility_dependence():
    result, data = fit_garch(garch_returns())
    assert result["status"] == "computed"
    assert result["optimizer_status"] == 0
    assert abs(result["residual_distribution"]["excess_kurtosis"]) < .4
    assert result["raw_distribution"]["excess_kurtosis"] > result["residual_distribution"]["excess_kurtosis"]+.3
    assert abs(result["residual_squared_acf"]["values"][1]) < .05
    assert result["raw_squared_acf"]["values"][1] > .1
    assert len(data["raw"]) == 5950


def test_student_innovation_heavy_tails_remain_after_filter():
    result, _ = fit_garch(garch_returns(seed=19, student=True))
    assert result["status"] == "computed"
    assert result["residual_distribution"]["excess_kurtosis"] > 1.


def test_residual_identity_and_garch_recursion_in_original_units():
    r = garch_returns(n=2000)
    result, data = fit_garch(r, burn=50)
    p = result["parameters"]
    np.testing.assert_allclose(data["standardized_residual"],
                               (r[50:]-p["mu"])/data["conditional_volatility"], rtol=1e-10)
    variance = data["conditional_volatility"]**2
    expected = p["omega"]+p["alpha"]*(r[50:-1]-p["mu"])**2+p["beta"]*variance[:-1]
    np.testing.assert_allclose(variance[1:], expected, rtol=1e-9)


def test_units_and_mean_shift_preserve_standardized_residuals():
    r = garch_returns(n=2000)
    a, x = fit_garch(r)
    b, y = fit_garch(100*r+.2)
    np.testing.assert_allclose(x["standardized_residual"], y["standardized_residual"], atol=2e-5)
    assert b["parameters"]["mu"] == pytest.approx(100*a["parameters"]["mu"]+.2, abs=1e-6)
    assert b["parameters"]["omega"] == pytest.approx(a["parameters"]["omega"]*10000, rel=1e-4)


def test_nonconvergence_does_not_produce_residual_claims():
    result, data = fit_garch(garch_returns(n=1000), max_iter=1)
    assert result["status"] == "fit_failed"
    assert result["optimizer_status"] != 0
    assert data is None
    assert "residual_distribution" not in result


def test_constant_returns_not_fitted():
    result, data = fit_garch(np.zeros(1000))
    assert result["status"] == "zero_variance"
    assert data is None


def test_segments_split_at_every_gap_and_session():
    s = sampled([np.nan, .1, .2, np.nan, .3, .4, .5, .6], ["a"]*6+["b"]*2)
    chunks = list(continuous_segments(s))
    assert [key for key, _ in chunks] == ["a", "a", "b"]
    assert [list(frame.log_return) for _, frame in chunks] == [[.1, .2], [.3, .4], [.5, .6]]


def test_resource_limits_skip_whole_segments_and_keep_coverage():
    r = garch_returns(n=1800)
    s = sampled(np.r_[np.nan, r[:600], np.nan, r[600:1200], np.nan, r[1200:]])
    config = AnalysisConfig(garch_max_segments=1, garch_max_points=1000)
    result, data = conditional_diagnostics(s, config)
    assert [x["status"] for x in result["segments"]] == ["computed", "resource_limit", "resource_limit"]
    assert result["status"] == "partially_computed"
    assert result["attempted_points"] == 600
    assert result["n_evaluated"] == 550
    assert result["evaluated_fraction"] == pytest.approx(550/1800)
    assert len(data) == 1
    oversized, _ = conditional_diagnostics(sampled(r), AnalysisConfig(garch_max_points=1000))
    assert oversized["attempted_points"] == 0
    assert oversized["segments"][0]["status"] == "resource_limit"


def test_short_missing_dependency_and_disabled_are_explicit(monkeypatch):
    s = sampled(np.r_[np.nan, np.arange(10)/100])
    short, _ = conditional_diagnostics(s, AnalysisConfig())
    assert short["segments"][0]["status"] == "insufficient_data"
    assert short["status"] == "not_computable"
    monkeypatch.setitem(sys.modules, "arch", None)
    missing, _ = conditional_diagnostics(s, AnalysisConfig())
    assert missing["status"] == "dependency_missing"
    off, _ = conditional_diagnostics(s, AnalysisConfig(conditional_model="off"))
    assert off["status"] == "disabled"


def test_fit_error_is_reported_and_does_not_crash_other_diagnostics(monkeypatch):
    def fail(*a, **kw):
        raise ValueError("deliberate invalid optimizer input")
    monkeypatch.setattr("financial_stylized_facts.conditional.fit_garch", fail)
    result, data = conditional_diagnostics(sampled(garch_returns(n=600)), AnalysisConfig())
    assert result["segments"][0]["status"] == "fit_failed"
    assert "deliberate" in result["segments"][0]["reason"]
    assert data == []


@pytest.mark.parametrize("kwargs", [{"conditional_model":"x"}, {"garch_min_points":99},
                                   {"garch_max_points":499}, {"garch_max_segments":0},
                                   {"garch_max_iter":0}, {"garch_burn":-1}, {"garch_burn":499}])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs).validate()
