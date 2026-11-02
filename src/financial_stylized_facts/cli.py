"""Command-line entry point."""
import argparse
from pathlib import Path
import sys

from . import __version__
from .data import AnalysisConfig
from .report import analyze_csv


def main(argv=None):
    parser = argparse.ArgumentParser(description="生成逐资产、逐路径的金融统计诊断报告")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="分析 canonical CSV 价格数据")
    analyze.add_argument("input", type=Path)
    analyze.add_argument("--output", type=Path, required=True)
    analyze.add_argument("--frequency", default="5min")
    analyze.add_argument("--timezone")
    analyze.add_argument("--max-staleness", default="0s", help="最多沿用多旧的价格；默认只接受精确端点")
    analyze.add_argument("--sampling", choices=["grid", "observations"], default="grid")
    analyze.add_argument("--observation-unit", help="observations 模式必须声明，例如 trading-day")
    analyze.add_argument("--session-policy", choices=["date", "continuous"], default="date")
    analyze.add_argument("--max-lag", type=int, default=30)
    analyze.add_argument("--min-pairs", type=int, default=20)
    analyze.add_argument("--max-grid-points", type=int, default=2_000_000)
    analyze.add_argument("--price-type", default="unspecified")
    analyze.add_argument("--title", default="金融市场 · 基础统计诊断")
    args = parser.parse_args(argv)
    kwargs = {k: getattr(args, k) for k in AnalysisConfig.__dataclass_fields__}
    try:
        result = analyze_csv(args.input, args.output, AnalysisConfig(**kwargs), title=args.title)
    except (ValueError, OSError) as exc:
        print(f"无法生成报告：{exc}", file=sys.stderr)
        return 2
    print(f"报告：{(args.output / 'index.html').resolve()}")
    print(f"分别分析 {len(result['groups'])} 组资产/路径；数值已写入 results.json、summary.csv 和 acf.csv。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
