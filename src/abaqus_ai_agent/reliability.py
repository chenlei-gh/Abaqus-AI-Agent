"""Empirical survival and two-parameter Weibull MLE with right censoring."""
import math
from .contracts.reliability import EmpiricalReliabilityPoint, ReliabilityResult, WeibullFit

def empirical_reliability(times):
    values = sorted(float(x) for x in times)
    if not values or any(not math.isfinite(x) or x < 0 for x in values): raise ValueError("failure times must be finite and non-negative")
    n = len(values)
    return tuple(EmpiricalReliabilityPoint(t, i, n-i, (n-i)/float(n)) for i,t in enumerate(values,1))

def _weibull_score(shape, observations):
    failures = [t for t,failed in observations if failed]
    if len(failures) < 2: raise ValueError("at least two failures are required")
    powered = [(t**shape, math.log(t)) for t,_ in observations]
    denom = sum(p for p,_ in powered)
    weighted_log = sum(p*logt for p,logt in powered)/denom
    mean_failed_log = sum(math.log(t) for t in failures)/len(failures)
    variance = sum(p*logt*logt for p,logt in powered)/denom - weighted_log**2
    return 1.0/shape + mean_failed_log - weighted_log, -1.0/(shape*shape)-variance

def fit_weibull_2p(times, censored=None, max_iterations=100, tolerance=1e-10):
    failures=[(float(t),True) for t in times]; censored_values=[(float(t),False) for t in (censored or ())]
    observations=failures+censored_values
    if len(failures)<2: raise ValueError("at least two failures are required")
    if any(not math.isfinite(t) or t<=0 for t,_ in observations): raise ValueError("reliability times must be finite and positive")
    shape,converged,iteration=1.0,False,0
    for iteration in range(1,int(max_iterations)+1):
        score,derivative=_weibull_score(shape,observations)
        if abs(score)<=tolerance: converged=True; break
        candidate=shape-score/derivative if derivative else shape*0.5
        if candidate<=0 or not math.isfinite(candidate): candidate=shape*0.5
        if abs(candidate-shape)<=tolerance*max(1.0,shape): shape,converged=candidate,True; break
        shape=candidate
    failed_count=len(failures)
    scale=(sum(t**shape for t,_ in observations)/failed_count)**(1.0/shape)
    log_likelihood=(failed_count*math.log(shape)-failed_count*shape*math.log(scale)
        +(shape-1.0)*sum(math.log(t) for t,_ in failures)-sum((t/scale)**shape for t,_ in observations))
    return WeibullFit(shape,scale,failed_count,len(censored_values),converged,iteration,log_likelihood)

def weibull_reliability(fit,time):
    if not isinstance(fit,WeibullFit): raise TypeError("fit must be WeibullFit")
    time=float(time)
    if not math.isfinite(time) or time<0: raise ValueError("time must be finite and non-negative")
    ratio=(time/fit.scale)**fit.shape; reliability=math.exp(-ratio)
    hazard=((fit.shape/fit.scale)*(time/fit.scale)**(fit.shape-1.0) if time>0 else (0.0 if fit.shape>=1.0 else math.inf))
    return ReliabilityResult(time,reliability,1.0-reliability,hazard)

def weibull_b_life(fit,probability):
    if not isinstance(fit,WeibullFit): raise TypeError("fit must be WeibullFit")
    probability=float(probability)
    if not 0.0<probability<1.0: raise ValueError("failure probability must be between 0 and 1")
    return fit.scale*(-math.log(1.0-probability))**(1.0/fit.shape)
