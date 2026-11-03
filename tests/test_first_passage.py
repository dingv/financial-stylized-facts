from dataclasses import replace
import itertools

import numpy as np
import pandas as pd
import pytest

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.first_passage import first_hit_steps, first_passage_diagnostics, path_extrema


def sampled(logs, sessions=None):
    logs=np.asarray(logs,float)
    frame=pd.DataFrame({"timestamp":pd.date_range("2024-01-01",periods=len(logs),freq="min",tz="UTC"),
                        "price":np.exp(logs),"session_id":sessions if sessions is not None else "one"})
    frame["log_return"]=frame.groupby("session_id",sort=False).price.transform(lambda x:np.log(x).diff())
    return frame


def config(**kwargs):
    return AnalysisConfig(first_passage_unit="log_return",first_passage_thresholds=(.5,),
                          first_passage_horizon=3,first_passage_min_starts=2,**kwargs)


def test_first_hits_include_exact_boundary_and_do_not_compete():
    up,down,follow=first_hit_steps(np.array([0.,1.,0.,-1.,0.,1.]),1.,3)
    np.testing.assert_array_equal(up,[1,0,3,1,1,0])
    np.testing.assert_array_equal(down,[3,1,1,0,0,0])
    np.testing.assert_array_equal(follow,[3,3,3,2,1,0])
    # The first start hits both sides, even though it reaches the gain first.
    assert up[0]==1 and down[0]==3


def test_hand_counts_fixed_cohort_and_censor_bounds():
    r=first_passage_diagnostics(sampled([0,1,0,-1,0,1]),config())
    assert r["status"]=="computed" and r["full_horizon_starts"]==3
    up,down=r["thresholds"][0]["up"],r["thresholds"][0]["down"]
    assert [x["full_cdf"] for x in up["curve"]]==pytest.approx([1/3,1/3,2/3])
    assert up["full_median_steps"]==3 and down["full_median_steps"]==1
    assert (up["observed_hits"],up["horizon_censored"],up["early_censored"])==(4,1,1)
    assert (down["observed_hits"],down["horizon_censored"],down["early_censored"])==(3,0,3)
    assert up["curve"][-1]["all_start_lower_bound"]==pytest.approx(4/6)
    assert up["curve"][-1]["all_start_upper_bound"]==pytest.approx(5/6)
    assert down["curve"][-1]["all_start_upper_bound"]==1.
    for d in [up,down]:
        assert d["all_starts"]==d["observed_hits"]+d["early_censored"]+d["horizon_censored"]
    # Censor exactly at h still provides negative information through h.
    assert down["curve"][0]["early_censored"]==1


def test_all_start_bounds_contain_every_enumerated_unobserved_continuation():
    observed=np.array([0.,1.,0.,-1.,0.])
    r=first_passage_diagnostics(sampled(observed),config())["thresholds"][0]
    for continuation in itertools.product([-1.,0.,1.],repeat=3):
        completed=np.r_[observed,observed[-1]+np.cumsum(continuation)]
        up,down,_=first_hit_steps(completed,.5,3)
        for name,hits in [("up",up),("down",down)]:
            for row in r[name]["curve"]:
                p=np.mean((hits[:len(observed)]>0)&(hits[:len(observed)]<=row["horizon"]))
                assert row["all_start_lower_bound"]<=p<=row["all_start_upper_bound"]


def test_no_hit_by_horizon_is_not_a_fake_median_or_dropped_denominator():
    r=first_passage_diagnostics(sampled(np.zeros(10)),config())
    assert r["status"]=="computed"
    for side in ["up","down"]:
        d=r["thresholds"][0][side]
        assert d["full_hit_probability"]==0 and d["full_median_steps"] is None
        assert d["full_horizon_nonhits"]==7
        assert d["horizon_censored"]==7 and d["early_censored"]==3


