"""Known time direction and artificial volume, for diagnostic demonstration only.

Run with --frequency 1min --coarse-factor 2 --volume-kind interval
         --volume-unit synthetic-units --price-type synthetic
"""
import argparse
from pathlib import Path

from financial_stylized_facts.demo import activity_prices as make_prices


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        make_prices().to_csv(stream, index=False)
    print(args.output)
