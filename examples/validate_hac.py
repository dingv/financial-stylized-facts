"""Small fixed-seed coverage audit, not proof of universal HAC validity.

Run in the project Conda environment; put --output outside the repository.
All cases use the same N, bandwidths and repetitions. No fitted choices.
"""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.stats import binomtest, norm

from financial_stylized_facts.inference import acf_influence, hac_variances, pearson_influence


def run(output, repetitions=200, n=2000, seed=20261103):
    if output.exists():
        raise FileExistsError("Output exists")
    rng = np.random.default_rng(seed)
    bandwidths = (10, 20, 40)
    counts = {}
    start = time.monotonic()
    for _ in range(repetitions):
        x = rng.normal(size=n)
        noise = rng.normal(size=n+300)
        ar = np.zeros(n+300)
        for i in range(1, len(ar)):
            ar[i] = .6*ar[i-1]+noise[i]
        ar = ar[300:]
        cases = [("iid_return_acf", 0., acf_influence([x],1)),
                 ("iid_absolute_acf", 0., acf_influence([abs(x)],1)),
                 ("iid_squared_acf", 0., acf_influence([x*x],1)),
                 ("ar1_return_acf", .6, acf_influence([ar],1)),
                 ("iid_leverage", 0., pearson_influence([x],[x*x],1))]
        blocks = x.reshape(-1,5)
        c,f = abs(blocks.sum(axis=1)),abs(blocks).mean(axis=1)
        a,sa,_ = pearson_influence([f],[c],1)
        b,sb,_ = pearson_influence([f],[c],-1)
        cases.append(("iid_time_direction_difference",0.,(a-b,[sa[0]-sb[0]],len(c)-1)))
        for case,truth,(estimate,scores,_) in cases:
            for bandwidth,variance in hac_variances(scores,bandwidths).items():
                key = (case, bandwidth)
                margin = norm.ppf(.975)*np.sqrt(variance)
                counts[key] = counts.get(key,0)+int(estimate-margin<=truth<=estimate+margin)
    rows = []
    for (case, bandwidth),count in counts.items():
        interval = binomtest(count,repetitions).proportion_ci(method="wilson")
        rows.append({"case":case,"bandwidth":bandwidth,"covered":count,"coverage":count/repetitions,
                     "monte_carlo_wilson_95_interval":[interval.low,interval.high]})
    result = {"seed":seed,"repetitions":repetitions,"n":n,"bandwidths":bandwidths,"rows":rows,
              "elapsed_seconds":time.monotonic()-start,
              "scope":"Gaussian iid and stationary AR(1); all targets analytically known. No parameter search.",
              "limitation":"Finite Monte Carlo audit, not a guarantee for financial data. These raw-formula checks include time-direction bandwidths beyond the report sample gate; report availability still follows the separate gate."}
    output.write_text(json.dumps(result,indent=2,allow_nan=False))
    print(json.dumps({"output":str(output),"elapsed_seconds":result["elapsed_seconds"],
                      "coverage_range":[min(r["coverage"] for r in rows),max(r["coverage"] for r in rows)]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    args = parser.parse_args()
    run(args.output)
