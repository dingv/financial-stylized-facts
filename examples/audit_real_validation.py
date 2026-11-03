"""Independent small-run numerical audit: NumPy backward lookup + SciPy moments.

Does not call the library's sampler, return calculator, ACF, or distribution code.
Input is the temporary directory produced by validate_real_data.py.
"""
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
from scipy.stats import kurtosis


def audit(root):
    rows = []
    for p in sorted(root.glob("*/report/results.json")):
        result = json.loads(p.read_text())
        c, g = result["config"], result["groups"][0]
        raw = pd.read_csv(p.parent.parent/"input/prices.csv")
        raw["timestamp"] = pd.to_datetime(raw.timestamp, utc=True, format="ISO8601")
        parts, missing = [], 0
        for _, part in raw.groupby("session_id", sort=False):
            part = part.sort_values("timestamp", kind="stable")
            if c["sampling"] == "observations":
                prices = part.price.to_numpy(float)
            else:
                step = pd.Timedelta(c["frequency"])
                stamps = part.timestamp.astype("int64").to_numpy()
                grid = pd.date_range(part.timestamp.min().ceil(step), part.timestamp.max().floor(step), freq=step).asi8
                positions = np.searchsorted(stamps, grid, side="right")-1
                valid = positions >= 0
                valid &= grid-stamps[np.maximum(positions, 0)] <= pd.Timedelta(c["max_staleness"]).value
                prices = np.full(len(grid), np.nan)
                prices[valid] = part.price.to_numpy()[positions[valid]]
            missing += int(np.isnan(prices).sum())
            parts.append(np.r_[np.nan, np.diff(np.log(prices))])
        values = np.concatenate(parts)
        finite = values[np.isfinite(values)]
        assert len(finite) == g["quality"]["valid_returns"]
        assert missing == g["quality"]["missing_prices"]
        expected = float(kurtosis(finite, fisher=True, bias=False))
        np.testing.assert_allclose(expected, g["distribution"]["excess_kurtosis"], rtol=1e-11, atol=1e-12)
        errors = []
        for name, transform in [("return", lambda x:x), ("absolute_return", np.abs), ("squared_return", np.square)]:
            transformed = [transform(a) for a in parts]
            mu = np.nanmean(np.concatenate(transformed))
            denominator = sum(np.nansum((a-mu)**2) for a in transformed)
            actual = g["acf"][name]
            for lag in range(1, c["max_lag"]+1):
                numerator, count = 0., 0
                for a in transformed:
                    left, right = a[:-lag], a[lag:]
                    ok = np.isfinite(left) & np.isfinite(right)
                    count += int(ok.sum())
                    numerator += np.sum((left[ok]-mu)*(right[ok]-mu))
                assert actual["pair_counts"][lag] == count
                if count < c["min_pairs"] or denominator == 0:
                    assert actual["values"][lag] is None
                else:
                    error = abs(numerator/denominator-actual["values"][lag])
                    assert error < 1e-11
                    errors.append(float(error))
        rows.append({"case": p.parent.parent.name, "valid_returns": len(finite), "missing_prices": missing,
                     "max_acf_absolute_error": max(errors, default=None),
                     "kurtosis_absolute_error": abs(expected-g["distribution"]["excess_kurtosis"])})
    if len(rows) != 8:
        raise ValueError("此小规模方案应有 8 个完整报告")
    out = {"status": "passed", "reference": "independent NumPy lookup/differences, direct ACF sums, SciPy corrected kurtosis", "cases": rows}
    (root/"numerical-audit.json").write_text(json.dumps(out, indent=2, allow_nan=False))
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    audit(Path(sys.argv[1]))
