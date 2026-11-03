"""Explicit optional download of two historical Bokeh stock examples to a new directory.

Data is not bundled or licensed by this library. See docs/data-guide.md.
"""
import hashlib
from pathlib import Path
import sys
from urllib.request import urlopen

from validate_real_data import STOCK_SHA256


def fetch(output):
    output.mkdir(parents=True, exist_ok=False)
    for name, expected in STOCK_SHA256.items():
        url = f"https://sampledata.bokeh.org/{name}.csv"
        with urlopen(url, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000 or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"{name} 与已核对的小型快照不一致；未保存响应")
        (output/f"{name}.csv").write_bytes(raw)
        print(name, len(raw), "bytes; checksum matched")


if __name__ == "__main__":
    fetch(Path(sys.argv[1]))
