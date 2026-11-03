"""Audit report R/S numerators and denominators independently with statsmodels."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_hac

from financial_stylized_facts.data import AnalysisConfig,read_prices,sample_path


def audit(inputs,outputs):
    rows=[]
    for case in sorted(Path(outputs).glob("*/report/results.json")):
        result=json.loads(case.read_text())
        config=AnalysisConfig(**result["config"])
        raw=read_prices(Path(inputs)/case.parent.parent.name/"input/prices.csv",config)
        worst=0.
        checked=0
        for group in result["groups"]:
            subset=raw[(raw.asset_id==group["asset_id"])&(raw.path_id==group["path_id"])]
            sampled,_=sample_path(subset,config)
            memory=group["volatility_persistence"]["long_memory_test"]
            for r in memory["rows"]:
                if r["status"]!="computed":
                    assert r["statistic"] is None and r["family_adjusted_p"] is None
                    continue
                block=sampled[(sampled.session_id==r["session_id"]) &
                              (sampled.timestamp>=pd.Timestamp(r["start"])) &
                              (sampled.timestamp<=pd.Timestamp(r["end"]))]
                x=np.abs(block.log_return.to_numpy())
                assert np.isfinite(x).all() and len(x)==r["n"]
                model=sm.OLS(x,np.ones((len(x),1))).fit()
                mean_variance=cov_hac(model,nlags=r["bandwidth"],use_correction=False)[0,0]
                expected=np.ptp(np.r_[0,np.cumsum(x-x.mean())])/(len(x)*np.sqrt(mean_variance))
                error=abs(expected-r["statistic"])
                assert error<1e-9,(case,r,error)
                worst=max(worst,error)
                checked+=1
                if not r["reference_only"]:
                    assert r["family_adjusted_p"]==min(1,r["asymptotic_p"]*memory["planned_family_size"])
        rows.append({"case":case.parent.parent.name,"checked_statistics":checked,"max_error":worst})
    assert rows
    Path(outputs,"long-memory-audit.json").write_text(json.dumps({"passed":True,"rows":rows},indent=2))
    return rows
