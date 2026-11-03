"""Fitted Gaussian-GARCH reference: simulate, refit, then evaluate residuals."""
import numpy as np
from scipy.stats import beta


def gaussian_garch(parameters, n, rng, burn=2000):
    """Stationary-variance initialization followed by burn-in; original units."""
    p=parameters
    if not 0<=p['alpha']+p['beta']<1 or p['omega']<=0:
        raise ValueError('Simulation requires stationary positive GARCH variance')
    shocks=rng.normal(size=n+burn)
    output=np.empty(len(shocks));variance=p['omega']/(1-p['alpha']-p['beta'])
    for i,e in enumerate(shocks):
        output[i]=np.sqrt(variance)*e
        variance=p['omega']+p['alpha']*output[i]**2+p['beta']*variance
    return output[burn:]+p['mu']


def portmanteau(z, squared=False, lags=10):
    x=np.asarray(z,float)
    x=x*x if squared else x.copy()
    x=x-x.mean();den=float(x@x);n=len(x)
    if den<=0 or n<=lags+1:
        return None
    return float(n*(n+2)*sum((float(x[k:]@x[:-k])/den)**2/(n-k) for k in range(1,lags+1)))


def conditional_reference(returns, fit, arrays, config, seed_key='', budget=None):
    """One-sided tail tests under the fitted composite Gaussian GARCH null.

    Re-estimation in each replicate accounts for fitting uncertainty to first
    order. Failed refits count as exceedances (conservative upper p bound), never
    silently disappear. This is a plug-in parametric bootstrap, not an exact test.
    """
    from .conditional import fit_garch
    from .intermittency import seed_for
    reps=config.conditional_bootstrap_reps
    result=dict(status='disabled',reason='条件厚尾模拟参照已关闭',method='gaussian_garch_simulate_refit',
                reps=reps,completed_reps=0,failed_reps=0,tests=[],null='stationary constant-mean Gaussian GARCH(1,1)',
                simulation_burn=2000,refit=True,seed_key=seed_key,estimated_work=0,
                tail_supported=False,adequacy_rejected=None)
    if not reps:
        return result
    if fit['parameters']['persistence']>=.995:
        result.update(status='unstable_null',reason='拟合持续性接近 1；平稳 Gaussian GARCH 模拟参照不可靠')
        return result
    work=(len(returns)+2000)*reps
    result['estimated_work']=work
    if budget is not None:
        if budget[0]+work>config.conditional_bootstrap_max_work:
            result.update(status='budget_exceeded',reason='超过逐路径模拟并重拟合的工作量预算');return result
        budget[0]+=work
    elif work>config.conditional_bootstrap_max_work:
        result.update(status='budget_exceeded',reason='超过模拟并重拟合的工作量预算');return result
    z=arrays['standardized_residual'];d=fit['residual_distribution']
    observed=[d['excess_kurtosis'],d['tail_counts']['3']['probability'],portmanteau(z),portmanteau(z,True)]
    if any(v is None or not np.isfinite(v) for v in observed):
        result.update(status='not_computable',reason='残差统计不可计算');return result
    rng=np.random.default_rng(seed_for(config,seed_key,'conditional-reference'))
    null=[]
    for _ in range(reps):
        r=gaussian_garch(fit['parameters'],len(returns),rng)
        try:
            fitted,values=fit_garch(r,config.garch_max_iter,config.garch_burn,10,config.min_pairs)
            if values is None:
                continue
            rd=fitted['residual_distribution'];zz=values['standardized_residual']
            stats=[rd['excess_kurtosis'],rd['tail_counts']['3']['probability'],portmanteau(zz),portmanteau(zz,True)]
            if all(v is not None and np.isfinite(v) for v in stats):
                null.append(stats)
        except (ValueError,RuntimeError,FloatingPointError,np.linalg.LinAlgError):
            continue
    count=len(null);failed=reps-count
    result.update(completed_reps=count,failed_reps=failed)
    if count<.95*reps:
        result.update(status='refit_failures',reason='成功重拟合不足 95%；不作推断');return result
    null=np.asarray(null)
    for i,name in enumerate(('excess_kurtosis','tail_probability_3sigma','residual_q10','squared_residual_q10')):
        exceed=int(np.count_nonzero(null[:,i]>=observed[i]))
        # Tail p bound includes every failed replicate. Plus-one never yields 0.
        lower=(1+exceed)/(reps+1);upper=(1+exceed+failed)/(reps+1)
        k=exceed+failed
        mc_low=float(beta.ppf(.025,k,reps-k+1)) if k else 0.
        mc_high=float(beta.ppf(.975,k+1,reps-k)) if k<reps else 1.
        result['tests'].append(dict(metric=name,estimate=float(observed[i]),
            null_lower=float(np.quantile(null[:,i],.025)),null_upper=float(np.quantile(null[:,i],.975)),
            p_value=upper,p_lower_bound=lower,p_upper_bound=upper,
            monte_carlo_interval=[mc_low,mc_high],exceedances=exceed))
    result.update(status='computed',reason=None)
    # The two upper-tail tests are an intersection requirement, not two chances
    # to reject. Across segments we additionally Bonferroni-adjust below.
    result['joint_tail_p']=max(t['p_value'] for t in result['tests'][:2])
    result['adequacy_p']=min(1.,2*min(t['p_value'] for t in result['tests'][2:]))
    result['adequacy_rejected']=result['adequacy_p']<=.05
    return result


def finalize_conditional(result, family_size):
    """Preserve planned segment multiplicity, including untested segments."""
    for row in result['segments']:
        ref=row.get('reference_test',{})
        ref['planned_segment_family']=family_size
        if ref.get('status')!='computed':
            continue
        p=min(1.,ref['joint_tail_p']*family_size)
        ref['family_adjusted_tail_p']=p
        ref['tail_supported']=bool(p<=.05 and not ref['adequacy_rejected'])
