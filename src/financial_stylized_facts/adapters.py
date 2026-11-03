"""Read-only source conversion, explicit missingness and auditable provenance.

These adapters interpret particular CSV schemas. They do not download data,
infer exchange calendars, repair corporate actions, or grant redistribution rights.
"""
from dataclasses import asdict
import hashlib
from io import BytesIO
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .data import AnalysisConfig


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_csv(path):
    raw = Path(path).read_bytes()
    return pd.read_csv(BytesIO(raw), dtype=str, keep_default_na=False), hashlib.sha256(raw).hexdigest()


def _dates(values, fmt):
    try:
        dates = pd.to_datetime(values, format=fmt, errors="raise")
    except (ValueError, TypeError) as exc:
        raise ValueError(f"日期格式应为 {fmt}") from exc
    if dates.isna().any() or dates.duplicated().any():
        raise ValueError("日频日期不允许空白或重复")
    return dates


def _number(values, *, missing=False, positive=True):
    values = values.str.strip()
    if missing:
        values = values.replace({"": np.nan, ".": np.nan})
    try:
        numbers = pd.to_numeric(values, errors="raise").astype(float)
    except (ValueError, TypeError) as exc:
        raise ValueError("数值列含无法识别的内容；仅空白和 . 是允许的缺失标记") from exc
    if np.isinf(numbers).any() or (numbers <= 0 if positive else numbers < 0).any() or (not missing and numbers.isna().any()):
        raise ValueError("价格必须有限且为正；成交量必须有限且非负")
    return numbers


def _range(frame, start, end):
    # User boundaries are inclusive calendar dates in the source's own date field.
    dates = frame.pop("_date")
    selected = pd.Series(True, index=frame.index)
    for value, lower in [(start, True), (end, False)]:
        if value is not None:
            try:
                boundary = pd.Timestamp(value)
                if boundary.tzinfo is not None or boundary != boundary.normalize():
                    raise ValueError()
            except (ValueError, TypeError) as exc:
                raise ValueError("start/end 需为无时区的日期 YYYY-MM-DD") from exc
            selected &= dates >= boundary if lower else dates <= boundary
    frame = frame.loc[selected].copy()
    if frame.empty:
        raise ValueError("指定资产和日期范围没有数据")
    return frame


def daily_csv(path, *, asset, date_column, price_column, price_type,
              volume_column=None, volume_unit=None, missing_policy="preserve",
              start=None, end=None, date_format="%Y-%m-%d", source_name="用户日频 CSV"):
    """Convert daily labelled observations; midnight UTC is a date label, not a trade time."""
    if missing_policy not in {"preserve", "available"}:
        raise ValueError("missing_policy 必须为 preserve 或 available")
    if not asset or not price_type or bool(volume_column) != bool(volume_unit):
        raise ValueError("必须说明资产、价格类型；成交量列和单位必须同时提供")
    raw, source_hash = _source_csv(path)
    required = {date_column, price_column} | ({volume_column} if volume_column else set())
    if not required.issubset(raw.columns) or raw.empty:
        raise ValueError(f"缺少必要列：{sorted(required)}，或文件为空")
    dates = _dates(raw[date_column], date_format)
    frame = pd.DataFrame({"_date": dates, "timestamp": dates.dt.tz_localize("UTC"),
                          "price": _number(raw[price_column], missing=True),
                          "asset_id": asset, "path_id": "observed", "session_id": "daily-series"})
    if volume_column:
        frame["volume"] = _number(raw[volume_column], missing=True, positive=False)
    frame = _range(frame, start, end).sort_values("timestamp", kind="stable")
    missing = int(frame.price.isna().sum())
    selected_rows = len(frame)
    if missing_policy == "available":
        frame = frame.loc[frame.price.notna()].copy()
    if frame.price.notna().sum() < 2:
        raise ValueError("至少需要两个有效价格")
    unit = "source-date-slot" if missing_policy == "preserve" else "available-price-observation"
    config = AnalysisConfig(frequency="1d", sampling="observations", observation_unit=unit,
                            session_policy="continuous", price_type=price_type,
                            allow_missing_prices=missing_policy == "preserve",
                            volume_kind="interval" if volume_column else "none", volume_unit=volume_unit)
    notes = ["UTC 零点只是源日期标签，不是实际成交或收盘时刻。",
             "未补交易日历；源文件未出现的日期不会自动补行，lag 按源观测序号计。",
             "不插值、不沿用价格；复权规则和数据使用权须以提供方说明为准。"]
    notes.append("保留显式缺失槽，缺口两侧不计算收益。" if missing_policy == "preserve" else
                 "明确移除无价格日期；收益跨越相邻可用报价，可能涵盖不同日历时长，不等于固定一天收益。")
    if volume_column:
        notes.append("成交量对应源日期；与跨休市日收益配对，不补休市日成交量，也不推断量是否复权。")
    info = {"source_name": source_name, "adapter": "daily_csv", "source_sha256": source_hash, "date_column": date_column,
            "price_column": price_column, "price_type": price_type, "volume_column": volume_column,
            "volume_unit": volume_unit, "missing_policy": missing_policy, "selected_source_rows": selected_rows,
            "missing_source_prices": missing, "rows_removed": selected_rows-len(frame), "notes": notes}
    return frame.reset_index(drop=True), config, info


