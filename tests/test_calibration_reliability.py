import math
import pytest
from abaqus_ai_agent.calibration import identify_parameters
from abaqus_ai_agent.contracts.calibration import CalibrationObservation, ParameterBound
from abaqus_ai_agent.reliability import empirical_reliability, fit_weibull_2p, weibull_b_life, weibull_reliability

def test_bounded_parameter_identification_is_deterministic():
    observations=tuple(CalibrationObservation("o%d"%x,x,2.0*x+1.0) for x in (0.0,1.0,2.0,3.0))
    def model(p,x): return p["slope"]*x+p["intercept"]
    result=identify_parameters(observations,model,(ParameterBound("slope",1.0,0.0,4.0,0.5),ParameterBound("intercept",0.0,-2.0,3.0,0.5)))
    assert result.converged and result.parameters["slope"]==pytest.approx(2.0) and result.parameters["intercept"]==pytest.approx(1.0)
    assert result.objective==pytest.approx(0.0)

def test_calibration_uncertainty_weights_residuals():
    observations=(CalibrationObservation("a",1.0,1.0,0.1),CalibrationObservation("b",2.0,1.0,10.0))
    result=identify_parameters(observations,lambda p,x:p["offset"],(ParameterBound("offset",0.0,-10.0,10.0,0.1),))
    assert result.parameters["offset"]==pytest.approx(1.0,abs=0.1)

def test_empirical_reliability_is_distribution_free():
    points=empirical_reliability((1,2,4))
    assert [p.reliability for p in points]==pytest.approx([2/3,1/3,0.0])

def test_weibull_fit_and_reliability():
    fit=fit_weibull_2p((1,2,3,4,5))
    assert fit.shape>0 and fit.scale>0
    result=weibull_reliability(fit,fit.scale)
    assert result.reliability==pytest.approx(math.exp(-1.0))
    assert weibull_b_life(fit,0.1)>0

def test_weibull_supports_right_censoring():
    fit=fit_weibull_2p((1,2,3),censored=(5,6))
    assert fit.failures==3 and fit.censored==2 and fit.converged
