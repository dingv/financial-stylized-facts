"""Finite-range ACF model comparison, without iid regression standard errors."""
import numpy as np
from scipy.optimize import minimize_scalar


def fit_decay(lags, values, kind, exposure=None):
    """Fit every signed ACF ordinate on its original scale with equal weight.

    Analytically eliminate the amplitude, then minimize over the shape. Both
    models have two parameters. R² and held-out-lag error are fit diagnostics,
    not independent-observation likelihood tests.
    """
    k,y=np.asarray(lags,dtype=float),np.asarray(values,dtype=float)
    if len(k)<8 or not np.isfinite(y).all() or not np.isfinite(k).all() or (k<=0).any():
        return dict(status='insufficient_data',reason='需要至少 8 个完整的正滞后 ACF 点')
    if kind not in {'power','exponential'}:
        raise ValueError('kind must be power or exponential')
    exposure=np.ones(len(k)) if exposure is None else np.asarray(exposure,float)
    if exposure.shape!=k.shape or not np.isfinite(exposure).all() or (exposure<=0).any() or (exposure>1).any():
        raise ValueError('exposure must be finite, positive, at most one and aligned')
    bounds=(1e-5,3.) if kind=='power' else (1e-5,5.)
    def basis(shape):
        return exposure*((k/k[0])**(-shape) if kind=='power' else np.exp(-shape*(k-k[0])))
    def objective(shape, detail=False):
        b=basis(shape);amp=float(np.clip(np.dot(b,y)/np.dot(b,b),0,1))
        pred=amp*b;err=float(np.sum((y-pred)**2))
        return (amp,pred,err) if detail else err
    # Coarse log-spaced search plus bounded refinement avoids assuming globally
    # unimodal shape loss over the full parameter interval.
    grid=np.geomspace(*bounds,80);j=int(np.argmin([objective(x) for x in grid]))
    opt=minimize_scalar(objective,bounds=(grid[max(0,j-1)],grid[min(len(grid)-1,j+1)]),method='bounded',options={'xatol':1e-10})
    candidates=[bounds[0],bounds[1],float(opt.x)]
    shape=min(candidates,key=objective);amp,pred,sse=objective(shape,True)
    sst=float(np.sum((y-y.mean())**2))
    boundary=amp<=1e-8 or amp>=1-1e-8 or shape<=bounds[0]*1.01 or shape>=bounds[1]*.999
    return dict(status='computed',reason=None,kind=kind,amplitude=amp,shape=float(shape),
                parameter='beta' if kind=='power' else 'lambda',anchor_lag=float(k[0]),
                sse=sse,rmse=float(np.sqrt(sse/len(y))),r_squared=1-sse/sst if sst>1e-20 else None,
                boundary=boundary,lags=k.astype(int).tolist(),predicted=pred.tolist())


def predict(fit,k,exposure=1.):
    k=np.asarray(k,float)
    return np.asarray(exposure)*fit['amplitude']*((k/fit['anchor_lag'])**(-fit['shape']) if fit['kind']=='power'
           else np.exp(-fit['shape']*(k-fit['anchor_lag'])))


