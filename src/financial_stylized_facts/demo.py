"""Packaged, reproducible synthetic demos; no market downloads or fitted claims."""
from dataclasses import asdict
import json
from numbers import Integral
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__
from .adapters import file_sha256
from .data import AnalysisConfig
from .report import analyze_csv


def synthetic_prices(seed=20261102,n=5000):
    rng=np.random.default_rng(seed)
    gaussian=rng.normal(size=n)
    heavy=rng.standard_t(5,size=n)*np.sqrt(3/5)
    shocks=rng.normal(size=n+1000)
    clustered=np.empty(n+1000)
    variance=1.
    for i,shock in enumerate(shocks):
        clustered[i]=np.sqrt(variance)*shock
        variance=.05+.1*clustered[i]**2+.85*variance
    asymmetric=rng.exponential(size=n)-1
    innovations=rng.normal(size=n+1)
    leverage=innovations[1:]*(1-.5*np.tanh(innovations[:-1]))
    frames=[]
    for label,returns in [("Gaussian iid",gaussian),("Student-t iid",heavy),
                          ("GARCH Gaussian",clustered[1000:]),("Skewed iid",asymmetric),("Leverage toy",leverage)]:
        frames.append(pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=n+1,freq="min",tz="UTC"),
            "price":100*np.exp(np.r_[0,np.cumsum(returns*.001)]),"asset_id":label,
            "path_id":"seed-"+str(seed),"session_id":"simulation"}))
    return pd.concat(frames,ignore_index=True)


def activity_prices(seed=20261103,n_blocks=1200):
    rng=np.random.default_rng(seed)
    coarse=rng.uniform(0,1,n_blocks)
    fine=np.r_[1.,1+coarse[:-1]]
    returns=.001*np.column_stack([fine+coarse/2,coarse/2-fine]).ravel()
    volume=1000+2e5*np.abs(returns)+rng.uniform(0,50,len(returns))
    frames=[]
    for label,r,v in [("Coarse leads fine",returns,volume),("Time reversed",returns[::-1],volume[::-1])]:
        frames.append(pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=len(r)+1,freq="min",tz="UTC"),
            "price":100*np.exp(np.r_[0,r.cumsum()]),"volume":np.r_[np.nan,v],
            "asset_id":"Constructed process","path_id":label,"session_id":"simulation"}))
    return pd.concat(frames,ignore_index=True)


def run_demo(output,kind="basic",seed=20261102,observations=2400):
    """Create a new demo directory, its input/manifest, and a portable HTML report."""
    if kind not in {"basic","activity"}:
        raise ValueError("demo kind 必须为 basic 或 activity")
    if isinstance(seed,bool) or not isinstance(seed,Integral) or not 0<=seed<=2**32-1:
        raise ValueError("demo seed 必须为 0–4294967295 的整数")
    if isinstance(observations,bool) or not isinstance(observations,Integral) or not 512<=observations<=10000:
        raise ValueError("demo observations 必须为 512–10000 的整数")
    if kind=="activity" and observations%2:
        raise ValueError("activity demo 的 observations 必须为偶数，保持两步聚合对齐")
    output=Path(output)
    output.mkdir(parents=True,exist_ok=False)
    frame=synthetic_prices(seed,observations) if kind=="basic" else activity_prices(seed,observations//2)
    config=AnalysisConfig(frequency="1min",price_type="synthetic",session_policy="continuous",
                          **({"coarse_factor":2,"volume_kind":"interval","volume_unit":"synthetic-units"} if kind=="activity" else {}))
    input_path=output/"prices.csv"
    frame.to_csv(input_path,index=False)
    digest=file_sha256(input_path)
    manifest={"source_name":"包内合成演示（不是市场行情）","source_sha256":digest,"canonical_sha256":digest,
        "selected_source_rows":len(frame),"missing_source_prices":0,"rows_removed":0,
        "notes":["数据由固定种子在本地生成，没有下载市场数据，也不是对真实市场的拟合。",
                 "basic 包括独立高斯、t(5)、Gaussian GARCH、偏态独立收益和负冲击后增大波动的示意过程。" if kind=="basic" else
                 "activity 的量价关系与粗细时间方向由公式刻意构造；同时展示原序列和时间反转，不能当作真实市场证据。",
                 "每条路径单独分析；这些过程不要求同时符合所有事实，有限样本、带宽与拟合会影响结果。"],
        "generator":{"kind":kind,"seed":seed,"observations_per_path":observations,"package_version":__version__},
        "analysis_config":asdict(config)}
    (output/"demo.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    return analyze_csv(input_path,output/"report",config,title="金融统计事实 · 合成演示",source_provenance=manifest)
