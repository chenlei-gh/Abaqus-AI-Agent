def classify_job_status(status):
    value = str(status).upper()
    if value in ("COMPLETED", "JOB_COMPLETED"):
        return "completed"
    if value in ("ABORTED", "TERMINATED", "ERROR"):
        return "failed"
    if value in ("RUNNING", "SUBMITTED", "CHECK_RUNNING", "ANALYSIS_RUNNING"):
        return "running"
    return "unknown"


def summarize_odb(data):
    """Normalize the minimal metadata returned by an ODB inspector."""
    if not isinstance(data, dict):
        if hasattr(data, "steps"):
            steps = list(data.steps.keys()) if hasattr(data.steps, "keys") else list(data.steps)
            instances = list(data.rootAssembly.instances.keys()) if hasattr(data, "rootAssembly") and hasattr(data.rootAssembly, "instances") else []
            step_frames = {k: len(data.steps[k].frames) for k in steps if hasattr(data.steps[k], "frames")} if hasattr(data.steps, "__getitem__") else {}
            return {
                "status": "available",
                "step_count": len(steps),
                "steps": steps,
                "instances": instances,
                "step_frames": step_frames,
            }
        return {"status": "invalid", "raw": data}
    steps = data.get("steps", [])
    return {
        "status": "available",
        "step_count": len(steps),
        "steps": list(steps),
        "instances": list(data.get("instances", [])),
        "step_frames": dict(data.get("step_frames", {})),
    }
