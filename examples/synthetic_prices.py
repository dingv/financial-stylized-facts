"""Small synthetic demonstration, not a fitted market model.

Usage: python examples/synthetic_prices.py /tmp/fsf-demo-prices.csv
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def make_prices(seed=20261102, n=5000):
    rng = np.random.default_rng(seed)
    gaussian = rng.normal(size=n)
    heavy = rng.standard_t(5, size=n) * np.sqrt(3 / 5)
    shocks = rng.normal(size=n+1000)
    clustered = np.empty(n+1000)
    variance = 1.0
    for i, shock in enumerate(shocks):
        clustered[i] = np.sqrt(variance) * shock
        variance = .05 + .1 * clustered[i]**2 + .85 * variance
    frames = []
    for label, returns in [("Gaussian iid", gaussian), ("Student-t iid", heavy), ("GARCH Gaussian", clustered[1000:])]:
        prices = 100 * np.exp(np.r_[0, np.cumsum(returns * .001)])
        frames.append(pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=n+1, freq="min", tz="UTC"),
                                    "price": prices, "asset_id": label, "path_id": "seed-"+str(seed), "session_id": "simulation"}))
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        make_prices().to_csv(stream, index=False)
    print(args.output)
