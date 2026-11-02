"""Explicit time sampling; never join returns across missing grid points."""
from dataclasses import dataclass
from pathlib import Path
from numbers import Integral

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class AnalysisConfig:
    frequency: str = "5min"
    timezone: str | None = None
    max_staleness: str = "0s"
    sampling: str = "grid"
    observation_unit: str | None = None
    session_policy: str = "date"
    max_lag: int = 30
    min_pairs: int = 20
    max_grid_points: int = 2_000_000
    price_type: str = "unspecified"
    aggregation_factors: tuple[int, ...] = (1, 5, 10, 20)
    rms_window: int = 20
    burst_threshold: float = 3.0

    def validate(self):
        for name in ["max_lag", "min_pairs", "max_grid_points", "rms_window"]:
            if isinstance(getattr(self, name), bool) or not isinstance(getattr(self, name), Integral):
                raise ValueError(f"{name} 必须为整数")
        factors = self.aggregation_factors
        if not factors or len(factors) > 12 or any(isinstance(x, bool) or not isinstance(x, Integral) or x < 1 or x > 10000 for x in factors):
            raise ValueError("aggregation_factors 需为 1–10000 的正整数，最多 12 项")
        if list(factors) != sorted(set(factors)) or factors[0] != 1:
            raise ValueError("aggregation_factors 必须从 1 开始、严格递增")
        if self.rms_window < 2 or not np.isfinite(self.burst_threshold) or self.burst_threshold <= 0:
            raise ValueError("rms_window 至少为 2；burst_threshold 必须有限且为正")
        if self.sampling not in {"grid", "observations"}:
            raise ValueError("sampling 必须是 grid 或 observations")
        if self.session_policy not in {"date", "continuous"}:
            raise ValueError("session_policy 必须是 date 或 continuous")
        if self.max_lag < 1 or self.max_lag > 2000:
            raise ValueError("max_lag 必须在 1–2000 之间")
        if self.min_pairs < 2 or self.max_grid_points < 1:
            raise ValueError("min_pairs 至少为 2；max_grid_points 必须为正")
        if self.sampling == "observations" and not self.observation_unit:
            raise ValueError("observations 模式必须声明 observation_unit，例如 trading-day")
        if self.timezone:
            try:
                pd.Timestamp("2024-01-01").tz_localize(self.timezone)
            except Exception as exc:
                raise ValueError("无法识别 timezone") from exc
        try:
            step = pd.Timedelta(self.frequency)
            stale = pd.Timedelta(self.max_staleness)
        except (ValueError, TypeError) as exc:
            raise ValueError("frequency 和 max_staleness 必须是固定时长，例如 5min、30s") from exc
        if pd.isna(step) or pd.isna(stale) or step <= pd.Timedelta(0) or stale < pd.Timedelta(0):
            raise ValueError("采样间隔必须为正，价格沿用时长不能为负")


def _timestamps(values, timezone):
    if values.isna().any() or values.str.fullmatch(r"[+-]?\d+(\.\d+)?").any():
        raise ValueError("timestamp 需要明确的日期时间，不接受空值或未说明单位的数字时间")
    try:
        parsed = [pd.Timestamp(s) for s in values]
        if any(pd.isna(t) for t in parsed):
            raise ValueError("missing timestamp")
        aware = [t.tzinfo is not None for t in parsed]
        if any(aware) and not all(aware):
            raise ValueError("不能混用带时区和不带时区的 timestamp")
        if not any(aware):
            if timezone is None:
                raise ValueError("无时区的 timestamp 必须通过 timezone 明确时区")
            return pd.DatetimeIndex(parsed).tz_localize(timezone, ambiguous="raise", nonexistent="raise").tz_convert("UTC")
        return pd.to_datetime(values, format="mixed", utc=True)
    except Exception as exc:
        raise ValueError(f"timestamp 无效或时区不明确：{exc}") from exc


