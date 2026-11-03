"""Adversarial examples for claims made in the result-first report."""
from copy import deepcopy

import numpy as np
import pytest

from financial_stylized_facts.assessment import assess, block_evidence, lag_evidence, NORMAL_TAIL_3
from financial_stylized_facts.findings import summarize
from tests.test_findings import fixture


def example(returns=None):
    if returns is None:
        returns = np.r_[np.nan, np.random.default_rng(27).standard_t(5, 2400)*.01]
    g, c, sampled = fixture(returns)
    g['uncertainty'] = {'blocks': []}
    g['dependence_uncertainty'] = {'rows': []}
    g['findings'] = summarize(g, c, sampled)
    return g, c


def hac(g, c, family, proxy, lower=-.1, upper=.1):
    for lag in range(1, min(c.inference_max_lag, c.max_lag)+1):
        for b in c.hac_bandwidths:
            g['dependence_uncertainty']['rows'].append(dict(family=family, proxy=proxy, lag=lag,
                bandwidth=b, status='computed', lower=.01, upper=.1,
                familywise_lower=lower, familywise_upper=upper))


def boot(g, c, values):
    g['uncertainty']['blocks'] = [dict(block_length=b, status='computed', intervals=[
        dict(metric=m, status='computed', lower=lo, upper=hi) for m,(lo,hi) in values.items()
    ]) for b in c.bootstrap_block_lengths]


def test_nominal_significance_does_not_override_familywise_interval():
    g,c = example(); hac(g,c,'acf','return')
    a = assess(g,c)['by_fact']['1']
    assert a['conclusion'] == 'not_detected'
    assert '不能' in a['summary'] and '独立' in a['summary']
    # Exact zero is included, not excluded.
    g['dependence_uncertainty']['rows'][0]['familywise_lower'] = 0
    assert assess(g,c)['by_fact']['1']['conclusion'] == 'not_detected'


def test_one_favourable_bandwidth_is_not_selected():
    g,c = example(); hac(g,c,'acf','return')
    g['dependence_uncertainty']['rows'][0]['familywise_lower'] = .01
    a = assess(g,c)['by_fact']['1']
    assert a['conclusion'] == 'mixed'
    assert lag_evidence(g,c,'acf','return')['positive_lags'] == []


def test_missing_bandwidth_is_not_treated_as_non_rejection():
    g,c = example(); hac(g,c,'acf','return')
    g['dependence_uncertainty']['rows'].pop()
    assert assess(g,c)['by_fact']['1']['conclusion'] == 'descriptive'
    assert not lag_evidence(g,c,'acf','return')['complete']


def test_isolated_spike_does_not_become_sustained_volatility_clustering():
    g,c = example()
    for p in ['absolute_return','squared_return']:
        hac(g,c,'acf',p)
    for row in g['dependence_uncertainty']['rows']:
        if row['lag'] == 2:
            row['familywise_lower'] = .01
    assert assess(g,c)['by_fact']['6']['conclusion'] == 'indicative'
    for row in g['dependence_uncertainty']['rows']:
        if row['lag'] == 3:
            row['familywise_lower'] = .01
    a = assess(g,c)['by_fact']['6']
    assert a['conclusion'] == 'supported'
    assert a['evidence']['common_positive_lags'] == [2,3]


def test_kurtosis_alone_does_not_create_tail_support():
    # Many zeros and occasional bounded changes: positive kurtosis but no 3σ tail.
    g,c = example(np.r_[np.nan, np.tile([0,0,0,0,.01,-.01],400)])
    assert g['distribution']['excess_kurtosis'] > 0
    assert g['distribution']['tail_counts']['3']['count'] == 0
    assert assess(g,c)['by_fact']['2']['conclusion'] == 'mixed'


