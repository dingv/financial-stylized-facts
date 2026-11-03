"""Rebuild the Coin Metrics/EIA snapshots from the original files, offline.

EIA workbooks require the optional extraction dependency xlrd==2.0.2.
Source filenames, download URLs and checksums are in data/examples/manifest.json.
"""
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path


CATALOG = Path(__file__).resolve().parents[1] / "data/examples/manifest.json"
MARKETS = ("BTC", "ETH", "BRENT", "HENRYHUB")


def extract(source, entry):
    if entry["source_format"] == "coinmetrics-csv":
        with source.open(newline="", encoding="utf-8") as stream:
            rows = [(r["time"][:10], r["PriceUSD"], r["volume_reported_spot_usd_1d"])
                    for r in csv.DictReader(stream)]
        columns = ["date", "price_usd", "spot_volume_usd"]
    else:
        import xlrd
        book = xlrd.open_workbook(source)
        sheet = book.sheet_by_name("Data 1")
        if sheet.cell_value(1, 1) != entry["source_series"]:
            raise ValueError("Unexpected EIA series")
        rows = []
        for i in range(3, sheet.nrows):
            day = xlrd.xldate_as_datetime(sheet.cell_value(i, 0), book.datemode).date().isoformat()
            value = sheet.cell_value(i, 1)
            # EIA publishes both series to two decimal places; retain source blanks.
            if value != "" and abs(value * 100 - round(value * 100)) > 1e-8:
                raise ValueError("Unexpected EIA precision")
            rows.append((day, "" if value == "" else f"{value:.2f}"))
        columns = ["date", "price_usd"]
    rows = [r for r in rows if entry["selection_start"] <= r[0] <= entry["selection_end"]]
    dates = [r[0] for r in rows]
    if not dates or dates != sorted(set(dates)):
        raise ValueError("Dates must be increasing and unique")
    if len(rows) != entry["rows"] or sum(r[1] == "" for r in rows) != entry["missing_prices"]:
        raise ValueError("Unexpected sample coverage")
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def rebuild(raw, output, catalog=CATALOG):
    raw, output = Path(raw), Path(output)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    entries = json.loads(Path(catalog).read_text(encoding="utf-8"))["datasets"]
    prepared = {}
    for name in MARKETS:
        entry = entries[name]
        source = raw / entry["source_file"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["source_sha256"]:
            raise ValueError(f"Original checksum mismatch: {name}")
        data = extract(source, entry)
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError(f"Rebuilt snapshot checksum mismatch: {name}")
        prepared[entry["file"]] = data
    output.mkdir(parents=True, exist_ok=False)
    for name, data in prepared.items():
        (output / name).write_bytes(data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    rebuild(args.raw, args.output)
