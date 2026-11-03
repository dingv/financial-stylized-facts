"""Finite-sample stress check of finite-range decay classification (not a test)."""
import json,os,time,argparse
import numpy as np
from scipy.signal import lfilter
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.decay import persistence_evidence
from financial_stylized_facts.dependence import dependence_diagnostics
from financial_stylized_facts.intermittency import intermittency_test
from tests.test_conditional import sampled
from tests.validation.validate_long_memory import fractional_gaussian_noise


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    c=AnalysisConfig(volatility_max_lag=50,long_memory='on',permutation_reps=199)
    rows=[];start=time.monotonic()
    for i in range(20):
        rng=np.random.default_rng(88200+i);n=8192
        ar=lfilter([np.sqrt(1-.8**2)],[1,-.8],rng.normal(size=n+1000))[1000:]
        fgn=fractional_gaussian_noise(rng,n,hurst=.85)
        cases={'iid':rng.normal(size=n),'short_memory_logvol':np.exp(.6*ar)*rng.normal(size=n),
               'long_memory_logvol':np.exp(.6*fgn)*rng.normal(size=n),
               'variance_break':rng.normal(size=n)*np.repeat([.5,3.],n//2)}
        for name,r in cases.items():
            vp=dependence_diagnostics(sampled(r),c)['volatility_persistence'];d=vp['decay_comparison']
            rows.append({'case':name,'trial':i,'stable_slow_power_pattern':d['stable_slow_power_pattern'],'lo_persistence':persistence_evidence(vp['long_memory_test']),
                'full_preferences':[r.get('preferred') for r in d['rows'] if r['period']=='full']})
    strong=[]
    for i in range(40):
        rng=np.random.default_rng(77100+i);r=rng.normal(size=2000)
        vol=np.ones(2000)*.2;vol[500:600]=3;r*=vol
        d=intermittency_test(sampled(r),c,str(i))
        strong.append(sum(row['reject'] for row in d['rows'])>=2)
    result={'n_returns':8192,'trials':20,'seed_start':88200,'K':50,'rows':rows,
            'stable_counts':{name:sum(r['stable_slow_power_pattern'] for r in rows if r['case']==name) for name in cases},
            'fano_concentrated_volatility':{'trials':40,'n_returns':2000,'count':sum(strong)},
            'elapsed_seconds':time.monotonic()-start}
    with open(args.output,'w') as f:json.dump(result,f,indent=2,allow_nan=False)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
if __name__=='__main__':main()