def test_tail_support_requires_both_metrics_and_every_block_length():
    g,c = example()
    boot(g,c,{'excess_kurtosis':(1,5), 'tail_probability_3sigma':(.005,.02)})
    assert assess(g,c)['by_fact']['2']['conclusion'] == 'supported'
    # Reference equality is not positive evidence.
    g['uncertainty']['blocks'][-1]['intervals'][1]['lower'] = NORMAL_TAIL_3
    assert assess(g,c)['by_fact']['2']['conclusion'] == 'indicative'
    g['uncertainty']['blocks'].pop()
    assert not block_evidence(g,c,'excess_kurtosis')['complete']
    assert assess(g,c)['by_fact']['2']['conclusion'] == 'indicative'


def test_positive_point_estimate_without_inference_is_descriptive():
    g,c = example()
    a = assess(g,c)['by_fact']['2']
    assert a['conclusion'] == 'indicative' and a['evidence_level'] == 'descriptive'


def test_single_extreme_is_kept_and_disclosed():
    g,c = example(np.r_[np.nan, np.linspace(-.01,.01,2400),-.7])
    before=deepcopy(g)
    a=assess(g,c)['by_fact']['2']
    assert a['notes'] and '单次变化' in a['notes'][0]
    assert g == before


def test_configured_coarse_endpoint_not_replaced_with_better_scale():
    g,c = example()
    # Configured last scale is unreliable; cannot choose a better intermediate scale.
    g['aggregation']['scales'][-1]['n'] = 20
    assert assess(g,c)['by_fact']['4']['conclusion'] == 'insufficient_data'


def test_negative_leverage_and_timescale_direction_are_not_confused():
    g,c = example()
    for p in ['absolute','squared']:
        hac(g,c,'leverage',p,lower=-.2,upper=-.01)
    hac(g,c,'timescale','difference',lower=-.2,upper=-.01)
    a=assess(g,c)['by_fact']
    assert a['9']['conclusion'] == 'supported'
    assert a['11']['label'] == '粗在前更强'
    g['dependence_uncertainty']['rows']=[r for r in g['dependence_uncertainty']['rows'] if r['family']!='leverage' or r['proxy']=='absolute']
    assert assess(g,c)['by_fact']['9']['conclusion'] != 'supported'


@pytest.mark.parametrize('values', [[np.nan], [np.nan,0,0,0,0], [np.nan,.1,-.1]])
def test_missing_short_and_constant_sequences_never_pass(values):
    g,c=example(values)
    a=assess(g,c)
    assert len(a['by_fact']) == 11 and not a['automatic_pass_fail']
    assert a['by_fact']['2']['conclusion'] == 'insufficient_data'
    assert a['by_fact']['10']['conclusion'] == 'not_applicable'
    assert all(x['conclusion'] != 'supported' for x in a['by_fact'].values())


def test_time_scale_and_output_are_explicit_and_deterministic():
    g,c=example()
    a=assess(g,c)
    assert a == assess(g,c)
    assert '1 分钟' in a['by_fact']['1']['summary']
    assert all(x['references'] and x['rule_id'] for x in a['by_fact'].values())
    assert a['by_fact']['7']['label'] == '未启用'


def test_disabled_or_budget_limited_memory_is_not_a_zero_rejection_result():
    g,c=example()
    for status in ["disabled", "budget_exceeded"]:
        g['volatility_persistence']['long_memory_test'] = {"status":status, "reason":"not run"}
        a=assess(g,c)['by_fact']['8']
        assert a['metrics'][1]['value'] is None
        assert '拒绝' not in a['summary']


def test_degenerate_fitted_residual_is_unavailable_not_no_heavy_tails():
    g,c=example()
    g['conditional_tails'].update(status='computed', n_evaluated=100, segments=[
        {'status':'computed', 'segment':1, 'residual_distribution':{'excess_kurtosis':None,'tail_counts':{}}}
    ])
    a=assess(g,c)['by_fact']['7']
    assert a['conclusion']=='insufficient_data' and a['evidence_level']=='unavailable'
    assert a['evidence']['segments'][0]['tail_pattern'] is None