def test_missing_price_and_session_breaks_do_not_create_hits():
    r=first_passage_diagnostics(sampled([0,0,np.nan,2,2,4,4],['a']*5+['b']*2),config())
    assert r["segment_count"]==3 and r["all_starts"]==6
    assert r["full_horizon_starts"]==0 and r["status"]=="partially_computed"
    for side in ["up","down"]:
        d=r["thresholds"][0][side]
        assert d["observed_hits"]==0 and d["full_hit_probability"] is None
        assert all(x["full_cdf"] is None for x in d["curve"])
    assert r["path_extrema"]["drawup"]["log_magnitude"]==0


def test_reciprocal_quotes_swap_directions_and_scale_does_not_change_hits():
    logs=np.cumsum(np.random.default_rng(31).normal(0,.03,120))
    c=AnalysisConfig(first_passage_horizon=12,first_passage_thresholds=(1.,3.))
    a=first_passage_diagnostics(sampled(logs),c)
    b=first_passage_diagnostics(sampled(-logs),c)
    shifted=first_passage_diagnostics(sampled(logs+5),c)
    for x,y,z in zip(a["thresholds"],b["thresholds"],shifted["thresholds"]):
        assert x["up"]==y["down"] and x["down"]==y["up"]
        assert x["up"]==z["up"] and x["down"]==z["down"]


def test_positive_drift_and_sign_symmetric_pair_have_expected_direction():
    c=config()
    rising=first_passage_diagnostics(sampled(np.arange(25)),c)["thresholds"][0]
    assert rising["up"]["full_hit_probability"]==1 and rising["down"]["full_hit_probability"]==0
    # Equal +/- paths, explicitly separate sessions: the combined sample is symmetric.
    logs=np.cumsum(np.random.default_rng(11).normal(size=100))
    both=sampled(np.r_[logs,-logs],['a']*100+['b']*100)
    symmetric=first_passage_diagnostics(both,c)["thresholds"][0]
    assert symmetric["up"]==symmetric["down"]


def test_drawdown_and_drawup_use_ordered_extrema_not_single_returns():
    dates=pd.date_range("2024-01-01",periods=6)
    r=path_extrema([(np.array([0.,3.,2.,4.,1.,2.]),dates)])
    assert r["drawdown"]["log_magnitude"]==3 and r["drawdown"]["steps"]==1
    assert r["drawup"]["log_magnitude"]==4 and r["drawup"]["steps"]==3
    assert r["drawdown"]["simple_percent"]==pytest.approx((1-np.exp(-3))*100)
    assert path_extrema([(np.array([0.]),dates[:1])])["status"]=="not_computable"
    huge=path_extrema([(np.array([-700.,700.]),dates[:2])])["drawup"]
    assert huge["simple_percent"] is None and huge["simple_percent_reason"]
    assert huge["log_magnitude"]==1400.


def test_explicit_disabled_resource_and_undefined_sigma_states():
    f=sampled(np.zeros(12))
    assert first_passage_diagnostics(f,AnalysisConfig())["status"]=="not_computable"
    assert first_passage_diagnostics(f,replace(config(),first_passage="off"))["status"]=="disabled"
    assert first_passage_diagnostics(f,replace(config(),first_passage_max_work=1))["status"]=="resource_limit"
    assert first_passage_diagnostics(sampled([np.nan]),config())["status"]=="not_computable"


@pytest.mark.parametrize('kwargs',[
    {"first_passage_horizon":0},{"first_passage_horizon":True},{"first_passage_horizon":2001},
    {"first_passage_thresholds":(0.,)},{"first_passage_thresholds":(2.,1.)},
    {"first_passage_thresholds":(float('inf'),)},{"first_passage_thresholds":(True,)},
    {"first_passage_thresholds":(None,)},{"first_passage_thresholds":1.},
    {"first_passage_unit":"percent"},{"first_passage_min_starts":1},{"first_passage_max_work":0}])
def test_invalid_options_are_rejected(kwargs):
    with pytest.raises(ValueError):
        replace(config(),**kwargs).validate()
