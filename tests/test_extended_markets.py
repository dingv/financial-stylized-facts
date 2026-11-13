"""Market-specific clocks and contract identity must survive sample conversion."""
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.data import sample_path

ROOT = Path(__file__).resolve().parents[1]


def module(filename):
    spec = importlib.util.spec_from_file_location(filename, ROOT / "examples" / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


examples = module("run_reports.py")
sources = module("market_sources.py")


@pytest.mark.parametrize("name,first,last", [
    ("GOLD_UAH", 8723.613, 186492.76), ("SILVER_UAH", 135.106, 3216.78),
])
def test_daily_metals_retain_units_weekday_clock_and_repeated_prices(name, first, last):
    _, source, frame, config, info = examples.load_cases(name)[0]
    raw = pd.read_csv(source)
    assert len(frame) == 4174 and config.sampling == "observations"
    assert frame.timestamp.dt.dayofweek.lt(5).all()
    assert frame.timestamp.iloc[0] == pd.Timestamp("2010-01-01", tz="UTC")
    assert frame.timestamp.iloc[-1] == pd.Timestamp("2025-12-31", tz="UTC")
    assert frame.price.iloc[0] == pytest.approx(first)
    assert frame.price.iloc[-1] == pytest.approx(last)
    assert np.allclose(raw.source_rate / raw.source_units, frame.price, rtol=0, atol=1e-8)
    assert set(raw.source_units) == {1, 10}
    assert (frame.price.diff() == 0).sum() > 200
    assert config.volume_kind == "none" and "UAH" in config.price_type
    assert info["retrieved_on"] == "2026-11-13"
    _, quality = sample_path(frame, config)
    assert quality["valid_returns"] == 4173


@pytest.mark.parametrize("name,first,last", [
    ("BTC_FUT_202512", 116133.0, 90681.7),
    ("ETH_FUT_202512", 4211.30, 2998.31),
])
def test_futures_have_one_contract_and_aligned_hourly_clock(name, first, last):
    _, source, frame, config, info = examples.load_cases(name)[0]
    raw = pd.read_csv(source)
    assert raw.contract_id.nunique() == 1 and raw.contract_id.iloc[0] == info["contract_id"]
    assert len(frame) == 1464 and (frame.timestamp.diff().dropna().dt.total_seconds() == 3600).all()
    assert config.sampling == "grid" and config.frequency == "1h" and config.max_staleness == "0s"
    assert config.session_policy == "continuous"
    assert frame.timestamp.iloc[0] == pd.Timestamp("2025-10-01T01:00:00Z")
    assert frame.timestamp.iloc[-1] == pd.Timestamp("2025-12-01T00:00:00Z")
    assert frame.price.iloc[0] == pytest.approx(first)
    assert frame.price.iloc[-1] == pytest.approx(last)
    sampled, quality = sample_path(frame, config)
    assert quality["valid_returns"] == 1463
    assert np.isfinite(sampled.log_return.iloc[1:]).all()


def test_taifex_reader_does_not_join_strikes_sides_or_expiry_day(tmp_path):
    fields = ["交易日期", "契約", "到期月份(週別)", "履約價", "買賣權", "交易時段", "結算價", "收盤價", "成交量"]
    records = [
        ["2025/12/15", "TXO", "202512  ", "24000", "買權", "一般", "100", "-", "0"],
        ["2025/12/16", "TXO", "202512", "24000", "買權", "一般", "101", "102", "3"],
        ["2025/12/16", "TXO", "202512", "24500", "買權", "一般", "50", "50", "2"],
        ["2025/12/16", "TXO", "202512", "24000", "賣權", "一般", "10", "10", "1"],
        ["2025/12/16", "TXO", "202512", "24000", "買權", "盤後", "102", "102", "1"],
        ["2025/12/17", "TXO", "202512", "24000", "買權", "一般", "0", "-", "0"],
    ]
    stream = io.StringIO(); writer = csv.writer(stream); writer.writerow(fields); writer.writerows(records)
    path = tmp_path / "options.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("month.csv", stream.getvalue().encode("cp950"))
    entry = dict(expiry_month="202512", strike=24000, source_option_type="買權", expiry="2025-12-17", contract_id="test", option_type="CALL")
    _, rows = sources.taifex_rows(path, entry)
    assert len(rows) == 2 and rows[0][1:4] == ("100", "", "0")
    assert rows[1][1:4] == ("101", "102", "3")


def test_binance_bar_end_and_zero_trade_handling(tmp_path):
    path = tmp_path / "sample.zip"
    header = "open_time,close_time,close,volume,count\n"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("BTCUSDT_251226-1h-sample.csv", header + "0,3599999,100,2,4\n3600000,7199999,100,0,0\n")
    entry = {"contract_id": "BTCUSDT_251226", "source_files": [{"file": path.name, "member": "BTCUSDT_251226-1h-sample.csv", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
    _, rows = sources.binance_rows(tmp_path, entry)
    assert rows[0][:3] == ("1970-01-01T01:00:00+00:00", "100", "2")
    assert rows[1][:3] == ("1970-01-01T02:00:00+00:00", "", "0")
    path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        sources.binance_rows(tmp_path, entry)


def test_nbu_reader_checks_unit_changes_and_source_calendar(tmp_path):
    entry = dict(source_series="XAU", selection_start="2025-01-03", selection_end="2025-01-06")
    records = [dict(cc="XAU", exchangedate=f"{day:02d}.01.2025", rate=1000, units=10,
                    rate_per_unit=100, calcdate=" ") for day in range(3, 7)]
    records[-1].update(rate=101, units=1, rate_per_unit=101)
    source = tmp_path / "metal.json"
    source.write_text(json.dumps(records))
    _, rows = sources.nbu_metal_rows(source, entry)
    assert [r[:4] for r in rows] == [("2025-01-03", "100", "1000", "10"),
                                    ("2025-01-06", "101", "101", "1")]
    for bad, message in [(records + [records[0]], "Duplicate"), (records[:-1], "incomplete"),
                         ([dict(records[0], units=1)] + records[1:], "unit conversion"),
                         ([dict(records[0], cc="XAG")] + records[1:], "Unexpected")]:
        source.write_text(json.dumps(bad))
        with pytest.raises(ValueError, match=message):
            sources.nbu_metal_rows(source, entry)
