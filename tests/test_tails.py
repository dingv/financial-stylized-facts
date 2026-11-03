import numpy as np
import pytest
from scipy.stats import norm
from financial_stylized_facts.tails import tail_diagnostics


def test_tied_values_strict_exceedance_and_hand_computed_qq():
    result = tail_diagnostics([-1, -1, 1, 1, np.nan])
    assert result["n"] == 4
    counts = {row["threshold_sigma"]: row["count"] for row in result["ccdf"]}
    assert counts[0] == 4 and counts[1] == 0 and counts[.5] == 4
    np.testing.assert_allclose([r["sample_quantile"] for r in result["qq"]], [-1, -1, 1, 1])
    np.testing.assert_allclose([r["normal_quantile"] for r in result["qq"]], norm.ppf([.125, .375, .625, .875]))


def test_direct_tail_count_and_shift_scale_invariance():
    x = np.random.default_rng(26).standard_t(5, 5001)
    result = tail_diagnostics(x)
    shifted = tail_diagnostics(50 + 2*x)
    z = (x-x.mean())/x.std(ddof=0)
    for row in result["ccdf"]:
        # The added maximum is exactly zero by construction; use fixed grid for independent counts.
        if row["threshold_sigma"] <= 6:
            assert row["count"] == np.count_nonzero(np.abs(z) > row["threshold_sigma"])
    assert len(result["qq"]) == 2000
    assert [result["qq"][0]["rank"], result["qq"][-1]["rank"]] == [1, 5001]
    np.testing.assert_allclose([r["sample_quantile"] for r in result["qq"]],
                               [r["sample_quantile"] for r in shifted["qq"]], atol=1e-13)
    assert min(r["count"] for r in result["ccdf"]) == 0


@pytest.mark.parametrize("values,status", [([], "insufficient_data"), ([1,2,3], "insufficient_data"), ([1]*4,"zero_variance")])
def test_unavailable_does_not_invent_zero_curve(values, status):
    result = tail_diagnostics(values)
    assert result["status"] == status and result["reason"]
    assert not result["ccdf"] and not result["qq"]


def test_infinity_rejected():
    with pytest.raises(ValueError, match="Infinity"):
        tail_diagnostics([1,2,3,np.inf])
