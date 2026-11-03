from dataclasses import replace
import numpy as np
import pandas as pd
import pytest
from scipy.stats import norm
from statsmodels.stats.sandwich_covariance import S_hac_simple

from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.statistics import autocorrelation
from financial_stylized_facts.dependence import lagged_volatility_correlation
from financial_stylized_facts.inference import acf_influence, pearson_influence, hac_variances, dependence_uncertainty


def weighted_acf(x, weights, lag):
    good=np.isfinite(x)
    mu=np.sum(weights[good]*x[good])/weights[good].sum()
    denominator=np.sum(weights[good]*(x[good]-mu)**2)
    valid=good[:-lag]&good[lag:]
    return np.sum(weights[:-lag][valid]*(x[:-lag][valid]-mu)*(x[lag:][valid]-mu))/denominator


def weighted_pearson(x,y,weights,lag):
    pos=np.arange(max(0,-lag),min(len(x),len(x)-lag))
    pos=pos[np.isfinite(x[pos])&np.isfinite(y[pos+lag])]
    a,b,w=x[pos],y[pos+lag],weights[pos]
    a=a-np.average(a,weights=w);b=b-np.average(b,weights=w)
    return np.sum(w*a*b)/np.sqrt(np.sum(w*a*a)*np.sum(w*b*b))


def test_acf_influence_matches_numerical_derivative_including_mean_and_missingness():
    x=np.array([np.nan,4.,7.,5.,np.nan,9.,-2.,3.,4.])
    estimate,scores,pairs=acf_influence([x],2)
    assert pairs==4
    assert estimate==pytest.approx(weighted_acf(x,np.ones(len(x)),2))
    eps=1e-5
    for i in range(len(x)):
        plus=np.ones(len(x));minus=plus.copy();plus[i]+=eps;minus[i]-=eps
        derivative=(weighted_acf(x,plus,2)-weighted_acf(x,minus,2))/(2*eps)
        assert scores[0][i]==pytest.approx(derivative,abs=1e-10)
    assert sum(scores[0])==pytest.approx(0,abs=1e-14)


@pytest.mark.parametrize('lag',[-3,-1,0,1,3])
def test_pearson_influence_matches_weighted_finite_difference(lag):
    x=np.array([4.,1.,np.nan,5.,8.,2.,-3.,6.,7.,1.])
    y=np.array([1.,5.,2.,4.,3.,np.nan,6.,8.,9.,5.])
    estimate,scores,pairs=pearson_influence([x],[y],lag)
    assert estimate==pytest.approx(weighted_pearson(x,y,np.ones(len(x)),lag))
    for i in range(len(x)):
        plus=np.ones(len(x));minus=plus.copy();plus[i]+=1e-5;minus[i]-=1e-5
        derivative=(weighted_pearson(x,y,plus,lag)-weighted_pearson(x,y,minus,lag))/2e-5
        assert scores[0][i]==pytest.approx(derivative,abs=1e-10)
    assert np.sum(scores[0])==pytest.approx(0,abs=1e-14)


def test_hac_exactly_matches_statsmodels_and_does_not_join_sessions():
    rng=np.random.default_rng(51)
    scores=[rng.normal(size=80)/80,rng.normal(size=50)/50]
    scores=[s-s.mean() for s in scores]
    actual=hac_variances(scores,[0,5,10])
    for bandwidth in actual:
        expected=sum(float(S_hac_simple(s,nlags=bandwidth)[0,0]) for s in scores)
        assert actual[bandwidth]==pytest.approx(expected,rel=1e-14)
    assert actual[10]!=pytest.approx(float(S_hac_simple(np.concatenate(scores),nlags=10)[0,0]),rel=1e-5)


def test_difference_variance_uses_joint_influence_covariance():
    rng=np.random.default_rng(7)
    f=rng.normal(size=500);c=.5*f+np.roll(f,1)+rng.normal(size=500)
    a,sa,_=pearson_influence([f],[c],1)
    b,sb,_=pearson_influence([f],[c],-1)
    scores=[sa[0]-sb[0]]
    actual=hac_variances(scores,[10])[10]
    matrix=S_hac_simple(np.column_stack([sa[0],sb[0]]),nlags=10)
    expected=np.array([1.,-1.])@matrix@np.array([1.,-1.])
    assert actual==pytest.approx(expected)
    assert actual!=pytest.approx(matrix.trace(),rel=1e-4)
    assert hac_variances([sa[0]-sa[0]],[10])[10]==0