def fred_csv(path, *, series, missing_policy="preserve", start=None, end=None):
    definitions = {"DEXUSEU": ("EUR/USD", "纽约中午参考汇率：USD per EUR"),
                   "DEXJPUS": ("USD/JPY", "纽约中午参考汇率：JPY per USD")}
    if series not in definitions:
        raise ValueError("此 FRED 适配器目前只核对 DEXUSEU 与 DEXJPUS；其他系列请用 daily_csv 明确字段")
    asset, price_type = definitions[series]
    frame, config, info = daily_csv(path, asset=asset, date_column="observation_date", price_column=series,
                                    price_type=price_type, missing_policy=missing_policy, start=start, end=end,
                                    source_name=f"Federal Reserve H.10 / FRED {series}")
    info.update(adapter="fred", series=series, source_url=f"https://fred.stlouisfed.org/series/{series}")
    return frame, config, info


def ebs_tick_csv(path, *, pair, frequency="5min", max_staleness="5min", start=None, end=None):
    """Use only D / Last Trade; no invented volume or individual-order reconstruction."""
    raw, source_hash = _source_csv(path)
    required = {"Date", "Time", "Currency Pair", "Event Type", "Side", "Last Trade"}
    if not required.issubset(raw.columns):
        raise ValueError("不是已核对的 CME EBS Tick CSV 字段格式")
    pair_rows = raw[raw["Currency Pair"].str.strip().eq(pair)]
    if not pair_rows["Event Type"].str.strip().isin(["D", "Q"]).all():
        raise ValueError("EBS 记录含未知 Event Type")
    deals = pair_rows[pair_rows["Event Type"].str.strip().eq("D")].copy()
    if deals.empty:
        raise ValueError("指定货币对没有 D 成交记录")
    if not deals.Side.str.strip().isin(["G", "P"]).all():
        raise ValueError("D 记录 Side 必须为 G 或 P")
    if not deals.Time.str.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?").all():
        raise ValueError("EBS Time 必须是 GMT HH:MM:SS（可带小数秒）")
    try:
        dates = pd.to_datetime(deals.Date, format="%Y/%m/%d", errors="raise")
        timestamps = pd.to_datetime(deals.Date + " " + deals.Time, format="mixed", utc=True, errors="raise")
        if dates.isna().any() or timestamps.isna().any():
            raise ValueError()
    except (ValueError, TypeError) as exc:
        raise ValueError("EBS GMT 日期时间无效") from exc
    frame = pd.DataFrame({"_date": dates, "timestamp": timestamps,
                          "price": _number(deals["Last Trade"]), "asset_id": pair,
                          "path_id": "observed", "session_id": "ebs-file"})
    frame = _range(frame, start, end).sort_values("timestamp", kind="stable").reset_index(drop=True)
    config = AnalysisConfig(frequency=frequency, max_staleness=max_staleness, session_policy="continuous",
                            price_type="EBS Tick D / Last Trade（记录成交价）")
    config.validate()
    info = {"adapter": "ebs_tick", "source_name": "CME EBS Spot FX Tick", "source_sha256": source_hash, "pair": pair,
            "source_url": "https://cmegroupclientsite.atlassian.net/wiki/spaces/EPICSANDBOX/pages/457573144/EBS+Spot+FX",
            "selected_source_rows": len(frame), "missing_source_prices": 0, "rows_removed": 0,
            "same_timestamp_extra_rows": int(frame.timestamp.duplicated().sum()),
            "notes": ["只使用 D 记录的 Last Trade，时间保留原始精度并按 GMT/UTC 解释。",
                      "这是时间片数据的成交价记录，不宣称每行是一张订单；Tick 没有成交量，量价模块不可用。",
                      "同时间价格按原文件行顺序取最后一条，不能从该顺序恢复真实微观成交先后。",
                      f"固定网格向后取价，最多沿用 {max_staleness}；无合格价格则保留缺失，不用未来价格回填。",
                      "整个文件作为一个 session，避免 GMT 午夜人为截断；未提供交易日历，跨周末文件需先划分 session。"]}
    return frame, config, info


def write_prepared(frame, config, info, *, source, output):
    """Write into a NEW directory only, never over raw input; emit a replayable manifest."""
    source, output = Path(source), Path(output)
    digest = file_sha256(source)
    if info.get("source_sha256") != digest:
        raise ValueError("源文件自读取后发生变化，或来源清单不匹配；未写转换结果")
    config.validate()
    output.mkdir(parents=True, exist_ok=False)
    canonical = output / "prices.csv"
    frame.to_csv(canonical, index=False)
    manifest = {"schema_version": "1", **info, "source_file_name": source.name,
                "source_sha256": digest, "canonical_sha256": file_sha256(canonical),
                "output_rows": len(frame), "start": str(frame.timestamp.min()), "end": str(frame.timestamp.max()),
                "analysis_config": asdict(config)}
    (output/"provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return manifest
