"""Generate reports from the real market snapshots included in this repository."""
import argparse
from dataclasses import replace
import json
from pathlib import Path

from financial_stylized_facts.adapters import daily_csv, file_sha256, write_prepared
from financial_stylized_facts.report import analyze_csv


DATA = Path(__file__).resolve().parents[1] / "data" / "examples"


def load_cases(dataset, data_dir=DATA):
    """Validate every selected snapshot before creating any output."""
    data_dir = Path(data_dir)
    catalog = json.loads((data_dir / "manifest.json").read_text(encoding="utf-8"))
    datasets = catalog["datasets"]
    names = list(datasets) if dataset == "all" else [dataset]
    cases = []
    for name in names:
        if name not in datasets:
            raise ValueError(f"Unknown dataset: {name}")
        entry = datasets[name]
        source = data_dir / entry["file"]
        if file_sha256(source) != entry["sha256"]:
            raise ValueError(f"Snapshot checksum mismatch: {name}")
        frame, config, info = daily_csv(
            source, asset=entry["asset"], date_column=entry["date_column"],
            price_column=entry["price_column"], price_type=entry["price_type"],
            volume_column=entry["volume_column"], volume_unit=entry["volume_unit"],
            missing_policy=entry["missing_policy"], source_name=entry["source_name"],
        )
        if info["selected_source_rows"] != entry["rows"]:
            raise ValueError(f"Snapshot row count mismatch: {name}")
        info.update(source_url=entry["source_url"], data_license=entry["license"],
                    license_url=entry["license_url"], attribution=entry["attribution"],
                    upstream_sha256=entry["source_sha256"], retrieved_on=catalog["retrieved_on"])
        info["notes"] += entry["notes"]
        # Fixed settings across assets; no parameter selection based on results.
        config = replace(config, max_lag=30, volatility_max_lag=100, coarse_factor=5,
                         bootstrap_reps=399, garch_max_points=10000, garch_max_segments=4)
        cases.append((name, source, frame, config, info))
    return cases


def run(dataset, output, data_dir=DATA):
    output = Path(output)
    if output.exists():
        raise FileExistsError(f"Output already exists: {output}")
    cases = load_cases(dataset, data_dir)
    output.mkdir(parents=True, exist_ok=False)
    summary = []
    for name, source, frame, config, info in cases:
        prepared, report = output / name / "input", output / name / "report"
        manifest = write_prepared(frame, config, info, source=source, output=prepared)
        result = analyze_csv(prepared / "prices.csv", report, config,
                             title=f"{name} · 真实市场统计报告", source_provenance=manifest)
        group = result["groups"][0]
        summary.append({"dataset": name, "source_sha256": info["source_sha256"],
                        "canonical_sha256": manifest["canonical_sha256"],
                        "n_returns": group["distribution"]["n"],
                        "excess_kurtosis": group["distribution"]["excess_kurtosis"],
                        "report": f"{name}/report/index.html"})
        print(f"{name}: {report / 'index.html'}", flush=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", choices=["AAPL", "MSFT", "EURUSD", "USDJPY", "all"], default="AAPL")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        run(args.dataset, args.output)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"{exc}\n")


if __name__ == "__main__":
    main()
