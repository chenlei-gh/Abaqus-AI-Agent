from enum import Enum


class EngineeringStatus(str, Enum):
    EXECUTION_FAILED = "EXECUTION_FAILED"
    SOLVER_FAILED = "SOLVER_FAILED"
    ODB_MISSING = "ODB_MISSING"
    RESULT_INVALID = "RESULT_INVALID"
    RESULT_SUSPICIOUS = "RESULT_SUSPICIOUS"
    RESULT_VALID = "RESULT_VALID"


def classify_engineering_result(job_state, odb_available, result_valid=None,
                                suspicious=False):
    state = str(job_state).upper()
    if state not in ("COMPLETED", "JOB_COMPLETED"):
        return EngineeringStatus.SOLVER_FAILED
    if not odb_available:
        return EngineeringStatus.ODB_MISSING
    if suspicious:
        return EngineeringStatus.RESULT_SUSPICIOUS
    if result_valid is False:
        return EngineeringStatus.RESULT_INVALID
    if result_valid is True:
        return EngineeringStatus.RESULT_VALID
    return EngineeringStatus.RESULT_SUSPICIOUS
