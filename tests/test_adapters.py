import json

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.adapters import daily_csv, fred_csv, ebs_tick_csv, write_prepared, file_sha256
from financial_stylized_facts.data import read_prices, sample_path
from financial_stylized_facts.cli import main


def test_fred_explicit_holiday_preserved_or_available_is_different_clock(tmp_path):
    source = tmp_path/"fred.csv"
    source.write_text("observation_date,DEXUSEU\n2024-01-05,1\n2024-01-08,\n2024-01-09,1.1\n2024-01-10,1.21\n")
    f, c, info = fred_csv(source, series="DEXUSEU")
    s, q = sample_path(f, c)
    assert s.log_return.isna().sum() == 3
    assert s.log_return.iloc[-1] == pytest.approx(np.log(1.1))
    assert c.allow_missing_prices and info["missing_source_prices"] == 1
    assert q["missing_prices"] == 1
    f, c, info = fred_csv(source, series="DEXUSEU", missing_policy="available")
    s, q = sample_path(f, c)
    np.testing.assert_allclose(s.log_return.iloc[1:], np.log([1.1, 1.1]))
    assert c.observation_unit == "available-price-observation"
    assert info["rows_removed"] == 1 and len(f) == 3
    assert "中午" in c.price_type


def test_fred_source_untouched_manifest_hash_and_bounds(tmp_path):
    source = tmp_path/"fred.csv"
    source.write_text("observation_date,DEXJPUS\n2024-01-04,145\n2024-01-05,146\n2024-01-08,.\n2024-01-09,147\n")
    before = source.read_bytes()
    f, c, info = fred_csv(source, series="DEXJPUS", start="2024-01-05", end="2024-01-09")
    out = tmp_path/"prepared"
    m = write_prepared(f, c, info, source=source, output=out)
    assert source.read_bytes() == before
    assert m["source_sha256"] == file_sha256(source)
    assert m["canonical_sha256"] == file_sha256(out/"prices.csv")
    assert m["output_rows"] == 3 and m["rows_removed"] == 0
    g = read_prices(out/"prices.csv", c)
    assert g.price.isna().sum() == 1
    assert json.loads((out/"provenance.json").read_text())["source_file_name"] == "fred.csv"
    with pytest.raises(FileExistsError):
        write_prepared(f, c, info, source=source, output=out)
    with pytest.raises(FileExistsError):
        write_prepared(f, c, info, source=source, output=source)
    source.write_text(before.decode().replace("145", "144"))
    with pytest.raises(ValueError, match="发生变化"):
        write_prepared(f, c, info, source=source, output=tmp_path/"changed")
    assert not (tmp_path/"changed").exists()


@pytest.mark.parametrize("bad", ["oops", "NaN", "inf", "-1", "0"])
def test_daily_bad_price_never_silently_dropped(tmp_path, bad):
    source = tmp_path/"x.csv"
    source.write_text(f"observation_date,DEXUSEU\n2024-01-01,1\n2024-01-02,{bad}\n2024-01-03,2\n")
    with pytest.raises(ValueError):
        fred_csv(source, series="DEXUSEU", missing_policy="available")


def test_daily_duplicate_unknown_series_and_volume_unit_rejected(tmp_path):
    p = tmp_path/"x.csv"
    p.write_text("Date,Adj Close,Volume\n2024-01-01,100,5\n2024-01-01,101,6\n")
    with pytest.raises(ValueError, match="重复"):
        daily_csv(p, asset="ABC", date_column="Date", price_column="Adj Close", price_type="adjusted close")
    with pytest.raises(ValueError, match="同时"):
        daily_csv(p, asset="ABC", date_column="Date", price_column="Adj Close", price_type="adjusted close", volume_column="Volume")
    with pytest.raises(ValueError, match="只核对"):
        fred_csv(p, series="SP500")


def test_adjusted_price_chosen_and_actual_zero_volume_retained(tmp_path):
    p = tmp_path/"stock.csv"
    p.write_text("Date,Close,Adj Close,Volume\n2024-01-05,200,100,0\n2024-01-08,101,101,\n2024-01-09,102,102,20\n")
    f, c, info = daily_csv(p, asset="ABC", date_column="Date", price_column="Adj Close",
                           price_type="provider-adjusted close", volume_column="Volume", volume_unit="shares")
    s, _ = sample_path(f, c)
    np.testing.assert_allclose(s.log_return.iloc[1:], np.log([1.01, 102/101]))
    assert s.volume.iloc[0] == 0 and np.isnan(s.volume.iloc[1])
    assert c.volume_kind == "interval" and info["price_column"] == "Adj Close"


def test_ebs_only_deals_stable_ties_and_backward_sampling(tmp_path):
    p = tmp_path/"ebs.csv"
    p.write_text("Date,Time,Currency Pair,Event Type,BidPrc,OfferPrc,Side,Last Trade\n"
                 "2026/07/29,23:59:00.000,EUR/USD,D,,,G,1\n"
                 "2026/07/29,23:59:50.000,EUR/USD,Q,99,100,,\n"
                 "2026/07/29,23:59:59.500,EUR/USD,D,,,P,1.1\n"
                 "2026/07/29,23:59:59.500,EUR/USD,D,,,G,1.2\n"
                 "2026/07/30,00:00:01.000,EUR/USD,D,,,P,9\n"
                 "2026/07/30,00:02:00.000,EUR/USD,D,,,G,1.3\n"
                 "2026/07/30,00:02:00.000,USD/JPY,D,,,G,145\n")
    f, c, info = ebs_tick_csv(p, pair="EUR/USD", frequency="1min", max_staleness="30s")
    s, q = sample_path(f, c)
    np.testing.assert_allclose(s.price, [1, 1.2, np.nan, 1.3], equal_nan=True)
    assert len(f) == 5 and "volume" not in f
    assert info["same_timestamp_extra_rows"] == 1 and q["sessions"] == 1
    assert s.log_return.iloc[1] == pytest.approx(np.log(1.2))
    assert s.log_return.iloc[2:].isna().all()


def test_prepare_cli_and_provenance_is_escaped_and_hash_checked(tmp_path):
    p = tmp_path/"stock.csv"
    p.write_text("Date,Adj Close\n2024-01-01,100\n2024-01-02,101\n2024-01-03,102\n")
    out = tmp_path/"ready"
    assert main(["prepare", "daily-csv", str(p), "--output", str(out), "--asset", "ABC", "--price-type", "adjusted close"]) == 0
    manifest = json.loads((out/"provenance.json").read_text())
    manifest["notes"].append("<script>unsafe-note</script>")
    manifest["source_name"] = "<script>unsafe</script>"
    (out/"provenance.json").write_text(json.dumps(manifest))
    report = tmp_path/"report"
    assert main(["analyze-prepared", str(out), "--output", str(report)]) == 0
    html = (report/"index.html").read_text()
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in html
    assert "<script>unsafe</script>" not in html
    assert "基础收益：1 个日频观测" in html and "source-date-slot" not in html
    assert "<script>unsafe-note</script>" in json.loads((report/"results.json").read_text())["data_source"]["notes"]
    assert "unsafe-note" not in html
    assert json.loads((report/"results.json").read_text())["data_source"]["canonical_sha256"] == file_sha256(out/"prices.csv")
    (out/"prices.csv").write_text((out/"prices.csv").read_text().replace("100", "99"))
    assert main(["analyze-prepared", str(out), "--output", str(tmp_path/"wrong")]) == 2
    assert not (tmp_path/"wrong").exists()
