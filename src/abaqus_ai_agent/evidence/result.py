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
            step_times = {}
            for k in steps:
                frames = list(getattr(data.steps[k], "frames", ()) or ()) if hasattr(data.steps, "__getitem__") else []
                step_times[k] = {
                    "first_frame_value": getattr(frames[0], "frameValue", None) if frames else None,
                    "last_frame_value": getattr(frames[-1], "frameValue", None) if frames else None,
                    "frame_count": len(frames),
                }
            return {
                "status": "available",
                "step_count": len(steps),
                "steps": steps,
                "instances": instances,
                "step_frames": step_frames,
                "step_times": step_times,
            }
        return {"status": "invalid", "raw": data}
    steps = data.get("steps", [])
    return {
        "status": "available",
        "step_count": len(steps),
        "steps": list(steps),
        "instances": list(data.get("instances", [])),
        "step_frames": dict(data.get("step_frames", {})),
        "step_times": dict(data.get("step_times", {})),
    }
