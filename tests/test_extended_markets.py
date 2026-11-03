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
    ("GOLD", 35, 4309), ("SILVER", .9, 62.3), ("COPPER", 715, 11785),
    ("WHEAT", 59.9, 242.8), ("MAIZE", 45, 205.7), ("SOYBEANS", 94, 440),
])
def test_monthly_samples_are_calendar_months_not_daily(name, first, last):
    _, _, frame, config, info = examples.load_cases(name)[0]
    assert len(frame) == 792 and config.sampling == "observations"
    assert config.observation_unit == "calendar-month"
    assert info["adapter"] == "monthly-labelled-csv" and config.volume_kind == "none"
    periods = frame.timestamp.dt.tz_localize(None).dt.to_period("M")
    assert list(periods) == list(pd.period_range("1960-01", "2025-12", freq="M"))
    assert frame.price.iloc[0] == pytest.approx(first)
    assert frame.price.iloc[-1] == pytest.approx(last)
    _, quality = sample_path(frame, config)
    assert quality["valid_returns"] == 791


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


@pytest.mark.parametrize("side,first,last", [("CALL", 655, 3630), ("PUT", 2480, .2)])
def test_option_premium_is_one_contract_before_expiry(side, first, last):
    name = "TXO_202512_24000_" + side
    _, source, frame, config, info = examples.load_cases(name)[0]
    raw = pd.read_csv(source)
    assert len(frame) == 186 and raw.contract_id.nunique() == 1
    assert set(raw.option_type) == {side} and set(raw.strike) == {24000}
    assert set(raw.expiry) == {"2025-12-17"}
    assert frame.timestamp.max() == pd.Timestamp("2025-12-16", tz="UTC")
    assert frame.price.iloc[0] == first and frame.price.iloc[-1] == last
    assert raw.last_trade_price.isna().any()  # Never fabricated from settlement.
    assert (raw.volume == 0).any()
    assert config.garch_min_points == 500 and config.inference_min_pairs == 200
    assert "结算价" in info["report_note"]
    _, quality = sample_path(frame, config)
    assert quality["valid_returns"] == 185


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
