"""External numerical references and invariants for primary assessment rules."""
from copy import deepcopy
from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.sandwich_covariance import S_hac_simple
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.inference import (automatic_bandwidth,primary_interval,holm_family,
    dependence_uncertainty,pearson_influence)
from financial_stylized_facts.assessment import lag_evidence,primary_skew_evidence,assess
from tests.test_assessment import example,boot


def test_holm_matches_statsmodels_including_ties_and_missing_planned_tests():
    p=[.001,.015,None,.04,.001,.6]
    rows=[{'p_value':v} for v in p];holm_family(rows)
    reject,adjusted,*_=multipletests([1 if v is None else v for v in p],method='holm')
    for i,r in enumerate(rows):
        assert r['reject']==bool(reject[i])
        assert r['adjusted_p']==(None if p[i] is None else pytest.approx(adjusted[i]))
    assert all(r['planned_family_size']==6 for r in rows)


def test_auto_bandwidth_matches_statsmodels_and_covers_lag():
    rng=np.random.default_rng(83)
    for n in [200,800,4000]:
        x=rng.normal(size=n)
        assert automatic_bandwidth(n,1)==int(np.floor(4*(n/100)**(2/9)))
        b=automatic_bandwidth(n,1)
        assert S_hac_simple(x)[0,0]==pytest.approx(S_hac_simple(x,nlags=b)[0,0])
    assert automatic_bandwidth(400,10)==10


def test_808_coarse_pairs_are_testable_without_820_gate_from_auxiliary_bandwidth():
    r=np.r_[np.nan,np.random.default_rng(9).normal(size=4046)]
    frame=pd.DataFrame({'log_return':r,'session_id':'a'})
    config=AnalysisConfig(coarse_factor=5)
    result=dependence_uncertainty(frame,config)
    main=[r for r in result['primary_rows'] if r['family']=='timescale']
    assert main[0]['pair_count']==808
    assert all(r['status']=='computed' for r in main)
    assert all(r['planned_family_size']==10 for r in main)
    old=[r for r in result['rows'] if r['family']=='timescale' and r['bandwidth']==40]
    assert all(r['status']=='not_computable' for r in old)


def test_adding_sensitivity_bandwidth_never_changes_primary_result():
    frame=pd.DataFrame({'log_return':np.r_[np.nan,np.random.default_rng(22).normal(size=1500)],'session_id':'a'})
    c=AnalysisConfig(coarse_factor=5,inference_max_lag=3)
    a=dependence_uncertainty(frame,replace(c,hac_bandwidths=(10,)))
    b=dependence_uncertainty(frame,c)
    assert a['primary_rows']==b['primary_rows']
    ea=lag_evidence({'dependence_uncertainty':a},c,'timescale','difference')
    eb=lag_evidence({'dependence_uncertainty':b},c,'timescale','difference')
    assert ea['positive_lags']==eb['positive_lags'] and ea['negative_lags']==eb['negative_lags']


def test_unavailable_inference_is_not_a_negative_test():
    c=AnalysisConfig(coarse_factor=5)
    result=dependence_uncertainty(pd.DataFrame({'log_return':np.r_[np.nan,np.arange(185)],'session_id':'a'}),c)
    e=lag_evidence({'dependence_uncertainty':result},c,'timescale','difference')
    assert e['inference_status']=='unavailable' and e['computed_lags']==0
    assert not e['positive_lags'] and not e['negative_lags']


def test_skew_primary_is_predeclared_and_not_best_available():
    g,c=example();boot(g,c,{'quantile_skewness':(-2,-.1)})
    g['uncertainty']['blocks'][-1]['intervals'][0].update(lower=-2,upper=2)
    e=primary_skew_evidence(g,c)
    assert e['negative'] and not e['sensitivity']['negative']
    g['uncertainty']['blocks'].pop(0)
    assert not primary_skew_evidence(g,c)['complete']


def test_sign_reversal_reverses_leverage_but_not_significance():
    rng=np.random.default_rng(77);eps=rng.normal(size=4001)
    r=eps[1:]*np.exp(-.4*eps[:-1]);c=AnalysisConfig()
    output=[]
    for x in [r,-r]:
        e,s,n=pearson_influence([x],[abs(x)],1)
        row=primary_interval(e,s,n,family='leverage',proxy='absolute',lag=1,config=c)
        holm_family([row]);output.append(row)
    assert output[0]['reject'] and output[1]['reject']
    assert output[0]['estimate']==pytest.approx(-output[1]['estimate'])
    assert output[0]['adjusted_p']==pytest.approx(output[1]['adjusted_p'])


def test_missing_primary_never_uses_favourable_sensitivity():
    g,c=example()
    g['dependence_uncertainty']['primary_rows']=[]
    for b in c.hac_bandwidths:
        g['dependence_uncertainty']['rows'].append(dict(family='timescale',proxy='difference',lag=1,
            bandwidth=b,status='computed',standard_error=.001,estimate=-.5))
    e=lag_evidence(g,c,'timescale','difference')
    assert not e['negative_lags'] and e['inference_status']=='unavailable'
    assert assess(g,c)['by_fact']['11']['conclusion']=='insufficient_data'


def test_quantile_skewness_matches_statsmodels_and_keeps_extremes():
    from statsmodels.stats.stattools import robust_skewness
    from financial_stylized_facts.diagnostics import quantile_skewness
    rng=np.random.default_rng(42)
    for x in [rng.standard_t(5,900),rng.gamma(4,1,900),np.r_[rng.normal(size=899),-1e4]]:
        original=x.copy()
        assert quantile_skewness(x)==pytest.approx(robust_skewness(x)[1])
        assert quantile_skewness(-x)==pytest.approx(-quantile_skewness(x))
        np.testing.assert_array_equal(x,original)
    assert quantile_skewness([0,0,0,0,1]) is None


def test_public_assessment_reports_reverse_leverage_as_reverse():
    from tests.test_findings import fixture
    from financial_stylized_facts.findings import summarize
    rng=np.random.default_rng(77);e=rng.normal(size=4001)
    r=-e[1:]*np.exp(-.4*e[:-1])
    g,c,frame=fixture(np.r_[np.nan,r])
    g['uncertainty']={'blocks':[]}
    g['dependence_uncertainty']=dependence_uncertainty(frame,c)
    g['findings']=summarize(g,c,frame)
    a=assess(g,c)['by_fact']['9']
    assert a['conclusion']=='opposite_direction' and a['direction']=='positive'
    assert a['classical_alignment']=='opposite'
