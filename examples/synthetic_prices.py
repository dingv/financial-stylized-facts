"""Small synthetic demonstration, not a fitted market model.

Usage: python examples/synthetic_prices.py /tmp/fsf-demo-prices.csv
"""
import argparse
from pathlib import Path

from financial_stylized_facts.demo import synthetic_prices as make_prices


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.output.open("x") as stream:
        make_prices().to_csv(stream, index=False)
    print(args.output)
