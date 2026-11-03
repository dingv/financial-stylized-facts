from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from arch.bootstrap import CircularBlockBootstrap
from scipy import stats

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.uncertainty import circular_indices, marginal_statistics, uncertainty_diagnostics


def sample(r, volume=None):
    frame = pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(r), freq="min", tz="UTC"),
                          "log_return": r, "session_id": "continuous"})
    if volume is not None:
        frame["volume"] = volume
    return frame


def metric(result, name, block_index=0):
    return next(r for r in result["blocks"][block_index]["intervals"] if r["metric"] == name)


def test_moment_and_volume_estimates_match_scipy_with_missing_volume():
    r = np.random.default_rng(41).standard_t(7, 1000)
    v = np.abs(r)+np.random.default_rng(42).uniform(size=1000)
    v[5::13] = np.nan
    out = marginal_statistics(r, v)
    z = (r-r.mean())/r.std()
    expected = [r.mean(), r.std(), stats.skew(r, bias=False), stats.kurtosis(r, bias=False),
                np.mean(abs(z)>3), np.mean(r==0)]
    np.testing.assert_allclose(out[:6], expected, atol=1e-12)
    valid = np.isfinite(v)
    assert out[6] == pytest.approx(stats.pearsonr(v[valid], abs(r[valid])).statistic)
    assert out[7] == pytest.approx(stats.spearmanr(v[valid], abs(r[valid])).statistic)
    assert out[8] == pytest.approx(stats.pearsonr(v[valid], r[valid]**2).statistic)
    constant_volume = marginal_statistics(r, np.ones(len(r)))
    assert np.isnan(constant_volume[6:]).all()


def test_circular_indices_equal_arch_and_never_leave_segment():
    seed, n, length = 918, 103, 13
    rng = np.random.default_rng(seed)
    library = CircularBlockBootstrap(length, np.arange(n), seed=seed)
    for (positional, _) in library.bootstrap(5):
        ix = circular_indices(n, length, rng)
        np.testing.assert_array_equal(ix, positional[0])
        assert ix.min() >= 0 and ix.max() < n and len(ix) == n
        for start in range(0, n, length):
            assert np.all(np.diff(ix[start:start+length]) % n == 1)


def test_percentile_intervals_match_arch_reference_exactly():
    r = np.random.default_rng(42).normal(size=1000)
    config = AnalysisConfig(bootstrap_reps=200, bootstrap_block_lengths=(20,))
    result = uncertainty_diagnostics(sample(r), config)
    seed = result["blocks"][0]["seed"]
    bs = CircularBlockBootstrap(20, r, seed=seed)
    def estimates(x):
        return np.array([x.mean(), x.std(), stats.skew(x, bias=False), stats.kurtosis(x, bias=False)])
    expected = bs.conf_int(estimates, reps=200, method="percentile", size=.95)
    actual = np.array([[metric(result, name)[bound] for name in ["mean", "std", "skewness", "excess_kurtosis"]]
                       for bound in ["lower", "upper"]])
    np.testing.assert_allclose(actual, expected, atol=1e-12)


def test_iid_mean_standard_error_near_analytical_value():
    r = np.random.default_rng(11).normal(size=2500)
    result = uncertainty_diagnostics(sample(r), AnalysisConfig(bootstrap_block_lengths=(10,)))
    se = metric(result, "mean")["bootstrap_se"]
    assert .7/np.sqrt(len(r)) < se < 1.3/np.sqrt(len(r))


def test_serial_dependence_changes_mean_uncertainty_and_block_sensitivity():
    innovations = np.random.default_rng(56).normal(size=3500)
    r = np.empty_like(innovations)
    r[0] = innovations[0]
    for i in range(1, len(r)):
        r[i] = .8*r[i-1]+innovations[i]
    r = r[500:]
    result = uncertainty_diagnostics(sample(r), AnalysisConfig(bootstrap_block_lengths=(5, 50)))
    short = metric(result, "mean", 0)["bootstrap_se"]
    long = metric(result, "mean", 1)["bootstrap_se"]
    assert long > 1.25*short
    assert long > 1.5*r.std()/np.sqrt(len(r))
    assert .5*5/np.sqrt(len(r)) < long < 1.5*5/np.sqrt(len(r))


def test_seed_independence_from_path_and_block_order():
    r = np.random.default_rng(32).normal(size=1000)
    config = AnalysisConfig(bootstrap_reps=200, bootstrap_block_lengths=(10, 20))
    first = uncertainty_diagnostics(sample(r), config, "asset/a")
    repeat = uncertainty_diagnostics(sample(r), config, "asset/a")
    alone = uncertainty_diagnostics(sample(r), replace(config, bootstrap_block_lengths=(20,)), "asset/a")
    other = uncertainty_diagnostics(sample(r), config, "asset/b")
    assert first == repeat
    assert first["blocks"][1] == alone["blocks"][0]
    assert first["blocks"][0]["seed"] != other["blocks"][0]["seed"]


def test_gaps_and_sessions_keep_segment_sizes_and_never_drop_short_segments():
    r = np.random.default_rng(13).normal(size=600)
    frame = sample(np.r_[r[:300], np.nan, r[300:]])
    frame.loc[451:, "session_id"] = "second"
    result = uncertainty_diagnostics(frame, AnalysisConfig(bootstrap_reps=200, bootstrap_block_lengths=(10, 100)))
    assert result["segment_lengths"] == [300, 150, 150]
    assert result["n"] == 600
    assert result["status"] == "partially_computed"
    assert result["blocks"][1]["status"] == "insufficient_data"
    assert metric(result, "mean")["estimate"] == pytest.approx(r.mean())


def test_resource_limits_missing_and_degenerate_statistics_are_explicit():
    config = AnalysisConfig(bootstrap_reps=200, bootstrap_block_lengths=(10,))
    r = np.random.default_rng(3).normal(size=500)
    limited = uncertainty_diagnostics(sample(r), replace(config, bootstrap_max_work=100))
    assert limited["status"] == "resource_limit"
    assert not limited["blocks"]
    assert uncertainty_diagnostics(sample(r[:100]), config)["status"] == "insufficient_data"
    assert uncertainty_diagnostics(sample(r*0), config)["status"] == "zero_variance"
    assert uncertainty_diagnostics(sample(r), replace(config, bootstrap_reps=0))["status"] == "disabled"
    result = uncertainty_diagnostics(sample(r), config)
    assert metric(result, "zero_fraction")["status"] == "degenerate"
    assert metric(result, "zero_fraction")["upper"] is None


@pytest.mark.parametrize("kwargs", [{"bootstrap_reps":1}, {"bootstrap_reps":True}, {"bootstrap_seed":-1},
                                   {"bootstrap_block_lengths":(1,)}, {"bootstrap_block_lengths":(20,10)},
                                   {"bootstrap_block_lengths":()}, {"bootstrap_max_work":0}])
def test_invalid_bootstrap_configuration(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs).validate()
