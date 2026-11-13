"""Build the README overview from the checked-in assessment tables.

Run from the repository root: python examples/plot_assessment_overview.py
No model fitting or market-data processing is performed.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
GROUPS = [
    ("股票", "日频", [("AAPL", "AAPL"), ("MSFT", "MSFT")]),
    ("外汇", "日频", [("EURUSD", "EUR/USD"), ("USDJPY", "USD/JPY")]),
    ("加密资产", "日频", [("BTC", "BTC"), ("ETH", "ETH")]),
    ("能源", "日频", [("BRENT", "Brent 原油"), ("HENRYHUB", "Henry Hub 天然气")]),
    ("金属", "月频", [("GOLD", "黄金"), ("SILVER", "白银"), ("COPPER", "铜")]),
    ("期货", "小时", [("BTC_FUT_202512", "BTC 期货"), ("ETH_FUT_202512", "ETH 期货")]),
    ("期权", "日频", [("TXO_202512_24000_CALL", "台指看涨期权"),
                        ("TXO_202512_24000_PUT", "台指看跌期权")]),
]
HEADERS = ["收益线性相关", "厚尾", "涨跌不对称", "聚合高斯化", "间歇性", "波动聚集",
           "条件厚尾", "波动缓慢衰减", "杠杆效应", "量价相关", "尺度不对称"]
COLORS = {"supported": "#2878CE", "indicative": "#A4C8F2", "inconclusive": "#E6E5E0",
          "opposite": "#EDAB62", "unavailable": "#FFFFFF", "return_test": "#F5F8FC"}


def category(row):
    """Keep unavailability and opposite direction distinct from non-rejection."""
    conclusion = row["conclusion"]
    if (conclusion in {"insufficient_data", "not_applicable"}
            or row.get("inference_status") == "unavailable"
            or row.get("evidence_level") == "unavailable"):
        return "unavailable"
    if row["fact_id"] == "1":
        if conclusion not in {"not_detected", "correlation_detected"}:
            raise ValueError(f"Unmapped return-correlation result: {conclusion}")
        return "return_test"
    if conclusion == "opposite_direction":
        return "opposite"
    if conclusion in {"supported", "indicative"}:
        return conclusion
    if conclusion in {"not_detected", "inconclusive", "mixed", "descriptive"}:
        return "inconclusive"
    raise ValueError(f"Unmapped conclusion: {conclusion}")


def load_assessments(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    entries = {r["dataset"]: r for r in manifest}
    result = {}
    versions = set()
    for _, _, assets in GROUPS:
        for name, _ in assets:
            entry = entries[name]
            source = directory / entry["assessment"]
            if hashlib.sha256(source.read_bytes()).hexdigest() != entry["assessment_sha256"]:
                raise ValueError(f"Assessment checksum mismatch: {name}")
            with source.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            if len(rows) != 11 or {r["fact_id"] for r in rows} != {str(i) for i in range(1, 12)}:
                raise ValueError(f"Expected exactly 11 facts: {name}")
            result[name] = {int(r["fact_id"]): r for r in rows}
            for row in rows:
                category(row)
                versions.add(row["rule_id"].rsplit(".v", 1)[1])
    if len(versions) != 1:
        raise ValueError("Assessment versions must agree across reports")
    return result, versions.pop()


def select_font(explicit):
    if explicit:
        font_manager.fontManager.addfont(explicit)
        return font_manager.FontProperties(fname=explicit).get_name()
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in ("Noto Sans CJK JP", "Noto Sans CJK SC", "Microsoft YaHei", "PingFang SC", "Arial Unicode MS"):
        if name in available:
            return name
    raise RuntimeError("A Chinese font is required; install Noto Sans CJK or pass --font PATH")


def draw(directory, output, font=None):
    assessments, version = load_assessments(directory)
    plt.rcParams.update({"font.family": select_font(font), "axes.unicode_minus": False})
    fig = plt.figure(figsize=(16, 10.4), facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(-3.65, 11.9)
    ax.set_ylim(-3.25, 20.25)
    ax.invert_yaxis()
    ax.axis("off")
    ax.text(-3.3, -2.4, "15 组真实数据 × 11 项 stylized facts", fontsize=23,
            weight="bold", color="#18222D", va="center")
    ax.text(-3.3, -1.62, "跨市场评估总览", fontsize=13, color="#617080", va="center")
    for col, label in enumerate(HEADERS):
        ax.text(col + .38, .45, f"{col+1}. {label}", rotation=40, ha="left", va="bottom",
                fontsize=12.5, color="#3D4752", rotation_mode="anchor")

    def box(x, y, kind, width=.95, height=.80):
        edge = "#D8D6CF" if kind == "unavailable" else "#FFFFFF"
        patch = FancyBboxPatch((x, y), width, height,
                              boxstyle="round,pad=0,rounding_size=0.055",
                              facecolor=COLORS[kind], edgecolor=edge, linewidth=.8,
                              hatch="///" if kind == "unavailable" else None)
        ax.add_patch(patch)

    y = .9
    for group, frequency, assets in GROUPS:
        middle = y + (len(assets)-1)*.90/2 + .4
        ax.text(-3.3, middle-.18, group, fontsize=13, weight="bold", color="#4F5963", va="center")
        ax.text(-3.3, middle+.29, frequency, fontsize=10.5, color="#87909A", va="center")
        for name, label in assets:
            ax.text(-.16, y+.4, label, fontsize=12.5, color="#18222D", ha="right", va="center")
            for fact, row in assessments[name].items():
                kind = category(row)
                box(fact-1, y, kind)
                if fact == 1 and kind == "return_test":
                    text = "未检出" if row["conclusion"] == "not_detected" else "有相关"
                    ax.text(.475, y+.40, text, fontsize=10.5, ha="center", va="center", color="#4D6074")
            y += .90
        y += .42
    legend = [("supported", "有支持", 0), ("indicative", "有迹象", 1.7),
              ("inconclusive", "未检出／结论不一致", 3.4),
              ("opposite", "与经典方向相反", 6.45), ("unavailable", "无法评估／不适用", 9.05)]
    for kind, label, x in legend:
        box(x, y+.02, kind, width=.25, height=.42)
        ax.text(x+.34, y+.23, label, fontsize=10.5, color="#535E69", va="center")
    ax.text(0, y+.94, "第 1 列直接标注收益相关检验结果；各市场按其原始采样频率独立评估。",
            fontsize=10.5, color="#74808C", va="center")
    ax.text(0, y+1.50, f"来源：15 份示例报告的 assessment.csv · 评估规则 v{version}",
            fontsize=9.5, color="#929BA4", va="center")
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=170, facecolor="white")
    plt.close(fig)
    print(f"Wrote {output}: {len(assessments)} datasets, 165 cells, rule v{version}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reports", type=Path, default=ROOT / "examples/reports")
    parser.add_argument("--output", type=Path, default=ROOT / "examples/reports/images/assessment-overview.png")
    parser.add_argument("--font", help="Optional Chinese font file")
    args = parser.parse_args()
    draw(args.reports, args.output, args.font)
