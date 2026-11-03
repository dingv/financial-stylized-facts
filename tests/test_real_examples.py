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
    assert set(cases) == {"AAPL", "MSFT", "EURUSD", "USDJPY"}
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