def compare_decay(acf, start, end, minimum_pairs):
    bylag=dict(zip(acf['lags'],zip(acf['values'],acf['pair_counts'])))
    row=dict(status='insufficient_data',reason='拟合范围须完整、至少 20 个滞后且每点配对充分',
             start_lag=start,end_lag=end,minimum_pairs=minimum_pairs)
    if end-start+1<20 or any(k not in bylag or bylag[k][0] is None or bylag[k][1]<minimum_pairs for k in range(start,end+1)):
        return row
    k=np.arange(start,end+1);y=np.array([bylag[i][0] for i in k],float)
    exposure=np.array([bylag[i][1] for i in k],float)/acf.get('n',max(c for _,c in bylag.values()))
    fits={kind:fit_decay(k,y,kind,exposure) for kind in ('power','exponential')}
    split=int(len(k)*2/3)
    for kind,f in fits.items():
        trained=fit_decay(k[:split],y[:split],kind,exposure[:split])
        f['heldout_rmse']=float(np.sqrt(np.mean((y[split:]-predict(trained,k[split:],exposure[split:]))**2)))
        f['heldout_fit']= {key:trained[key] for key in ('amplitude','shape','anchor_lag','boundary')}
    power,exponential=fits.values()
    # Relative error margins are predefined operational rules, not p-values.
    preferred='power' if power['rmse']<.9*exponential['rmse'] and power['heldout_rmse']<.9*exponential['heldout_rmse'] else 'exponential' if exponential['rmse']<.9*power['rmse'] and exponential['heldout_rmse']<.9*power['heldout_rmse'] else 'undetermined'
    usable=(not power['boundary'] and power['r_squared'] is not None and power['r_squared']>=.2 and np.mean(y>0)>=.8)
    row.update(status='computed',reason=None,models=fits,positive_fraction=float(np.mean(y>0)),
               train_end_lag=int(k[split-1]),preferred=preferred,
               exposure_min=float(exposure.min()),exposure_max=float(exposure.max()),
               slow_power_pattern=bool(usable and preferred=='power' and 0<power['shape']<1))
    return row


def decay_diagnostics(persistence, config):
    rows=[];end=config.volatility_max_lag
    for period,acf in [('full',persistence['full'])]+[(f"block_{b['block']}",b['acf']) for b in persistence['blocks']]:
        for start in (1,5):
            row=compare_decay(acf,start,end,max(config.min_pairs,200,5*end))
            rows.append(dict(period=period,**row))
    full=[r for r in rows if r['period']=='full']
    computed=[r for r in full if r['status']=='computed']
    stable=bool(rows) and all(r.get('slow_power_pattern',False) for r in rows)
    return dict(status='computed' if len(computed)==2 else 'partially_computed' if computed else 'insufficient_data',
                reason=None if computed else '数据不足以覆盖预定衰减范围；未缩短范围挑选拟合',
                method='bounded_nonlinear_least_squares_signed_acf', rows=rows,
                ranges=[[1,end],[5,end]], stable_slow_power_pattern=stable,
                verified_long_memory=False, inferential_p=None,
                preference_rule='both full-range and held-out-lag RMSE improve by >10%',
                stability_rule='both ranges and every chronological block: beta in (0,1), R2>=.2, >=80% positive, no boundary, power preferred')


def persistence_evidence(memory):
    """Use existing corrected Lo tests; lower-tail rejections are not persistence.

    Require every positive bandwidth on each full segment and both halves.
    Quarter-window results remain a finer stability check, not a selection pool.
    """
    bands=[q for q in memory.get('bandwidths',[]) if q>0]
    rows=[r for r in memory.get('rows',[]) if r['partition'] in (1,2) and r['bandwidth']>0]
    segments=sorted({r['segment'] for r in rows})
    expected=len(segments)*3*len(bands)
    complete=bool(expected) and len(rows)==expected and all(r['status']=='computed' for r in rows)
    supported=complete and all(r['position']=='above' and r['reject_short_memory_family'] for r in rows)
    full=[r for r in rows if r['partition']==1]
    full_supported=bool(full) and len(full)==len(segments)*len(bands) and all(r['status']=='computed' and r['position']=='above' and r['reject_short_memory_family'] for r in full)
    return dict(status=memory.get('status','unavailable'),complete=complete,stable_upper_rejection=bool(supported),
                full_upper_rejection=bool(full_supported),required_tests=expected,
                computed_tests=sum(r['status']=='computed' for r in rows),
                largest_family_p=max((r['family_adjusted_p'] for r in rows if r.get('family_adjusted_p') is not None),default=None),
                rule='all positive-q full and half windows reject in upper tail; original all-window family correction retained')
