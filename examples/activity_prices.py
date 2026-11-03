"""Known time direction and artificial volume, for diagnostic demonstration only.

Run with --frequency 1min --coarse-factor 2 --volume-kind interval
         --volume-unit synthetic-units --price-type synthetic
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd


def make_prices(seed=20261103, n_blocks=1200):
    rng = np.random.default_rng(seed)
    coarse = rng.uniform(0, 1, n_blocks)
    fine = np.r_[1., 1+coarse[:-1]]
    # |r1+r2|=coarse, mean(|r1|,|r2|)=fine: deliberately coarse leads fine.
    returns = .001*np.column_stack([fine+coarse/2, coarse/2-fine]).ravel()
    volume = 1000+2e5*np.abs(returns)+rng.uniform(0, 50, len(returns))
    frames = []
    for label, r, v in [("Coarse leads fine", returns, volume), ("Time reversed", returns[::-1], volume[::-1])]:
        frames.append(pd.DataFrame({"timestamp": pd.date_range("2024-01-01", periods=len(r)+1, freq="min", tz="UTC"),
                                   "price": 100*np.exp(np.r_[0, r.cumsum()]), "volume": np.r_[np.nan, v],
                                   "asset_id": "Constructed process", "path_id": label, "session_id": "simulation"}))
    return pd.concat(frames, ignore_index=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        make_prices().to_csv(stream, index=False)
    print(args.output)