def test_estimates_match_existing_acf_and_signed_leverage_with_gaps():
    rng=np.random.default_rng(9)
    arrays=[rng.normal(size=400),rng.normal(.1,size=500)]
    arrays[0][15:22]=np.nan;arrays[1][50]=np.nan
    for lag in [1,5,10]:
        e,_,n=acf_influence(arrays,lag)
        reference=autocorrelation(arrays,lag,2)
        assert e==pytest.approx(reference['values'][lag]) and n==reference['pair_counts'][lag]
    for proxy,transform in [('absolute',np.abs),('squared',np.square)]:
        ref=lagged_volatility_correlation(arrays,10,2,proxy)
        for lag in [-10,-1,1,10]:
            e,_,n=pearson_influence(arrays,[transform(x) for x in arrays],lag)
            idx=ref['lags'].index(lag)
            assert e==pytest.approx(ref['values'][idx],abs=1e-13) and n==ref['pair_counts'][idx]


def test_white_noise_and_ar1_standard_errors_have_expected_scale():
    rng=np.random.default_rng(2026);n=30000
    x=rng.normal(size=n)
    _,scores,_=acf_influence([x],1)
    se=np.sqrt(hac_variances(scores,[40])[40])
    assert se==pytest.approx(1/np.sqrt(n),rel=.12)
    phi=.6;a=np.zeros(n)
    for i in range(1,n):a[i]=phi*a[i-1]+x[i]
    e,scores,_=acf_influence([a],1)
    assert e==pytest.approx(phi,abs=.02)
    se=np.sqrt(hac_variances(scores,[40])[40])
    assert se==pytest.approx(np.sqrt((1-phi**2)/n),rel=.15)


def sampled(values):
    return pd.DataFrame({'log_return':values,'session_id':'a'})


def test_statuses_budget_disabled_and_no_fake_zero_intervals():
    c=AnalysisConfig(inference_max_lag=2)
    assert dependence_uncertainty(sampled([np.nan,0,0]),replace(c,dependence_inference='off'))['status']=='disabled'
    assert dependence_uncertainty(sampled(np.arange(1000)),replace(c,inference_max_work=1))['status']=='resource_limit'
    r=dependence_uncertainty(sampled(np.r_[np.nan,np.zeros(500)]),c)
    assert r['status']=='not_computable'
    assert all(row['lower'] is None and row['upper'] is None for row in r['rows'])
    assert next(x for x in r['rows'] if x['family']=='acf' and x['lag']==1)['pair_count']==499


def test_bandwidth_sensitivity_and_familywise_intervals_cover_all_planned_rows():
    rng=np.random.default_rng(53)
    c=AnalysisConfig(inference_max_lag=2,hac_bandwidths=(1,10,40),coarse_factor=2)
    r=dependence_uncertainty(sampled(np.r_[np.nan,rng.normal(size=600)]),c)
    assert r['status']=='partially_computed'
    assert r['family_size']==2*8*3==len(r['rows'])
    assert r['familywise_critical_value']==pytest.approx(norm.ppf(1-.05/(2*r['family_size'])))
    for row in r['rows']:
        if row['bandwidth']==40 or row['bandwidth']<abs(row['lag']):
            assert row['status']=='not_computable'
        if row['status']=='computed':
            assert row['familywise_lower']<=row['lower']<=row['estimate']<=row['upper']<=row['familywise_upper']


@pytest.mark.parametrize('kwargs',[{'hac_bandwidths':()},{'hac_bandwidths':(20,10)},{'hac_bandwidths':(True,)},
                                   {'inference_max_lag':0},{'inference_min_pairs':3},{'dependence_inference':'iid'}])
def test_invalid_inference_config(kwargs):
    with pytest.raises(ValueError):AnalysisConfig(**kwargs).validate()
