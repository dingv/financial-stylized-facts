from io import StringIO

import numpy as np
import pandas as pd
import pytest
from scipy.stats import pearsonr, spearmanr

from financial_stylized_facts.activity import coarse_fine_blocks, timescale_asymmetry, volume_diagnostics
from financial_stylized_facts.data import AnalysisConfig, read_prices, sample_path


def test_coarse_fine_hand_values_gaps_and_session_boundaries():
    pairs, quality = coarse_fine_blocks([[1., -1., 1., 1., 9.], [2., np.nan, -3., 1.]], 2)
    np.testing.assert_equal(pairs[0], ([0., 2.], [1., 1.]))
    np.testing.assert_equal(pairs[1], ([np.nan, 2.], [np.nan, 2.]))
    assert quality == {"total_blocks": 4, "invalid_blocks": 1, "discarded_return_slots": 1}


def test_timescale_matches_direct_pairs_and_time_reversal():
    rng = np.random.default_rng(51)
    segments = [rng.normal(size=300), rng.normal(size=280)]
    segments[0][23] = np.nan
    result = timescale_asymmetry(segments, 5, 8, 10)
    pairs, _ = coarse_fine_blocks(segments, 5)
    for row in result["correlations"]:
        k = row["lag"]
        collected = [(fine[t], coarse[t+k]) for coarse, fine in pairs
                     for t in range(len(fine)) if 0 <= t+k < len(coarse)
                     and np.isfinite(fine[t]) and np.isfinite(coarse[t+k])]
        x, y = np.array(collected).T
        assert row["pair_count"] == len(collected)
        assert row["correlation"] == pytest.approx(pearsonr(x, y).statistic, abs=1e-12)
    reversed_result = timescale_asymmetry([s[::-1] for s in segments], 5, 8, 10)
    np.testing.assert_allclose([d["difference"] for d in result["differences"]],
                               [-d["difference"] for d in reversed_result["differences"]], atol=1e-12)
    inverted_quote = timescale_asymmetry([-s for s in segments], 5, 8, 10)
    assert inverted_quote == result  # Absolute proxies unaffected by FX quote direction.


def test_timescale_known_coarse_leads_fine_sign():
    rng = np.random.default_rng(91)
    coarse = rng.uniform(0, 1, 1000)
    fine = np.r_[1., 1+coarse[:-1]]  # F at next block responds to prior C.
    # Two returns can realize arbitrary C<=2F: r1=F+C/2, r2=C/2-F.
    returns = np.column_stack([fine+coarse/2, coarse/2-fine]).ravel()
    result = timescale_asymmetry([returns], 2, 3, 20)
    first = result["differences"][0]
    assert first["coarse_leads_fine"] == pytest.approx(1)
    assert abs(first["fine_leads_coarse"]) < .1
    assert first["difference"] < -.9


@pytest.mark.parametrize("segments", [[], [[1.]], [[1.]*100], [[np.nan]*100]])
def test_timescale_unavailable_not_zero(segments):
    result = timescale_asymmetry(segments, 5, 4, 10)
    assert result["status"] == "not_computable"
    assert all(d["difference"] is None for d in result["differences"])


def test_volume_matches_mature_statistics_with_ties_missing_and_zero():
    frame = pd.DataFrame({"log_return": [np.nan, .1, -.2, -.3, .4, -.5, .5, .7],
                          "volume": [999., 0., 1., 1., np.nan, 3., 3., 7.]})
    config = AnalysisConfig(volume_kind="interval", volume_unit="shares", min_pairs=3)
    result = volume_diagnostics(frame, config)
    good = frame.dropna()
    assert result["n"] == 6
    assert result["status"] == "computed"
    for key, y in [("absolute", abs(good.log_return)), ("squared", good.log_return**2)]:
        assert result["correlations"][key]["pearson"] == pytest.approx(pearsonr(good.volume, y).statistic)
        assert result["correlations"][key]["spearman"] == pytest.approx(spearmanr(good.volume, y).statistic)
    assert sum(b["n"] for b in result["bins"]) == 6
    assert result["bins"][0]["volume_min"] == 0
    assert all(a["volume_max"] < b["volume_min"] for a, b in zip(result["bins"], result["bins"][1:]))


