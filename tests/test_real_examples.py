"""Integration checks for the frozen public market snapshots."""
import importlib.util
from pathlib import Path
import shutil

import numpy as np
import pytest

from financial_stylized_facts.data import sample_path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("real_examples", ROOT / "examples/run_reports.py")
examples = importlib.util.module_from_spec(spec)
spec.loader.exec_module(examples)


def test_real_snapshots_use_actual_prices_and_explicit_observation_clock():
    cases = {name: (frame, config, info) for name, _, frame, config, info in examples.load_cases("all")}
    assert set(cases) == {"AAPL", "MSFT", "EURUSD", "USDJPY", "BTC", "ETH", "BRENT", "HENRYHUB"}
    aapl, config, info = cases["AAPL"]
    assert len(aapl) == 3270
    assert aapl.price.iloc[0] == pytest.approx(4.186662803811)
    assert aapl.volume.iloc[0] == 9616100
    assert config.sampling == "observations" and info["rows_removed"] == 0
    for name in ("EURUSD", "USDJPY"):
        frame, config, info = cases[name]
        assert len(frame) == 4001 and info["missing_source_prices"] == 173
        assert info["rows_removed"] == 173 and config.volume_kind == "none"
        assert config.observation_unit == "available-price-observation"
        assert frame.timestamp.iloc[0].strftime("%Y-%m-%d") == "2010-01-04"
        # There are genuine gaps in calendar time; no fabricated weekend prices.
        assert frame.timestamp.diff().dt.days.max() >= 3
        sampled, quality = sample_path(frame, config)
        assert quality["valid_returns"] == 4000
        assert np.isfinite(frame.price).all()


def test_modified_real_snapshot_rejected_before_output(tmp_path):
    data = tmp_path / "data"
    shutil.copytree(examples.DATA, data)
    with (data / "AAPL.csv").open("a") as stream:
        stream.write("unexpected,row\n")
    output = tmp_path / "output"
    with pytest.raises(ValueError, match="checksum"):
        examples.run("AAPL", output, data)
    assert not output.exists()


def test_real_example_never_overwrites_report(tmp_path):
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "keep.txt"
    sentinel.write_text("original")
    with pytest.raises(FileExistsError):
        examples.run("AAPL", output)
    assert sentinel.read_text() == "original" and len(list(output.iterdir())) == 1


@pytest.mark.parametrize("name,first,last,first_volume", [
    ("BTC", 7170.63186879018, 87516.9780376972, 945065382.602609),
    ("ETH", 129.963875336061, 2968.12801431911, 181770907.592221),
])
def test_crypto_calendar_and_spot_turnover(name, first, last, first_volume):
    _, _, frame, config, info = examples.load_cases(name)[0]
    assert len(frame) == 2192 and info["rows_removed"] == 0
    assert frame.timestamp.iloc[0].strftime("%Y-%m-%d") == "2020-01-01"
    assert frame.timestamp.iloc[-1].strftime("%Y-%m-%d") == "2025-12-31"
    assert (frame.timestamp.diff().dropna().dt.total_seconds() == 86400).all()
    assert frame.price.iloc[0] == pytest.approx(first)
    assert frame.price.iloc[-1] == pytest.approx(last)
    assert frame.volume.iloc[0] == pytest.approx(first_volume)
    assert np.isfinite(frame.volume).all() and (frame.volume > 0).all()
    assert config.volume_kind != "none"
    assert info["data_license"] == "CC BY-NC 4.0 (data only)"
    _, quality = sample_path(frame, config)
    assert quality["valid_returns"] == 2191


@pytest.mark.parametrize("name,n,missing,first,last", [
    ("BRENT", 4047, 0, 79.05, 61.35),
    ("HENRYHUB", 4035, 1, 6.09, 4.00),
])
def test_energy_spot_keeps_source_gaps(name, n, missing, first, last):
    _, _, frame, config, info = examples.load_cases(name)[0]
    assert len(frame) == n and info["rows_removed"] == missing
    assert info["missing_source_prices"] == missing
    assert config.volume_kind == "none"
    assert frame.price.iloc[0] == pytest.approx(first)
    assert frame.price.iloc[-1] == pytest.approx(last)
    assert frame.timestamp.iloc[0].strftime("%Y-%m-%d") == "2010-01-04"
    assert frame.timestamp.iloc[-1].strftime("%Y-%m-%d") == "2025-12-31"
    assert frame.timestamp.diff().dt.days.max() >= 3
    assert np.isfinite(frame.price).all() and (frame.price > 0).all()
    _, quality = sample_path(frame, config)
    assert quality["valid_returns"] == n - 1


def test_real_example_cli_accepts_catalog_markets(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(examples, "run", lambda name, output: calls.append((name, output)))
    for name in ("BTC", "ETH", "BRENT", "HENRYHUB"):
        examples.main(["--dataset", name, "--output", str(tmp_path / name)])
    assert [name for name, _ in calls] == ["BTC", "ETH", "BRENT", "HENRYHUB"]
    with pytest.raises(SystemExit) as caught:
        examples.main(["--dataset", "UNKNOWN", "--output", str(tmp_path / "bad")])
    assert caught.value.code == 2
    assert not (tmp_path / "bad").exists()


def test_standalone_html_retains_data_attribution_and_escapes_text():
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from financial_stylized_facts import AnalysisConfig
    from financial_stylized_facts.report import _fmt

    env = Environment(loader=FileSystemLoader(ROOT / "src/financial_stylized_facts/templates"),
                      autoescape=select_autoescape(["html"]))
    env.filters["number"] = _fmt
    result = {"title": "Example", "provenance": {}, "data_source": {
        "source_name": "Coin Metrics", "attribution": "Coin Metrics, Inc. <script>test</script>",
        "data_license": "CC BY-NC 4.0", "license_url": "https://creativecommons.org/licenses/by-nc/4.0/",
        "source_url": "https://example.com/data.csv"}}
    html = env.get_template("report.html").render(result=result, groups=[],
                                                 config=AnalysisConfig(), clock_label="daily")
    assert "Coin Metrics, Inc." in html and "CC BY-NC 4.0" in html
    assert result["data_source"]["license_url"] in html
    assert result["data_source"]["source_url"] in html
    assert "<script>test</script>" not in html and "&lt;script&gt;test&lt;/script&gt;" in html
