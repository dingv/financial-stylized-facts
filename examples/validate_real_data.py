"""Small, read-only real-data validation; outputs belong outside the repository.

Requires the user's existing EBS/FRED snapshots and separately acquired Bokeh
stock CSVs. No download, model simulation, or source-data write occurs here.
"""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import time

from financial_stylized_facts.adapters import daily_csv, fred_csv, ebs_tick_csv, write_prepared, file_sha256
from financial_stylized_facts.data import sample_path
from financial_stylized_facts.report import analyze_csv


STOCK_SHA256 = {
    "AAPL": "855f0b122ac0e4c5b9464d1862f6c56bcd2c1cd7eb94db6fa6c798546964dff8",
    "MSFT": "b3d95da3b72a786616c10b196999c5fc2f7e42dc37be0723ae9038a9244f0f82",
}


def run(fred_dir, ebs_file, stock_dir, output):
    output.mkdir(parents=True, exist_ok=False)
    started, summaries = time.monotonic(), []
    sources = [fred_dir/f"{s}.csv" for s in ["DEXUSEU", "DEXJPUS"]] + [ebs_file] + [stock_dir/f"{s}.csv" for s in STOCK_SHA256]
    before = {str(p): file_sha256(p) for p in sources}
    for ticker, expected in STOCK_SHA256.items():
        if before[str(stock_dir/f"{ticker}.csv")] != expected:
            raise ValueError(f"{ticker} 不匹配已核对的 Bokeh 历史示例快照")
    cases = []
    for series in ["DEXUSEU", "DEXJPUS"]:
        p = fred_dir/f"{series}.csv"
        f, c, info = fred_csv(p, series=series, missing_policy="available", start="2000-03-01", end="2013-03-01")
        # The preserved-slot comparison checks how much the explicit choice changes sample size.
        pf, pc, pi = fred_csv(p, series=series, missing_policy="preserve", start="2000-03-01", end="2013-03-01")
        ps, pq = sample_path(pf, pc)
        info["preserved_slot_valid_returns"] = pq["valid_returns"]
        info["notes"].append(f"同一范围保留缺失槽时有 {pq['valid_returns']} 条有效收益；本次明确采用相邻可用报价收益，并非把删除缺失当作无影响。")
        cases.append((series, p, f, c, info))
    for ticker in STOCK_SHA256:
        p = stock_dir/f"{ticker}.csv"
        f, c, info = daily_csv(p, asset=ticker, date_column="Date", price_column="Adj Close",
                               price_type="Bokeh 示例标注的 Adj Close（调整收盘价）", volume_column="Volume",
                               volume_unit="source-reported shares; adjustment unspecified", source_name=f"Bokeh historical stock sample / {ticker}")
        info["source_url"] = f"https://sampledata.bokeh.org/{ticker}.csv"
        info["notes"] += ["该公开研究/可视化样本覆盖 2000–2013 年，提供方称数据来自公开新闻来源；不是交易所授权完整行情。",
                           "使用提供方的 Adj Close 列；未独立审计分红、拆股及 Volume 的调整方法，因此量价关系仅作输入与计算验证。",
                           "原始样本不随本库分发；软件许可证不等于数据再分发许可。"]
        cases.append((ticker, p, f, c, info))
    for pair in ["EUR/USD", "USD/JPY"]:
        for frequency in ["1min", "5min"]:
            f, c, info = ebs_tick_csv(ebs_file, pair=pair, frequency=frequency, max_staleness="5min")
            info["notes"].append("只有一个 EBS 文件日，日内状态和小样本会影响估计，不能据此判断整个外汇市场的长期性质。")
            cases.append((pair.replace("/", "")+"-"+frequency, ebs_file, f, c, info))
    for name, source, frame, config, info in cases:
        if time.monotonic()-started > 240:
            raise RuntimeError("验证运行超过 4 分钟工作预算，停止新增报告")
        # Same fixed settings for every case; not selected for attractive results.
        config = replace(config, max_lag=20, volatility_max_lag=100, coarse_factor=5,
                         bootstrap_reps=399, garch_max_points=10000, garch_max_segments=4)
        prepared, report = output/name/"input", output/name/"report"
        manifest = write_prepared(frame, config, info, source=source, output=prepared)
        result = analyze_csv(prepared/"prices.csv", report, config, title=f"真实数据验证 · {name}", source_provenance=manifest)
        group = result["groups"][0]
        summaries.append({"case": name, "quality": group["quality"], "distribution": group["distribution"],
                          "acf_lag1": {k: v["values"][1] for k, v in group["acf"].items()},
                          "volume": group["volume_volatility"], "conditional": group["conditional_tails"],
                          "uncertainty": group["uncertainty"], "source": manifest})
        print(name, "returns", group["distribution"]["n"], "excess kurtosis", group["distribution"]["excess_kurtosis"],
              "GARCH", group["conditional_tails"]["status"], "intervals", group["uncertainty"]["status"], flush=True)
        total_bytes = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
        if total_bytes > 100 * 1024**2:
            raise RuntimeError("验证输出超过 100 MiB，停止新增报告")
    after = {str(p): file_sha256(p) for p in sources}
    if after != before:
        raise RuntimeError("源文件在验证期间发生变化，不能宣称使用固定快照")
    summary = {"source_hashes_unchanged": True, "elapsed_seconds": time.monotonic()-started,
               "output_bytes": total_bytes, "cases": summaries}
    (output/"validation-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False))
    print("VALIDATION_OUTPUT", output, "seconds", summary["elapsed_seconds"], "bytes", total_bytes, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fred-dir", type=Path, required=True)
    parser.add_argument("--ebs-file", type=Path, required=True)
    parser.add_argument("--stock-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.fred_dir, args.ebs_file, args.stock_dir, args.output)
