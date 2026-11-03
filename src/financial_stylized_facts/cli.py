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
    analyze.add_argument("--aggregation-factors", type=int, nargs="+", default=[1, 5, 10, 20], help="基本采样间隔的整数倍，非重叠聚合")
    analyze.add_argument("--rms-window", type=int, default=20, help="滚动 RMS 的基础收益观测数")
    analyze.add_argument("--burst-threshold", type=float, default=3.0, help="大幅波动阈值：偏离本路径均值的标准差倍数")
    analyze.add_argument("--volatility-max-lag", type=int, default=300, help="长范围绝对收益 ACF 的最大基础间隔数")
    analyze.add_argument("--stability-blocks", type=int, default=4, help="按时间顺序等观测槽分段，检查 ACF 是否稳定")
    analyze.add_argument("--volume-kind", choices=["none", "interval"], default="none", help="interval 表示已按基础采样区间汇总的成交量")
    analyze.add_argument("--volume-unit", help="成交量单位，例如 shares、contracts、USD；不能用成交笔数代替")
    analyze.add_argument("--coarse-factor", type=int, default=30, help="粗波动区间包含的基础收益数，至少为 2")
    analyze.add_argument("--conditional-model", choices=["auto", "off"], default="auto", help="有 arch 依赖且连续段足够长时拟合 GARCH")
    analyze.add_argument("--garch-min-points", type=int, default=500)
    analyze.add_argument("--garch-max-points", type=int, default=100000, help="每条路径允许拟合的总收益数上限，不截断长段")
    analyze.add_argument("--garch-max-segments", type=int, default=8, help="每条路径最多尝试拟合的连续段数")
    analyze.add_argument("--garch-max-iter", type=int, default=500)
    analyze.add_argument("--garch-burn", type=int, default=50, help="拟合后比较分布时舍弃段首的观测数")
    analyze.add_argument("--title", default="金融市场 · 基础统计诊断")
    args = parser.parse_args(argv)
    kwargs = {k: getattr(args, k) for k in AnalysisConfig.__dataclass_fields__}
    try:
        result = analyze_csv(args.input, args.output, AnalysisConfig(**kwargs), title=args.title)
    except (ValueError, OSError) as exc:
        print(f"无法生成报告：{exc}", file=sys.stderr)
        return 2
    print(f"报告：{(args.output / 'index.html').resolve()}")
    print(f"分别分析 {len(result['groups'])} 组资产/路径；数值已写入 results.json 和同目录各项 CSV。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
