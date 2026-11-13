"""Fixed-seed size/power audit for primary decisions, independent of market data.

Output is JSON in tmp. Prespecified: n=1500/4000, 100 trials, lag 1..10,
5% two-sided Holm, Gaussian/t5/reversible-SV nulls, signed alternatives.
"""
import argparse,json,time,os
from dataclasses import replace
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.signal import lfilter
from scipy.stats import binomtest
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.inference import pearson_influence,primary_interval,holm_family
from financial_stylized_facts.uncertainty import uncertainty_diagnostics
from financial_stylized_facts.decay import persistence_evidence
from financial_stylized_facts.dependence import dependence_diagnostics
from tests.validation.validate_long_memory import fractional_gaussian_noise
from tests.test_conditional import sampled


def rate(flags):
    k,n=sum(flags),len(flags);ci=binomtest(k,n).proportion_ci(method='wilson')
    return {'hits':int(k),'trials':n,'rate':k/n,'wilson_95':[ci.low,ci.high]}


def decision(r,family,config):
    if family=='leverage':
        fine,coarse=r,abs(r)
    else:
        blocks=r[:len(r)//5*5].reshape(-1,5)
        fine,coarse=abs(blocks).mean(axis=1),abs(blocks.sum(axis=1))
    rows=[]
    for lag in range(1,11):
        e,s,n=pearson_influence([fine],[coarse],lag)
        if family=='timescale':
            reverse,rs,rn=pearson_influence([fine],[coarse],-lag)
            e-=reverse;s=[a-b for a,b in zip(s,rs)];n=min(n,rn)
        rows.append(primary_interval(e,s,n,family=family,proxy='absolute' if family=='leverage' else 'difference',
                     lag=lag,config=config,bounds=(-1,1) if family=='leverage' else (-2,2)))
    holm_family(rows)
    return {'any':any(r['reject'] for r in rows),'negative':any(r['reject'] and r['estimate']<0 for r in rows),
            'positive':any(r['reject'] and r['estimate']>0 for r in rows),'available':all(r['status']=='computed' for r in rows)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    c=AnalysisConfig(coarse_factor=5,volatility_max_lag=100)
    rows=[];start=time.monotonic()
    for n in [1500,4000]:
        for case in ['gaussian_null','t5_null','reversible_sv_null','leverage_negative','leverage_positive','coarse_leads','fine_leads']:
            out={'leverage':[],'timescale':[]}
            for trial in range(100):
                rng=np.random.default_rng(1130000+trial+10*n)
                eps=rng.normal(size=n+501)
                if case=='gaussian_null':r=eps[501:]
                elif case=='t5_null':r=rng.standard_t(5,n)
                elif case=='reversible_sv_null':
                    vol=lfilter([np.sqrt(1-.8**2)],[1,-.8],rng.normal(size=n+500))[500:]
                    r=eps[501:]*np.exp(.5*vol)
                elif case.startswith('leverage'):
                    r=eps[501:]*np.exp(-.4*eps[500:-1])
                    if case.endswith('positive'):r=-r
                else:
                    k=n//5;coarse=rng.uniform(1,2,k+1);amp=2+3*coarse[:-1]
                    blocks=coarse[1:,None]/5+amp[:,None]*np.array([1,-1,1,-1,0])
                    r=(blocks*rng.choice([-1,1],size=(k,1))).ravel()
                    if case=='fine_leads':r=r[::-1]
                families=['leverage','timescale'] if case.endswith('null') else ['leverage'] if case.startswith('leverage') else ['timescale']
                for family in families:out[family].append(decision(r,family,c))
            for family,values in out.items():
                if not values:continue
                row={'case':case,'n':n,'family':family,**{key:rate([v[key] for v in values]) for key in values[0]}}
                rows.append(row);print(case,n,family,row['any']['rate'],flush=True)
    # Marginal skew: same primary CBB length for null and either skew direction.
    for case in ['gaussian_null','t5_null','left_skew','right_skew']:
        flags=[]
        for trial in range(100):
            rng=np.random.default_rng(1930000+trial)
            r=rng.normal(size=1500) if case=='gaussian_null' else rng.standard_t(5,1500) if case=='t5_null' else rng.gamma(4,1,1500)-4
            if case=='left_skew':r=-r
            out=uncertainty_diagnostics(sampled(r),replace(c,bootstrap_block_lengths=(10,)),str(trial))
            row=next(x for x in out['blocks'][0]['intervals'] if x['metric']=='quantile_skewness')
            flags.append(row['status']=='computed' and (row['lower']>0 or row['upper']<0))
        rows.append({'case':case,'n':1500,'family':'quantile_skewness','any':rate(flags)})
        print(case,'skewness',rate(flags)['rate'],flush=True)
    # Fact 8: report the indication and stronger stability result separately.
    for case in ['gaussian_null','short_memory_sv','long_memory_sv','variance_break']:
        indicative=[];stable=[]
        for trial in range(40):
            rng=np.random.default_rng(1730000+trial);n=4096;eps=rng.normal(size=n)
            if case=='gaussian_null':r=eps
            elif case=='variance_break':r=eps*np.repeat([.5,3],n//2)
            else:
                vol=fractional_gaussian_noise(rng,n,.85) if case=='long_memory_sv' else lfilter([.6],[1,-.8],rng.normal(size=n+500))[500:]
                r=eps*np.exp(.6*vol)
            vp=dependence_diagnostics(sampled(r),c)['volatility_persistence']
            e=persistence_evidence(vp['long_memory_test']);fits=[x for x in vp['decay_comparison']['rows'] if x['period']=='full']
            indicative.append(e['full_upper_rejection'] or (len(fits)==2 and all(x.get('slow_power_pattern',False) for x in fits)))
            stable.append(e['stable_upper_rejection'])
        rows.append({'case':case,'n':4096,'family':'persistence','indication':rate(indicative),'stable_support':rate(stable)})
        print(case,'persistence',rate(indicative)['rate'],flush=True)
    result={'seed_ranges':[1130000,1930000,1730000],'lag_range':[1,10],'alpha':.05,'rows':rows,'elapsed_seconds':time.monotonic()-start}
    a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
if __name__=='__main__':main()