def test_volume_constant_and_missing_have_reasons():
    config = AnalysisConfig(volume_kind="interval", volume_unit="contracts", min_pairs=2)
    for volumes, status in [([0., 0., 0.], "zero_or_near_zero_pair_variance"),
                            ([np.nan]*3, "insufficient_pairs")]:
        result = volume_diagnostics(pd.DataFrame({"log_return": [.1, .2, -.3], "volume": volumes}), config)
        assert result["status"] == status
        assert result["correlations"]["absolute"]["pearson"] is None
        assert result["reason"]
    assert volume_diagnostics(pd.DataFrame(), AnalysisConfig())["status"] == "not_applicable"


def test_volume_unit_rescaling_preserves_correlations_and_finite_bins():
    config = AnalysisConfig(volume_kind="interval", volume_unit="USD", min_pairs=3)
    frame = pd.DataFrame({"log_return": [.1, -.2, .4, -.1, .7], "volume": [1., 2., 4., 1., 7.]})
    first = volume_diagnostics(frame, config)
    frame.volume *= 1e307
    changed = volume_diagnostics(frame, config)
    assert changed["correlations"]["absolute"]["pearson"] == pytest.approx(first["correlations"]["absolute"]["pearson"])
    assert changed["correlations"]["absolute"]["spearman"] == first["correlations"]["absolute"]["spearman"]
    assert all(np.isfinite(b["mean_volume"]) for b in changed["bins"])


def test_volume_alignment_does_not_carry_or_fill_zero():
    config = AnalysisConfig(frequency="1min", max_staleness="1min", volume_kind="interval", volume_unit="shares")
    csv = StringIO("timestamp,price,volume\n2024-01-01T00:00Z,100,10\n2024-01-01T00:02Z,101,0\n2024-01-01T00:03Z,102,\n")
    sampled, _ = sample_path(read_prices(csv, config), config)
    np.testing.assert_equal(sampled.volume.to_numpy(), [10., np.nan, 0., np.nan])
    assert sampled.price.iloc[1] == 100
    assert sampled.carried.iloc[1]


@pytest.mark.parametrize("kind,unit,rows", [
    ("none", None, "2024-01-01T00:00Z,100,10\n"),
    ("interval", None, "2024-01-01T00:00Z,100,10\n"),
    ("cumulative", "shares", "2024-01-01T00:00Z,100,10\n"),
    ("interval", "shares", "2024-01-01T00:00Z,100,-1\n"),
    ("interval", "shares", "2024-01-01T00:00Z,100,inf\n"),
    ("interval", "shares", "2024-01-01T00:00:30Z,100,10\n"),
    ("interval", "shares", "2024-01-01T00:00Z,100,10\n2024-01-01T00:00Z,101,20\n"),
])
def test_volume_ambiguous_or_invalid_inputs_rejected(kind, unit, rows):
    config = AnalysisConfig(frequency="1min", volume_kind=kind, volume_unit=unit)
    with pytest.raises(ValueError):
        frame = read_prices(StringIO("timestamp,price,volume\n"+rows), config)
        sample_path(frame, config)


def test_daily_observation_volume_is_attached_to_ending_day():
    config = AnalysisConfig(sampling="observations", observation_unit="trading-day", volume_kind="interval", volume_unit="shares")
    text = "timestamp,price,volume\n2024-01-05T16:00Z,100,10\n2024-01-08T16:00Z,101,20\n"
    sampled, _ = sample_path(read_prices(StringIO(text), config), config)
    assert len(sampled) == 2
    assert np.isnan(sampled.log_return.iloc[0])
    assert sampled.volume.iloc[1] == 20
    assert sampled.log_return.iloc[1] == pytest.approx(np.log(101/100))


@pytest.mark.parametrize("factor", [1, 0, True, 2.5])
def test_invalid_coarse_factor_rejected(factor):
    with pytest.raises(ValueError):
        AnalysisConfig(coarse_factor=factor).validate()
    with pytest.raises(ValueError):
        coarse_fine_blocks([[1., 2.]], factor)