def read_prices(path: str | Path, config: AnalysisConfig) -> pd.DataFrame:
    """Read canonical CSV columns; all identifiers are preserved as strings."""
    config.validate()
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if frame.empty or not {"timestamp", "price"}.issubset(frame.columns):
        raise ValueError("CSV 必须包含 timestamp、price，且至少有一行数据")
    frame["timestamp"] = _timestamps(frame["timestamp"], config.timezone)
    try:
        frame["price"] = pd.to_numeric(frame["price"], errors="raise").astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError("price 必须为数值；请先明确处理源数据中的缺失值") from exc
    if not np.isfinite(frame["price"]).all() or (frame["price"] <= 0).any():
        raise ValueError("price 必须全部有限且大于零，不自动删除异常行")
    for column, default in [("asset_id", "series"), ("path_id", "observed")]:
        if column not in frame:
            frame[column] = default
        if frame[column].str.strip().eq("").any():
            raise ValueError(f"{column} 不能留空")
    if "session_id" not in frame:
        if config.sampling == "grid" and config.session_policy == "date":
            frame["session_id"] = frame["timestamp"].dt.tz_convert(config.timezone or "UTC").dt.strftime("%Y-%m-%d")
        else:
            frame["session_id"] = "continuous"
    if frame["session_id"].str.strip().eq("").any():
        raise ValueError("session_id 不能留空")
    return frame


def sample_path(frame: pd.DataFrame, config: AnalysisConfig):
    """Sample a single asset/path, keeping session boundaries and grid gaps."""
    config.validate()
    if frame[["asset_id", "path_id"]].drop_duplicates().shape[0] != 1:
        raise ValueError("sample_path 每次只接受一个资产的一条路径")
    step, tolerance = pd.Timedelta(config.frequency), pd.Timedelta(config.max_staleness)
    chunks, duplicates, total = [], 0, 0
    for session, group in frame.groupby("session_id", sort=False):
        group = group.sort_values("timestamp", kind="stable")
        duplicate_count = int(group["timestamp"].duplicated().sum())
        duplicates += duplicate_count
        if config.sampling == "observations":
            if duplicate_count:
                raise ValueError("observations 模式不允许同一 session 出现重复 timestamp")
            sampled = group[["timestamp", "price"]].copy()
            sampled["age_seconds"] = 0.0
        else:
            # Stable ordering makes the last input row at a tie explicit.
            group = group.drop_duplicates("timestamp", keep="last")
            start = group["timestamp"].iloc[0].ceil(step)
            end = group["timestamp"].iloc[-1].floor(step)
            count = max(0, int((end - start) // step) + 1)
            if total + count > config.max_grid_points:
                raise ValueError("采样网格超过 max_grid_points；请增大间隔或缩短输入时段")
            if count == 0:
                continue
            grid = pd.DataFrame({"timestamp": pd.date_range(start, end, freq=step)})
            source = group[["timestamp", "price"]].rename(columns={"timestamp": "source_time"})
            sampled = pd.merge_asof(grid, source, left_on="timestamp", right_on="source_time", direction="backward", tolerance=tolerance)
            sampled["age_seconds"] = (sampled["timestamp"] - sampled["source_time"]).dt.total_seconds()
            sampled = sampled.drop(columns="source_time")
        total += len(sampled)
        if total > config.max_grid_points:
            raise ValueError("输入观测数超过 max_grid_points")
        sampled["session_id"] = str(session)
        sampled["carried"] = sampled["age_seconds"].gt(0)
        sampled["log_return"] = np.log(sampled["price"]).diff()
        chunks.append(sampled)
    columns = ["timestamp", "price", "age_seconds", "session_id", "carried", "log_return"]
    sampled = pd.concat(chunks, ignore_index=True)[columns] if chunks else pd.DataFrame(columns=columns)
    meta = {
        "input_rows": len(frame), "sampled_points": len(sampled), "sessions": len(chunks),
        "duplicate_rows_last_wins": duplicates,
        "missing_prices": int(sampled["price"].isna().sum()),
        "carried_prices": int(sampled["carried"].sum()),
        "valid_returns": int(sampled["log_return"].notna().sum()),
        "start": str(frame["timestamp"].min()), "end": str(frame["timestamp"].max()),
    }
    return sampled, meta
