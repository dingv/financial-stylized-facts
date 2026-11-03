"""Direction semantics, independent paired calculations, and lead/lag recovery."""
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy.stats import pearsonr

from financial_stylized_facts.activity import volume_diagnostics
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.volume_lag import volume_lag_diagnostics, volume_lag_evidence
from tests.test_assessment import example, hac, boot
from financial_stylized_facts.assessment import assess


@pytest.mark.parametrize("sign,alignment,conclusion,direction", [
    (-1, "consistent", "supported", "left_skew"),
    (1, "opposite", "opposite_direction", "right_skew")])
def test_skew_evidence_and_classical_direction_are_separate(sign, alignment, conclusion, direction):
    g,c = example()
    g['asymmetry']['skewness'] = sign
    boot(g,c,{'skewness':(-2,-.1) if sign < 0 else (.1,2)})
    a = assess(g,c)['by_fact']['3']
    assert a['asymmetry_evidence'] == 'supported'
    assert a['direction'] == direction and a['classical_alignment'] == alignment
    assert a['conclusion'] == conclusion and a['directional_basis'] == 'skewness_proxy'


def test_skew_point_direction_does_not_create_classical_support():
    g,c = example(); g['asymmetry']['skewness'] = -1
    boot(g,c,{'skewness':(-2,1)})
    a = assess(g,c)['by_fact']['3']
    assert a['direction'] == 'left_skew' and a['asymmetry_evidence'] == 'not_detected'
    assert a['classical_alignment'] == 'inconclusive'
    g['uncertainty']['blocks'].pop()
    assert assess(g,c)['by_fact']['3']['asymmetry_evidence'] == 'inconclusive'


@pytest.mark.parametrize("sign,alignment,direction", [
    (-1,'consistent','coarse_leads_fine'), (1,'opposite','fine_leads_coarse')])
def test_timescale_direction_is_interpreted_with_correct_sign(sign, alignment, direction):
    g,c=example()
    hac(g,c,'timescale','difference',lower=-.2 if sign<0 else .01,upper=-.01 if sign<0 else .2)
    a=assess(g,c)['by_fact']['11']
    assert a['asymmetry_evidence']=='supported' and a['classical_alignment']==alignment
    assert a['direction']==direction
    assert a['conclusion']==('supported' if sign<0 else 'opposite_direction')


def test_mixed_and_unavailable_directions_are_not_classical_support():
    g,c=example(); hac(g,c,'timescale','difference',lower=-.2,upper=-.01)
    for r in g['dependence_uncertainty']['rows']:
        if r['lag']==2:
            r.update(familywise_lower=.01,familywise_upper=.2)
    a=assess(g,c)['by_fact']['11']
    assert a['direction']=='mixed' and a['classical_alignment']=='mixed'
    g,c=example([np.nan,0,0,0])
    for i in ['3','11']:
        a=assess(g,c)['by_fact'][i]
        assert a['asymmetry_evidence']=='unavailable' and a['classical_alignment']=='not_evaluated'


def cfg(**kwargs):
    return AnalysisConfig(volume_kind='interval',volume_unit='shares',frequency='1min',
                          max_lag=3,inference_max_lag=3,hac_bandwidths=(3,5),min_pairs=3,**kwargs)


def test_volume_lags_match_independent_pairs_without_compressing_gaps_or_crossing_sessions():
    f=pd.DataFrame({'session_id':['a']*6+['b']*6,
       'volume':[1,2,np.nan,4,5,0, 12,1,5,3,2,9],
       'log_return':[np.nan,.1,-.3,np.nan,.2,-.1, np.nan,.02,.2,-.4,.01,-.7]})
    result=volume_lag_diagnostics(f,cfg(dependence_inference='off'))
    for row in result['rows']:
        x,y=[],[]; lag=row['lag']
        for _,g in f.groupby('session_id'):
            for i in range(len(g)):
                j=i+lag
                if 0<=j<len(g) and np.isfinite(g.volume.iloc[i]) and np.isfinite(g.log_return.iloc[j]):
                    x.append(g.volume.iloc[i]); r=g.log_return.iloc[j]
                    y.append(abs(r) if row['proxy']=='absolute' else r*r)
        assert row['pair_count']==len(x)
        if len(x)>=3 and np.std(x)>0 and np.std(y)>0:
            assert row['correlation']==pytest.approx(pearsonr(x,y).statistic,abs=1e-12)
    zero={r['proxy']:r for r in result['rows'] if r['lag']==0}
    same=volume_diagnostics(f,cfg())
    for p in zero:
        assert zero[p]['correlation']==pytest.approx(same['correlations'][p]['pearson'])


def shifted_volume_frame(n=2000):
    rng=np.random.default_rng(921)
    v=rng.uniform(1,5,n)
    amplitude=np.r_[rng.uniform(1,5,2),v[:-2]]+rng.uniform(0,.2,n)
    return pd.DataFrame({'session_id':'one','volume':v,'log_return':amplitude*rng.choice([-1,1],n)})


def test_known_lead_reverses_under_time_reversal_and_survives_unit_changes():
    f=shifted_volume_frame(); c=cfg()
    forward=volume_lag_diagnostics(f,c)
    backward=volume_lag_diagnostics(f.iloc[::-1],c)
    e=volume_lag_evidence(forward,c)
    assert 2 in e['positive_volume_earlier_lags']
    assert -2 in volume_lag_evidence(backward,c)['positive_volatility_earlier_lags']
    for a,b in zip(forward['rows'],sorted(backward['rows'],key=lambda r:(r['proxy'],-r['lag']))):
        assert a['correlation']==pytest.approx(b['correlation'],abs=1e-12)
    f['volume']*=1e100;f['log_return']*=1e90
    scaled=volume_lag_diagnostics(f,c)
    for a,b in zip(forward['rows'],scaled['rows']):
        assert a['correlation']==pytest.approx(b['correlation'],abs=1e-12)
    # All configured signed lags, proxies and bandwidths form the family.
    assert forward['inference']['family_size']==2*7*2
    for r in forward['inference']['rows']:
        if r['status']=='computed':
            assert r['familywise_lower']<=r['lower']<=r['upper']<=r['familywise_upper']


def test_no_volume_constant_sparse_disabled_and_resource_limits():
    f=shifted_volume_frame(30)
    assert volume_lag_diagnostics(f,AnalysisConfig())['status']=='not_applicable'
    off=volume_lag_diagnostics(f,cfg(dependence_inference='off'))
    assert off['rows'] and off['inference']['status']=='disabled'
    limited=volume_lag_diagnostics(f,replace(cfg(),inference_max_work=1))
    assert limited['status']=='resource_limit' and not limited['rows']
    f['volume']=0
    result=volume_lag_diagnostics(f,cfg())
    assert result['status']=='not_computable'
    assert all(r['correlation'] is None for r in result['rows'])
    assert not volume_lag_evidence(result,cfg())['positive_lags']


def test_lag_support_requires_both_proxies_and_all_bandwidths():
    c=cfg();r=volume_lag_diagnostics(shifted_volume_frame(),c)
    assert 2 in volume_lag_evidence(r,c)['positive_lags']
    row=next(x for x in r['inference']['rows'] if x['lag']==2 and x['proxy']=='squared')
    row['familywise_lower']=0
    assert 2 not in volume_lag_evidence(r,c)['positive_lags']
