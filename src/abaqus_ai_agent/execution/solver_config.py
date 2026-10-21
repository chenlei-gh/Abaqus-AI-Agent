"""Explicit solver-parameter decisions for the production CAE job path.

This is not an adaptive selector. A value is forwarded to ``mdb.Job`` only when
the caller supplied it. Missing values stay omitted so Abaqus keeps its own
default. Queue resource fields are a ledger, not solver arguments.
"""
from dataclasses import dataclass


_EXPLICIT_JOB_KEYS = ("numCpus", "numDomains")
_REFUSED_WITHOUT_EVIDENCE = ("memory", "memoryPolicy", "precision", "mp_mode")


@dataclass(frozen=True)
class SolverParameterDecision:
    name: str
    value: object
    source: str
    evidence: str
    reason: str
    sent_to_solver: bool

    def __post_init__(self):
        if self.source not in (
            "explicit", "safe_default", "evidence_adjusted", "refused",
        ):
            raise ValueError("unsupported decision source: %s" % self.source)
        if self.source == "evidence_adjusted":
            raise ValueError("evidence-adjusted solver parameters are not enabled")
        if self.sent_to_solver and self.source != "explicit":
            raise ValueError("only an explicit caller value may be sent to the solver")


def _positive_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("%s must be a positive int, got %r" % (name, value))
    return value


def resolve_explicit_job_kwargs(job_options=None):
    """Split caller options into Job kwargs and a decision record.

    Returns ``(kwargs, decisions)``. ``kwargs`` contains only parameters that
    will actually be passed to ``mdb.Job``. Decisions for omitted parameters
    are marked ``not sent``.
    """
    options = dict(job_options or {})
    unknown = sorted(set(options) - set(_EXPLICIT_JOB_KEYS) - set(_REFUSED_WITHOUT_EVIDENCE))
    if unknown:
        raise ValueError("unsupported solver job option(s): %s" % ", ".join(unknown))

    kwargs = {}
    decisions = []
    for name in _REFUSED_WITHOUT_EVIDENCE:
        if name not in options:
            continue
        decisions.append(SolverParameterDecision(
            name=name,
            value=options[name],
            source="refused",
            evidence="none",
            reason="no verified consumption path; refusing to apply or invent a solver setting",
            sent_to_solver=False,
        ))

    requested_cpus = options.get("numCpus")
    requested_domains = options.get("numDomains")
    if requested_cpus is None and requested_domains is None:
        decisions.append(SolverParameterDecision(
            name="numCpus",
            value=None,
            source="safe_default",
            evidence="omitted",
            reason="caller did not set numCpus; Abaqus default of 1 is left unchanged",
            sent_to_solver=False,
        ))
        return kwargs, tuple(decisions)

    if requested_cpus is not None:
        kwargs["numCpus"] = _positive_int("numCpus", requested_cpus)
        decisions.append(SolverParameterDecision(
            name="numCpus",
            value=kwargs["numCpus"],
            source="explicit",
            evidence="caller",
            reason="caller supplied numCpus; forwarded unchanged",
            sent_to_solver=True,
        ))
    if requested_domains is not None:
        kwargs["numDomains"] = _positive_int("numDomains", requested_domains)
        decisions.append(SolverParameterDecision(
            name="numDomains",
            value=kwargs["numDomains"],
            source="explicit",
            evidence="caller",
            reason="caller supplied numDomains; forwarded unchanged",
            sent_to_solver=True,
        ))
    elif requested_cpus is not None:
        decisions.append(SolverParameterDecision(
            name="numDomains",
            value=None,
            source="safe_default",
            evidence="omitted",
            reason="numDomains was not supplied; not inferred from numCpus",
            sent_to_solver=False,
        ))
    return kwargs, tuple(decisions)
