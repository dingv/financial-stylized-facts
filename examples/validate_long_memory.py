"""Bounded, fixed-seed audit: Lo R/S is sensitive to both memory and breaks.

No tuning on outcomes; raw per-test rates, not the report's family-adjusted rule.
All outputs belong in tmp. References/algorithm in docs/internal/long-memory.md.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.signal import lfilter
from scipy.stats import binomtest

from financial_stylized_facts.long_memory import modified_rs


def fractional_gaussian_noise(rng,n,hurst=.8):
    # Circulant embedding has exactly the requested finite fGn covariance.
    k=np.arange(n,dtype=float)
    cov=.5*(np.abs(k+1)**(2*hurst)-2*k**(2*hurst)+np.abs(k-1)**(2*hurst))
    eigen=np.fft.fft(np.r_[cov,0.,cov[:0:-1]]).real
    if eigen.min() < -1e-10:
        raise ValueError("Circulant embedding is not positive semidefinite")
    z=rng.normal(size=2*n)
    return np.fft.ifft(np.sqrt(np.maximum(eigen,0))*np.fft.fft(z)).real[:n]


def run(output,repetitions=200,n=4096,seed=20261103):
    if output.exists():
        raise FileExistsError(output)
    rng=np.random.default_rng(seed)
    bands=(0,10,20,40)
    counts={}
    start=time.monotonic()
    for _ in range(repetitions):
        iid=rng.normal(size=n)
        ar=lfilter([np.sqrt(1-.8**2)],[1,-.8],rng.normal(size=n+1000))[1000:]
        long=fractional_gaussian_noise(rng,n)
        cases={"iid_gaussian":iid,"short_memory_ar1_logvol":np.exp(.5*ar)*rng.normal(size=n),
               "long_memory_fgn_logvol_H08":np.exp(.5*long)*rng.normal(size=n),
               "variance_break_iid":iid*np.repeat([1.,4.],n//2)}
        for name,x in cases.items():
            for q in bands:
                r=modified_rs(abs(x),q)
                key=(name,q)
                counts[key]=counts.get(key,0)+int(r["asymptotic_p"]<.05)
    rows=[]
    for (case,q),hits in counts.items():
        ci=binomtest(hits,repetitions).proportion_ci(method="wilson")
        rows.append({"case":case,"bandwidth":q,"rejections":hits,"rate":hits/repetitions,
                     "monte_carlo_wilson_95":[ci.low,ci.high],"q0_is_iid_reference":q==0})
    result={"repetitions":repetitions,"n":n,"seed":seed,"rows":rows,
            "elapsed_seconds":time.monotonic()-start,
            "scope":"Single complete windows; unadjusted 5% asymptotic p. No parameter selection. Reports separately adjust all positive-q windows.",
            "limitation":"Finite-q, finite-sample size and power depend on the process. A variance break is not long memory; rejection is not proof."}
    output.write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    run(args.output)
