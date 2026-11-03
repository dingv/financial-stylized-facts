from dataclasses import replace
import numpy as np
import pytest
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.intermittency import fano, intermittency_test
from financial_stylized_facts.decay import fit_decay, compare_decay, decay_diagnostics
from financial_stylized_facts.conditional import fit_garch
from financial_stylized_facts.conditional_inference import conditional_reference, finalize_conditional, gaussian_garch, portmanteau
from tests.test_conditional import sampled, garch_returns


def test_fano_hand_counts_and_zero():
    assert fano([0,0,2,2]) == pytest.approx(4/3)
    assert fano([0,0]) is None
    assert fano([1]) is None


def test_randomization_detects_clusters_and_is_reproducible():
    r=np.zeros(4000)
    r[100:120]=10;r[2000:2020]=10
    c=AnalysisConfig(permutation_reps=199)
    a=intermittency_test(sampled(r),c,'asset')
    assert a==intermittency_test(sampled(r),c,'asset')
    assert all(x['reject'] for x in a['rows'])
    assert all(x['p_value']>=1/200 and x['family_adjusted_p']>=3/200 for x in a['rows'])
    assert a['total_events']==40


def test_missing_slots_and_session_edges_never_become_count_windows():
    r=np.r_[np.arange(19),np.nan,np.arange(21)]
    a=intermittency_test(sampled(r),AnalysisConfig(intermittency_windows=(10,)))
    assert a['rows'][0]['retained_returns']==30
    assert a['rows'][0]['omitted_returns']==10
    assert a['rows'][0]['status']=='insufficient_data'
    a=intermittency_test(sampled(np.arange(40),['a']*19+['b']*21),AnalysisConfig(intermittency_windows=(10,)))
    assert a['rows'][0]['retained_returns']==30


def test_no_events_constant_ties_off_and_budget_have_reasons():
    c=AnalysisConfig()
    assert intermittency_test(sampled(np.ones(5000)),c)['total_events']==0
    r=np.random.default_rng(1).normal(size=4000)
    for kwargs,status in [({'permutation_reps':0},'disabled'),({'permutation_max_work':1},'budget_exceeded')]:
        a=intermittency_test(sampled(r),replace(c,**kwargs))
        assert all(x['status']==status and x['reason'] for x in a['rows'])


def curve(kind):
    k=np.arange(1,101);y=.4*k**(-.4) if kind=='power' else .4*np.exp(-.08*(k-1))
    return dict(lags=k.tolist(),values=y.tolist(),pair_counts=[5000]*100)


@pytest.mark.parametrize('kind',['power','exponential'])
def test_known_decay_shapes_recover_parameters_and_holdout(kind):
    a=curve(kind);r=compare_decay(a,1,100,1000)
    assert r['preferred']==kind
    fit=r['models'][kind]
    assert fit['amplitude']==pytest.approx(.4,abs=1e-6)
    assert fit['shape']==pytest.approx(.4 if kind=='power' else .08,abs=1e-6)
    assert fit['heldout_rmse']<1e-6
    assert r['slow_power_pattern']==(kind=='power')


def test_decay_never_discards_negative_or_unavailable_lags():
    a=curve('power');a['values'][40]=-.5
    r=compare_decay(a,1,100,1000)
    assert len(r['models']['power']['predicted'])==100
    assert r['positive_fraction']==.99
    a['values'][40]=None
    assert compare_decay(a,1,100,1000)['status']=='insufficient_data'
    assert compare_decay(curve('power'),1,100,6000)['status']=='insufficient_data'


def test_decay_stability_requires_every_range_and_period():
    a=curve('power');p=dict(full=a,blocks=[{'block':1,'acf':a}])
    assert decay_diagnostics(p,AnalysisConfig(volatility_max_lag=100))['stable_slow_power_pattern']
    p['blocks'].append({'block':2,'acf':curve('exponential')})
    assert not decay_diagnostics(p,AnalysisConfig(volatility_max_lag=100))['stable_slow_power_pattern']


def test_bootstrap_refits_gaussian_and_student_returns():
    c=AnalysisConfig(conditional_bootstrap_reps=99,conditional_bootstrap_max_work=1000000)
    for student in [False,True]:
        r=garch_returns(seed=19,n=2000,student=student);fit,arrays=fit_garch(r)
        ref=conditional_reference(r,fit,arrays,c,'fixed')
        assert ref['status']=='computed'
        assert ref['completed_reps']+ref['failed_reps']==99
        assert ref['joint_tail_p']>.05 if not student else ref['joint_tail_p']<=.05
        assert all(t['p_value']>=.01 for t in ref['tests'])
        assert ref['refit'] and ref['tests'][0]['monte_carlo_interval']


def test_simulation_is_reproducible_and_preserves_mean_and_units():
    p={'mu':.2,'omega':.05,'alpha':.1,'beta':.8}
    x=gaussian_garch(p,100,np.random.default_rng(1))
    q={**p,'mu':20.,'omega':500.}
    y=gaussian_garch(q,100,np.random.default_rng(1))
    np.testing.assert_allclose(y,100*x)
    assert portmanteau(np.ones(100)) is None
    with pytest.raises(ValueError):
        gaussian_garch({**p,'beta':.95},100,np.random.default_rng(1))


