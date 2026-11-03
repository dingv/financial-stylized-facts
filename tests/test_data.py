from dataclasses import replace
import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.data import AnalysisConfig, read_prices, sample_path


def load(tmp_path, rows, config=None):
    p = tmp_path / "input.csv"
    pd.DataFrame(rows).to_csv(p, index=False)
    return read_prices(p, config or AnalysisConfig())


def test_hand_computed_nonoverlapping_returns(tmp_path):
    c = AnalysisConfig(frequency="1min")
    f = load(tmp_path, {"timestamp": ["2024-01-01T00:00Z", "2024-01-01T00:01Z", "2024-01-01T00:02Z"], "price": [100, 110, 99]}, c)
    sampled, meta = sample_path(f, c)
    np.testing.assert_allclose(sampled.log_return.iloc[1:], np.log([1.1, .9]))
    assert meta["valid_returns"] == 2


def test_asof_never_uses_future_and_tolerance_expires(tmp_path):
    c = AnalysisConfig(frequency="1min", max_staleness="30s")
    f = load(tmp_path, {"timestamp": ["2024-01-01T00:00:00Z", "2024-01-01T00:00:59Z", "2024-01-01T00:02:01Z", "2024-01-01T00:03:00Z"], "price": [100, 110, 999, 120]}, c)
    s, m = sample_path(f, c)
    np.testing.assert_allclose(s.price, [100, 110, np.nan, 120], equal_nan=True)
    assert np.isnan(s.log_return.iloc[3])
    assert m["carried_prices"] == 1
    assert m["missing_prices"] == 1


def test_session_boundaries_do_not_produce_overnight_returns(tmp_path):
    c = AnalysisConfig(frequency="1h")
    f = load(tmp_path, {"timestamp": ["2024-01-01T23:00Z", "2024-01-02T00:00Z", "2024-01-02T01:00Z"], "price": [100, 900, 990]}, c)
    s, m = sample_path(f, c)
    assert s.log_return.isna().sum() == 2
    assert m["sessions"] == 2
    assert s.log_return.dropna().iloc[0] == pytest.approx(np.log(1.1))


def test_explicit_sessions_override_date(tmp_path):
    c = AnalysisConfig(frequency="1h")
    f = load(tmp_path, {"timestamp": ["2024-01-01T23:00Z", "2024-01-02T00:00Z"], "price": [100, 110], "session_id": ["simulation"]*2}, c)
    s, m = sample_path(f, c)
    assert m["valid_returns"] == 1


def test_duplicate_price_uses_stable_last_input_row(tmp_path):
    c = AnalysisConfig(frequency="1min")
    f = load(tmp_path, {"timestamp": ["2024-01-01T00:01Z", "2024-01-01T00:00Z", "2024-01-01T00:01Z"], "price": [110, 100, 120], "asset_id": ["001"]*3}, c)
    s, m = sample_path(f, c)
    assert s.price.tolist() == [100, 120]
    assert m["duplicate_rows_last_wins"] == 1
    assert f.asset_id.unique().tolist() == ["001"]


@pytest.mark.parametrize("price", [0, -1, np.inf, np.nan, "oops"])
def test_rejects_invalid_prices(tmp_path, price):
    with pytest.raises(ValueError, match="price"):
        load(tmp_path, {"timestamp": ["2024-01-01T00:00Z"], "price": [price]})


def test_requires_explicit_timezone_and_rejects_dst_ambiguity(tmp_path):
    rows = {"timestamp": ["2024-11-03 01:30:00"], "price": [100]}
    with pytest.raises(ValueError, match="时区"):
        load(tmp_path, rows)
    with pytest.raises(ValueError, match="timestamp"):
        load(tmp_path, rows, AnalysisConfig(timezone="America/New_York"))
    f = load(tmp_path, rows, AnalysisConfig(timezone="Asia/Shanghai"))
    assert str(f.timestamp.iloc[0]) == "2024-11-02 17:30:00+00:00"


def test_observations_requires_unit_and_does_not_invent_weekend(tmp_path):
    with pytest.raises(ValueError, match="observation_unit"):
        AnalysisConfig(sampling="observations").validate()
    c = AnalysisConfig(sampling="observations", observation_unit="trading-day")
    f = load(tmp_path, {"timestamp": ["2024-01-05T16:00Z", "2024-01-08T16:00Z"], "price": [100, 110]}, c)
    s, _ = sample_path(f, c)
    assert len(s) == 2
    assert s.log_return.iloc[1] == pytest.approx(np.log(1.1))
    with pytest.raises(ValueError, match="重复"):
        sample_path(pd.concat([f, f]), c)


def test_grid_limit_and_asset_separation(tmp_path):
    c = AnalysisConfig(frequency="1s", max_grid_points=10)
    f = load(tmp_path, {"timestamp": ["2024-01-01T00:00Z", "2024-01-01T00:01Z"], "price": [100, 110]}, c)
    with pytest.raises(ValueError, match="max_grid_points"):
        sample_path(f, c)
    f.loc[0, "asset_id"] = "other"
    with pytest.raises(ValueError, match="一条路径"):
        sample_path(f, c)


def test_no_future_grid_extension_for_short_session(tmp_path):
    c = AnalysisConfig(frequency="5min", max_staleness="5min")
    f = load(tmp_path, {"timestamp": ["2024-01-01T00:01Z", "2024-01-01T00:02Z"], "price": [100, 110]}, c)
    s, m = sample_path(f, c)
    assert s.empty and m["valid_returns"] == 0


def test_explicit_missing_price_blocks_returns_without_compressing_clock(tmp_path):
    c = AnalysisConfig(frequency="1min", allow_missing_prices=True, max_staleness="30s")
    f = load(tmp_path, {"timestamp": ["2024-01-01T00:00Z", "2024-01-01T00:00:59Z", "2024-01-01T00:02Z", "2024-01-01T00:03Z"],
                        "price": [100, "", 120, 132]}, c)
    s, m = sample_path(f, c)
    np.testing.assert_allclose(s.price, [100, np.nan, 120, 132], equal_nan=True)
    assert s.log_return.isna().sum() == 3 and m["carried_prices"] == 0
    assert s.log_return.iloc[-1] == pytest.approx(np.log(1.1))
    for bad in [0, -1, np.inf, "oops", "NaN"]:
        with pytest.raises(ValueError):
            load(tmp_path, {"timestamp": ["2024-01-01T00:00Z"], "price": [bad]}, c)
