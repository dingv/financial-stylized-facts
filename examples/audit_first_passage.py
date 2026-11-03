"""Direct nested-loop audit of first-passage exports on prepared real inputs.

No data download or model run. Requires paired CASE/input and CASE/report trees.
"""
import argparse
import json
from pathlib import Path

import numpy as np

from financial_stylized_facts.data import AnalysisConfig,read_prices,sample_path


def audit(input_root,report_root):
    records=[]
    for p in sorted(report_root.glob('*/report/results.json')):
        result=json.loads(p.read_text())
        case=p.parent.parent.name
        c=AnalysisConfig(**result['config'])
        prices=read_prices(input_root/case/'input/prices.csv',c)
        for group in result['groups']:
            selected=prices[(prices.asset_id==group['asset_id'])&(prices.path_id==group['path_id'])]
            frame,_=sample_path(selected,c)
            fp=group['first_passage']
            for threshold in fp['thresholds']:
                all_rows=[]
                for _,s in frame.groupby('session_id',sort=False):
                    v=s.price.to_numpy(float)
                    for start in range(len(v)):
                        if not np.isfinite(v[start]):
                            continue
                        up=down=None
                        observed=0
                        for step in range(1,c.first_passage_horizon+1):
                            end=start+step
                            if end>=len(v) or not np.isfinite(v[end]):
                                break
                            observed=step
                            change=float(np.log(v[end]/v[start]))
                            if up is None and change>=threshold['log_threshold']:
                                up=step
                            if down is None and change<=-threshold['log_threshold']:
                                down=step
                        all_rows.append((up,down,observed))
                full=[r for r in all_rows if r[2]==c.first_passage_horizon]
                assert len(all_rows)==fp['all_starts'] and len(full)==fp['full_horizon_starts']
                for index,name in enumerate(['up','down']):
                    for row in threshold[name]['curve']:
                        h=row['horizon']
                        hits=sum(r[index] is not None and r[index]<=h for r in all_rows)
                        unknown=sum(r[index] is None and r[2]<h for r in all_rows)
                        full_hits=sum(r[index] is not None and r[index]<=h for r in full)
                        assert (hits,unknown,full_hits)==(row['observed_hits'],row['early_censored'],row['full_hits'])
                        assert row['all_start_lower_bound']==hits/len(all_rows)
                        assert row['all_start_upper_bound']==(hits+unknown)/len(all_rows)
                        expected=full_hits/len(full) if len(full)>=c.first_passage_min_starts else None
                        assert row['full_cdf']==expected
            records.append({'case':case,'asset':group['asset_id'],'full_starts':fp.get('full_horizon_starts'),
                            'all_starts':fp.get('all_starts'),'status':fp['status'],
                            'hit_probabilities':[{ 'threshold':t['configured_threshold'],
                                 'up':t['up']['full_hit_probability'],'down':t['down']['full_hit_probability']}
                                 for t in fp['thresholds']]})
    if not records:
        raise ValueError('No reports found')
    out={'status':'passed','reference':'direct loops over original sampled slots; log of price ratios','cases':records}
    (report_root/'first-passage-audit.json').write_text(json.dumps(out,indent=2,allow_nan=False))
    print(json.dumps(out))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inputs',type=Path,required=True)
    p.add_argument('--reports',type=Path,required=True)
    args=p.parse_args()
    audit(args.inputs,args.reports)
