import numpy as np
import pytest
from financial_stylized_facts.absolute_decay import loglog_decay
from financial_stylized_facts.data import AnalysisConfig


def test_pairs_do_not_bridge_a_gap_and_use_pearson():
    x = np.array([1.,2.,4.,3.,5.,7.,np.nan,9.,2.,7.,3.,1.,4.])
    result = loglog_decay([x], AnalysisConfig(volatility_max_lag=6, min_pairs=2, decay_bootstrap_reps=0))
    row = result["rows"][1]
    left = np.r_[x[:4],x[7:11]]
    right = np.r_[x[2:6],x[9:13]]
    assert row["pairs"] == 8
    assert row["acf"] == pytest.approx(np.corrcoef(left,right)[0,1])
    assert result["conclusion"] == "insufficient_data"


def test_negative_lags_preclude_log_fit():
    x = np.tile([1.,2.],100)
    result = loglog_decay([x], AnalysisConfig(volatility_max_lag=20, decay_bootstrap_reps=0))
    assert result["beta"] is None and result["conclusion"] == "mixed"
    assert result["rows"][4]["acf"] == pytest.approx(-1)
