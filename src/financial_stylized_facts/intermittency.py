"""Extreme-event dispersion against within-segment exchangeability."""
import hashlib
import numpy as np
from .conditional import continuous_segments


def seed_for(config, key, module):
    digest = hashlib.sha256((module+'\0'+key).encode()).digest()
    return np.random.SeedSequence([config.bootstrap_seed, int.from_bytes(digest[:8], 'big')])


def fano(counts):
    counts = np.asarray(counts, dtype=float)
    return float(counts.var(ddof=1)/counts.mean()) if len(counts)>1 and counts.mean()>0 else None


def intermittency_test(sampled, config, seed_key=''):
    arrays = [g.log_return.to_numpy(dtype=float) for _,g in continuous_segments(sampled)]
    n = sum(map(len, arrays))
    result = dict(status='insufficient_data', reason='至少需要 20 个完整窗口及 10 次极端事件',
                  method='within_continuous_segment_permutation_fano', quantile=config.intermittency_quantile,
                  threshold=None, threshold_definition='abs(return) > full_path_quantile_linear',
                  null='event locations exchangeable within each retained continuous segment',
                  reps=config.permutation_reps, family_size=len(config.intermittency_windows), rows=[],
                  n=n, estimated_work=0, seed_key=seed_key)
    if not n:
        return result
    threshold = float(np.quantile(np.abs(np.concatenate(arrays)), config.intermittency_quantile))
    result['threshold'] = threshold
    events = [np.abs(a)>threshold for a in arrays]
    result['total_events'] = sum(int(a.sum()) for a in events)
    work=0
    for window in config.intermittency_windows:
        parts = [a[:len(a)//window*window] for a in events if len(a)>=window]
        counts = np.concatenate([a.reshape(-1,window).sum(axis=1) for a in parts]) if parts else np.array([])
        retained=sum(map(len,parts)); nevents=int(counts.sum())
        row=dict(window=window,windows=len(counts),retained_returns=retained,omitted_returns=n-retained,
                 events=nevents,fano=fano(counts),null_lower=None,null_upper=None,p_value=None,
                 family_adjusted_p=None,reject=False,status='insufficient_data',reason=result['reason'])
        result['rows'].append(row)
        if len(counts)<20 or nevents<10 or row['fano'] is None:
            continue
        if not config.permutation_reps:
            row.update(status='disabled',reason='置换检验已关闭');continue
        estimate=retained*config.permutation_reps
        work+=estimate
        if work>config.permutation_max_work:
            row.update(status='budget_exceeded',reason='达到逐路径置换工作量上限；本尺度未运行');continue
        rng=np.random.default_rng(seed_for(config,seed_key,f'fano:{window}'))
        null=np.empty(config.permutation_reps)
        for b in range(len(null)):
            shuffled=np.concatenate([rng.permutation(a).reshape(-1,window).sum(axis=1) for a in parts])
            null[b]=fano(shuffled)
        lo,hi=np.quantile(null,[.025,.975])
        p=float((1+np.count_nonzero(null>=row['fano']-1e-12))/(len(null)+1))
        adjusted=min(1.,p*result['family_size'])
        row.update(status='computed',reason=None,null_lower=float(lo),null_upper=float(hi),
                   p_value=p,family_adjusted_p=adjusted,reject=adjusted<=.05)
        if np.ptp(null)<1e-12:
            row.update(status='degenerate_null',reason='条件置换未改变计数离散程度，无法区分时间聚集',reject=False)
    result['estimated_work']=work
    computed=sum(r['status']=='computed' for r in result['rows'])
    if computed:
        result.update(status='computed' if computed==len(result['rows']) else 'partially_computed',reason=None)
    return result
