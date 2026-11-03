from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import brentq
import statsmodels.api as sm
from statsmodels.stats.sandwich_covariance import cov_hac

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.long_memory import bridge_range_tails, modified_rs, long_memory_diagnostics


def frame(x, sessions=None):
    return pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=len(x),freq="min",tz="UTC"),
                         "session_id":"s" if sessions is None else sessions,"log_return":x})


def test_hand_range_and_bartlett_covariance():
    # centered [-1.5,-.5,.5,1.5], range=2, gamma0=1.25, gamma1=.3125.
    assert modified_rs([1,2,3,4],0)["statistic"] == pytest.approx(2/np.sqrt(5))
    assert modified_rs([1,2,3,4],1)["statistic"] == pytest.approx(.8)


@pytest.mark.parametrize("q",[0,1,10,40])
def test_variance_independently_matches_statsmodels(q):
    x=np.random.default_rng(57).normal(size=1300)
    fitted=sm.OLS(x,np.ones((len(x),1))).fit()
    var_mean=cov_hac(fitted,nlags=q,use_correction=False)[0,0]
    expected=np.ptp(np.r_[0,np.cumsum(x-x.mean())])/(len(x)*np.sqrt(var_mean))
    assert modified_rs(x,q)["statistic"] == pytest.approx(expected,rel=2e-13)


def test_limit_critical_values_match_published_table_and_stable_tails():
    # Lo's 95% equal-tailed range, reproduced in Gould et al. (2016), Appendix B.3.
    quantiles=[brentq(lambda v:bridge_range_tails(v)[0]-p,.1,4) for p in [.025,.975]]
    assert quantiles == pytest.approx([.809,1.862],abs=.0005)
    values=np.geomspace(.01,20,1000)
    cdf=np.array([bridge_range_tails(v)[0] for v in values])
    assert np.all(np.diff(cdf)>=-1e-15)
    for v in [.1,.8,1-1e-10,1.,1+1e-10,2,4,20,21]:
        a,b=bridge_range_tails(v)
        assert 0<=a<=1 and 0<=b<=1 and a+b==pytest.approx(1)
    assert bridge_range_tails(.9999999999)[0] == pytest.approx(bridge_range_tails(1.)[0],abs=1e-9)
    assert bridge_range_tails(4)[1]>0  # Avoid 1-CDF cancellation.


def test_affine_scale_and_time_reversal_invariance():
    x=np.random.default_rng(32).normal(size=1000)
    expected=modified_rs(x,20)["statistic"]
    for y in [x[::-1],x*1e150,x*1e-150,-2*x+3]:
        assert modified_rs(y,20)["statistic"]==pytest.approx(expected,rel=1e-12)
    assert modified_rs(np.ones(1000),20)["statistic"] is None
    for y in [[1,np.nan],[1,np.inf],[[1,2]],[]]:
        with pytest.raises(ValueError):
            modified_rs(y,0)
    with pytest.raises(ValueError):
        modified_rs(x,1000)


def test_gaps_and_sessions_are_not_joined_and_windows_are_prespecified():
    x=np.r_[np.ones(300),np.nan,np.ones(300)*2,np.ones(600)*3]
    data=frame(x,["a"]*601+["b"]*600)
    result=long_memory_diagnostics(data,AnalysisConfig())
    whole=[r for r in result["rows"] if r["partition"]==1 and r["bandwidth"]==0]
    assert [r["n"] for r in whole]==[300,300,600]
    assert [r["session_id"] for r in whole]==["a","a","b"]
    assert result["planned_family_size"]==3*7*3
    assert all(r["statistic"] is None for r in result["rows"])
    assert data.log_return.isna().sum()==1


def test_family_includes_unavailable_windows_but_q0_is_reference_only():
    x=np.random.default_rng(101).normal(size=1200)
    result=long_memory_diagnostics(frame(x),AnalysisConfig())
    assert result["planned_windows"]==7 and result["planned_family_size"]==21
    assert result["computed_tests"]==7  # whole 3, half 2 each, quarters too short.
    for r in result["rows"]:
        if r["status"]=="computed" and not r["reference_only"]:
            assert r["family_adjusted_p"]==min(1,21*r["asymptotic_p"])
        else:
            assert r["family_adjusted_p"] is None
    assert result["verified_long_memory"] is False


def test_regime_break_can_reject_without_being_long_memory():
    rng=np.random.default_rng(817)
    x=rng.normal(size=12000)*np.repeat([1,5],6000)
    result=long_memory_diagnostics(frame(x),AnalysisConfig())
    full=[r for r in result["rows"] if r["partition"]==1 and not r["reference_only"]]
    half=[r for r in result["rows"] if r["partition"]==2 and not r["reference_only"]]
    assert all(r["reject_short_memory_family"] and r["position"]=="above" for r in full)
    assert not any(r["reject_short_memory_family"] for r in half)
    assert result["verified_long_memory"] is False


def test_disabled_budget_empty_and_reference_only_have_reasons():
    data=frame(np.random.default_rng(2).normal(size=600))
    cfg=AnalysisConfig()
    for field,val in [("long_memory_max_work",1),("long_memory_max_windows",1)]:
        result=long_memory_diagnostics(data,replace(cfg,**{field:val}))
        assert result["status"]=="budget_exceeded" and not result["rows"] and result["reason"]
    assert long_memory_diagnostics(data,replace(cfg,long_memory="off"))["status"]=="disabled"
    assert long_memory_diagnostics(frame([np.nan]*5),cfg)["status"]=="insufficient_data"
    result=long_memory_diagnostics(data,replace(cfg,long_memory_bandwidths=(0,)))
    assert result["status"]=="reference_only" and result["planned_family_size"]==0


@pytest.mark.parametrize("kwargs",[{"long_memory_bandwidths":(40,10)}, {"long_memory_bandwidths":(True,)},
    {"long_memory_bandwidths":()}, {"long_memory_min_points":5}, {"long_memory_min_points":True},
    {"long_memory_max_work":0}, {"long_memory_max_windows":2049}, {"long_memory":"auto"}])
def test_configuration_rejects_ambiguous_or_unbounded_inputs(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs).validate()


def test_probability_underflow_is_an_explicit_conservative_bound():
    # Alternation has bounded partial sums, driving V almost to zero.
    result=modified_rs(np.tile([0.,1.],10000),0)
    assert result["asymptotic_p"]==1e-300
    assert result["p_is_numerical_upper_bound"] is True


def test_audit_fgn_generator_has_the_prescribed_finite_covariance():
    from examples.validate_long_memory import fractional_gaussian_noise
    n,h=128,.8
    class Basis:
        def __init__(self,index):
            self.index=index
        def normal(self,size):
            z=np.zeros(size)
            z[self.index]=1.
            return z
    transform=np.column_stack([fractional_gaussian_noise(Basis(i),n,h) for i in range(2*n)])
    k=np.abs(np.arange(n)[:,None]-np.arange(n)[None,:]).astype(float)
    target=.5*((k+1)**(2*h)-2*k**(2*h)+np.abs(k-1)**(2*h))
    np.testing.assert_allclose(transform@transform.T,target,atol=2e-13)
