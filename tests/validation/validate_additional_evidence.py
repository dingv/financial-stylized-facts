"""Bounded Monte Carlo audit for Fano tests and fitted GARCH references.

Run manually with --output /tmp/validation.json. No market data is altered.
"""
import argparse,json,time,os
from dataclasses import replace
import numpy as np
from scipy.stats import beta
from financial_stylized_facts.data import AnalysisConfig
from financial_stylized_facts.intermittency import intermittency_test
from financial_stylized_facts.conditional import fit_garch
from financial_stylized_facts.conditional_inference import conditional_reference
from financial_stylized_facts.dependence import dependence_diagnostics
from tests.test_conditional import sampled,garch_returns


def rate(flags):
    n=len(flags);k=sum(flags)
    return {'count':k,'trials':n,'rate':k/n if n else None,
            'binomial_95_interval':[float(beta.ppf(.025,k,n-k+1)) if k else 0.,float(beta.ppf(.975,k+1,n-k)) if k<n else 1.]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',required=True);p.add_argument('--trials',type=int,default=40);args=p.parse_args()
    if not 1<=args.trials<=100:
        raise ValueError('trials must be 1–100')
    os.sched_setaffinity(0,{min(os.sched_getaffinity(0))})
    start=time.monotonic();c=AnalysisConfig(permutation_reps=199,conditional_bootstrap_reps=99,volatility_max_lag=50,long_memory='off')
    output={'seed_start':77100,'trials':args.trials,'n_returns':2000,'config':{'permutation_reps':199,'conditional_bootstrap_reps':99},'cases':{}}
    for label in ['iid_gaussian','iid_student','clustered_volatility']:
        decisions=[]
        for i in range(args.trials):
            rng=np.random.default_rng(77100+i)
            r=rng.standard_t(5,2000) if label=='iid_student' else rng.normal(size=2000)
            if label=='clustered_volatility':
                r*=np.tile(np.r_[np.ones(200)*.2,np.ones(200)*3.],5)
            result=intermittency_test(sampled(r),c,str(i))
            decisions.append(sum(row['reject'] for row in result['rows'])>=2)
        output['cases']['fano_'+label]=rate(decisions)
        print(label,output['cases']['fano_'+label],flush=True)
    for student in [False,True]:
        rejected=[];supported=[];adequacy=[];unavailable=0
        for i in range(args.trials):
            r=garch_returns(seed=77100+i,n=2000,student=student);fit,a=fit_garch(r)
            if a is None:
                unavailable+=1;continue
            ref=conditional_reference(r,fit,a,c,str(i))
            if ref['status']!='computed':
                unavailable+=1;continue
            rejected.append(ref['joint_tail_p']<=.05)
            adequacy.append(ref['adequacy_rejected'])
            supported.append(ref['joint_tail_p']<=.05 and not ref['adequacy_rejected'])
        output['cases']['garch_student' if student else 'garch_gaussian']={'tail_rejection':rate(rejected),'supported_after_adequacy':rate(supported),'adequacy_rejection':rate(adequacy),'unavailable':unavailable}
        print('student',student,output['cases']['garch_student' if student else 'garch_gaussian'],flush=True)
    output['elapsed_seconds']=time.monotonic()-start
    with open(args.output,'w') as f:json.dump(output,f,indent=2,allow_nan=False)
if __name__=='__main__':main()