def test_no_null_inference_after_budget_boundary_or_failed_refits(monkeypatch):
    r=garch_returns(n=600);fit,arrays=fit_garch(r);c=AnalysisConfig(conditional_bootstrap_reps=99)
    assert conditional_reference(r,fit,arrays,replace(c,conditional_bootstrap_max_work=1))['status']=='budget_exceeded'
    fit['parameters']['persistence']=.999
    assert conditional_reference(r,fit,arrays,c)['status']=='unstable_null'
    fit['parameters']['persistence']=.9
    monkeypatch.setattr('financial_stylized_facts.conditional.fit_garch',lambda *a,**k: ({},None))
    ref=conditional_reference(r,fit,arrays,c)
    assert ref['status']=='refit_failures' and not ref['tail_supported']


def test_failed_refits_are_counted_conservatively(monkeypatch):
    r=garch_returns(n=600);fit,arrays=fit_garch(r);c=AnalysisConfig(conditional_bootstrap_reps=99)
    calls=[0]
    def fake(*args,**kwargs):
        calls[0]+=1
        if calls[0]<=4:
            return {},None
        return fit,arrays
    monkeypatch.setattr('financial_stylized_facts.conditional.fit_garch',fake)
    ref=conditional_reference(r,fit,arrays,c)
    assert calls[0]==99 and ref['failed_reps']==4 and ref['status']=='computed'
    for t in ref['tests']:
        assert t['p_upper_bound']-t['p_lower_bound']==pytest.approx(.04)


def test_segment_correction_and_residual_misfit_gate():
    ref=dict(status='computed',joint_tail_p=.02,adequacy_rejected=False)
    result={'segments':[{'reference_test':ref}]}
    finalize_conditional(result,3)
    assert not ref['tail_supported'] and ref['family_adjusted_tail_p']==.06
    finalize_conditional(result,1)
    assert ref['tail_supported']
    ref['adequacy_rejected']=True
    finalize_conditional(result,1)
    assert not ref['tail_supported']


@pytest.mark.parametrize('kwargs',[{'intermittency_windows':(30,10)}, {'intermittency_quantile':1},
    {'permutation_reps':5},{'conditional_bootstrap_reps':False},{'conditional_bootstrap_max_work':0}])
def test_invalid_new_configuration(kwargs):
    with pytest.raises(ValueError):
        AnalysisConfig(**kwargs).validate()


def test_assessment_uses_tests_and_keeps_uncertainty_visible():
    from tests.test_assessment import example
    from financial_stylized_facts.assessment import assess
    g,c=example()
    g['intermittency']['inference']={'status':'computed','total_events':30,'rows':[
        {'status':'computed','window':w,'reject':w!=10,'family_adjusted_p':.01 if w!=10 else .5} for w in (10,30,60)]}
    assert assess(g,c)['by_fact']['5']['conclusion']=='supported'
    g['intermittency']['inference']['rows'][1]['reject']=False
    assert assess(g,c)['by_fact']['5']['conclusion']=='indicative'
    g['volatility_persistence']['decay_comparison']={'status':'computed','rows':[
        dict(period='full',**compare_decay(curve('exponential'),1,100,1000)),
        dict(period='full',**compare_decay(curve('exponential'),5,100,1000))],
        'stable_slow_power_pattern':False}
    a=assess(g,c)['by_fact']['8']
    assert '指数' in a['label'] and a['evidence_level']=='model'


def test_decay_accounts_for_fewer_pairs_at_session_edges():
    k=np.arange(1,101);n=5000;exposure=1-k/150
    acf=dict(n=n,lags=k.tolist(),pair_counts=np.rint(n*exposure).astype(int).tolist())
    exact=np.array(acf['pair_counts'])/n
    acf['values']=(.4*k**(-.4)*exact).tolist()
    r=compare_decay(acf,1,100,1000)
    assert r['models']['power']['shape']==pytest.approx(.4,abs=1e-6)
    assert r['preferred']=='power'


def test_persistence_requires_upper_rejection_all_bands_and_halves():
    from financial_stylized_facts.decay import persistence_evidence
    memory=dict(status='computed',bandwidths=[0,10,20],rows=[
        dict(segment=1,partition=p,window=w,bandwidth=q,status='computed',position='above',reject_short_memory_family=True,family_adjusted_p=.01)
        for p in (1,2) for w in range(1,p+1) for q in (10,20)])
    assert persistence_evidence(memory)['stable_upper_rejection']
    memory['rows'][-1]['position']='below'
    assert not persistence_evidence(memory)['stable_upper_rejection']
    assert persistence_evidence(memory)['full_upper_rejection']
    memory['rows'].pop()
    assert not persistence_evidence(memory)['complete']
    assert not persistence_evidence({'status':'disabled'})['stable_upper_rejection']
