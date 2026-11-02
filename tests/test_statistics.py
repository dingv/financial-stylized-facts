import numpy as np
import pytest
from statsmodels.tsa.stattools import acf

from financial_stylized_facts.statistics import distribution, autocorrelation


def test_three_acfs_center_each_transform_independently():
    import pandas as pd
    from financial_stylized_facts.statistics import three_acfs

    x = np.random.default_rng(73).normal(.4, 1., 200)
    result = three_acfs(pd.DataFrame({"session_id": "one", "log_return": x}), 10, 2)
    for key, values in [("return", x), ("absolute_return", abs(x)), ("squared_return", x*x)]:
        np.testing.assert_allclose(result[key]["values"], acf(values, nlags=10, fft=False), atol=1e-12)


def test_hand_moments():
    r = distribution([1, 2, 3, 4])
    assert r["excess_kurtosis"] == pytest.approx(-1.2)
    assert r["excess_kurtosis_uncorrected"] == pytest.approx(-1.36)
    assert r["pearson_kurtosis"] == pytest.approx(1.64)


def test_hand_acf_and_mature_implementation_agree():
    x = np.array([-1., 0., 1., 0.])
    actual = autocorrelation([x], 3, 2)
    np.testing.assert_allclose(actual["values"][:3], [1, 0, -.5], atol=1e-14)
    assert actual["values"][3] is None
    rng = np.random.default_rng(101)
    x = rng.normal(size=1000)
    np.testing.assert_allclose(autocorrelation([x], 20, 2)["values"], acf(x, nlags=20, fft=False), atol=1e-12)


def test_gap_is_not_removed_from_time_axis():
    r = autocorrelation([[1., np.nan, 3., 4., 2.]], 4, 2)
    assert r["pair_counts"] == [4, 2, 2, 1, 1]
    np.testing.assert_allclose(r["values"][:3], [1, 0, -.2], atol=1e-14)
    assert r["values"][3:] == [None, None]
    compressed = autocorrelation([[1., 3., 4., 2.]], 1, 2)
    assert compressed["values"][1] == pytest.approx(-.15)


def test_session_edges_are_not_correlated():
    r = autocorrelation([[-1., 1.], [-1., 1.]], 3, 2)
    assert r["pair_counts"] == [4, 2]
    assert r["values"] == pytest.approx([1, -.5])


@pytest.mark.parametrize("factor", [1e-200, 1e200, -7.])
def test_scale_invariance(factor):
    x = np.array([1., 2., 3., 4., 1., 2.])
    assert distribution(x*factor)["excess_kurtosis"] == pytest.approx(distribution(x)["excess_kurtosis"])
    np.testing.assert_allclose(autocorrelation([x*factor], 2, 2)["values"], autocorrelation([x], 2, 2)["values"], atol=1e-12)


def test_missing_constant_short_and_infinite_are_explicit():
    assert distribution([np.nan])["status"] == "insufficient_data"
    assert distribution([1, 1, 1, 1])["excess_kurtosis"] is None
    assert distribution([1, 2, 3])["status"] == "insufficient_data"
    assert autocorrelation([[0]*30])["status"] == "zero_variance"
    with pytest.raises(ValueError):
        distribution([1, np.inf])
    with pytest.raises(ValueError):
        autocorrelation([[1, np.inf]])


def test_known_gaussian_heavy_tail_and_ar1_properties():
    rng = np.random.default_rng(902)
    gaussian = rng.normal(size=40000)
    heavy = rng.standard_t(5, size=40000)
    assert abs(distribution(gaussian)["excess_kurtosis"]) < .1
    assert distribution(heavy)["excess_kurtosis"] > 2
    assert abs(autocorrelation([gaussian], 1)["values"][1]) < .03
    x = np.zeros(20000)
    noise = rng.normal(size=len(x))
    for i in range(1, len(x)):
        x[i] = .7*x[i-1] + noise[i]
    assert autocorrelation([x[1000:]], 1)["values"][1] == pytest.approx(.7, abs=.03)


def test_garch_has_volatility_dependence_without_direction_dependence():
    rng = np.random.default_rng(431)
    x = np.zeros(30000)
    variance = 1.
    for i, shock in enumerate(rng.normal(size=len(x))):
        x[i] = np.sqrt(variance)*shock
        variance = .05 + .15*x[i]**2 + .8*variance
    x = x[2000:]
    assert abs(autocorrelation([x], 1)["values"][1]) < .04
    assert autocorrelation([x*x], 1)["values"][1] > .12
