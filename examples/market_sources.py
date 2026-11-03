"""Offline readers for frozen World Bank, Binance and TAIFEX source files."""
import csv
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import hashlib
import io
from pathlib import Path
import re
import xml.etree.ElementTree as ET
import zipfile


def worldbank_rows(path, column, start="1960M01", end="2025M12"):
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as book:
        strings = ["".join(s.itertext()) for s in ET.fromstring(book.read("xl/sharedStrings.xml"))]
        sheets = ET.fromstring(book.read("xl/workbook.xml"))
        sheet = next(s for s in sheets.find("m:sheets", ns) if s.attrib["name"] == "Monthly Prices")
        rid = sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]
        target = next(r.attrib["Target"] for r in ET.fromstring(book.read("xl/_rels/workbook.xml.rels")) if r.attrib["Id"] == rid)
        root = ET.fromstring(book.read("xl/" + target.lstrip("/")))
        table = []
        for row in root.findall(".//m:row", ns):
            values = {}
            for cell in row:
                value = cell.find("m:v", ns)
                value = "" if value is None else value.text
                if cell.attrib.get("t") == "s":
                    value = strings[int(value)]
                values[re.sub(r"\d+$", "", cell.attrib["r"])] = value
            table.append(values)
    headers = [r for r in table if column in r.values()]
    if len(headers) != 1:
        raise ValueError("World Bank column not uniquely identified")
    col = next(k for k, v in headers[0].items() if v == column)
    rows = []
    for r in table:
        period = r.get("A", "")
        if re.fullmatch(r"\d{4}M\d{2}", period) and start <= period <= end:
            value = r.get(col, "")
            if value in {"", "...", "…"}:
                value = ""
            elif not Decimal(value).is_finite() or Decimal(value) <= 0:
                raise ValueError("Unexpected commodity price")
            rows.append((period[:4] + "-" + period[5:] + "-01", value))
    return ["date", "price"], rows


def binance_rows(directory, entry):
    rows = []
    symbol = entry["contract_id"]
    for item in entry["source_files"]:
        path = Path(directory) / item["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Binance archive checksum mismatch")
        with zipfile.ZipFile(path) as archive:
            if archive.namelist() != [item["member"]] or not item["member"].startswith(symbol + "-1h-"):
                raise ValueError("Unexpected futures contract")
            source = csv.DictReader(io.StringIO(archive.read(item["member"]).decode("utf-8")))
            for r in source:
                start, end = int(r["open_time"]), int(r["close_time"])
                if start % 3600000 or end != start + 3599999:
                    raise ValueError("Unexpected hourly boundary")
                # A bar ending at hh:59:59.999 is labelled by the next exact hour.
                timestamp = datetime.fromtimestamp((end + 1) / 1000, timezone.utc).isoformat()
                price = r["close"] if int(r["count"]) > 0 else ""
                rows.append((timestamp, price, r["volume"], r["count"], symbol))
    rows.sort()
    times = [datetime.fromisoformat(r[0]) for r in rows]
    if any(b - a != timedelta(hours=1) for a, b in zip(times, times[1:])):
        raise ValueError("Futures archives have gaps or duplicate hours")
    return ["timestamp", "price", "volume", "trade_count", "contract_id"], rows


def taifex_rows(path, entry):
    rows = []
    with zipfile.ZipFile(path) as archive:
        for member in sorted(archive.namelist()):
            with archive.open(member) as stream:
                for r in csv.DictReader(io.TextIOWrapper(stream, encoding="cp950")):
                    if (r["契約"].strip() != "TXO"
                            or r["到期月份(週別)"].strip() != entry["expiry_month"]
                            or Decimal(r["履約價"].strip()) != entry["strike"]
                            or r["買賣權"].strip() != entry["source_option_type"]
                            or r["交易時段"].strip() != "一般"):
                        continue
                    day = datetime.strptime(r["交易日期"].strip(), "%Y/%m/%d").date().isoformat()
                    # Expiry-day settlement fields are not option premium observations.
                    if day >= entry["expiry"]:
                        continue
                    settlement = r["結算價"].strip()
                    if settlement in {"", "-"}:
                        settlement = ""
                    elif Decimal(settlement) <= 0:
                        raise ValueError("Nonpositive pre-expiry option premium")
                    last = r["收盤價"].strip()
                    last = "" if last in {"", "-"} else last
                    rows.append((day, settlement, last, r["成交量"].strip(), entry["contract_id"],
                                 entry["expiry"], str(entry["strike"]), entry["option_type"]))
    rows.sort()
    if len({r[0] for r in rows}) != len(rows):
        raise ValueError("Duplicate contract dates")
    return ["date", "settlement", "last_trade_price", "volume", "contract_id", "expiry", "strike", "option_type"], rows


def encode_csv(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")
