import json

from ..contracts.session import SessionHealth


def session_health(executor):
    code = """import json, os, sys
result={}
try:
    from abaqus import getVersion
    result['abaqus_version']=str(getVersion())
except Exception:
    result['abaqus_version']='unknown'
result['python_version']=sys.version
result['connected']=True
result['gui_available']=bool(globals().get('session'))
result['workdir']=os.getcwd()
result['model_count']=len(mdb.models) if 'mdb' in globals() else 0
result['job_count']=len(mdb.jobs) if 'mdb' in globals() else 0
result['current_model']=None
result['current_viewport']=None
if 'mdb' in globals() and mdb.models:
    result['current_model']=next(iter(mdb.models.keys()))
if 'session' in globals():
    try: result['current_viewport']=session.currentViewportName
    except Exception: pass
caps=[]
if 'mdb' in globals(): caps.append('model_inspection')
if 'mdb' in globals() and hasattr(mdb, 'jobs'): caps.append('job')
try:
    import odbAccess
    caps.append('odb')
except Exception:
    pass
if 'session' in globals(): caps.append('viewport')
result['capabilities']=caps
try:
    if mdb.jobs:
        result['last_job_status']=str(list(mdb.jobs.values())[-1].status)
except Exception:
    pass
print(json.dumps(result))
"""
    raw = executor.execute(code)
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(str(raw).strip().splitlines()[-1])
        except Exception:
            data = {"connected": False, "metadata": {"raw": str(raw)}}
    return SessionHealth(
        connected=bool(data.get("connected")),
        abaqus_version=str(data.get("abaqus_version", "unknown")),
        python_version=str(data.get("python_version", "")),
        gui_available=bool(data.get("gui_available")),
        current_model=data.get("current_model"),
        current_viewport=data.get("current_viewport"),
        workdir=data.get("workdir"),
        model_count=int(data.get("model_count", 0)),
        job_count=int(data.get("job_count", 0)),
        capabilities=tuple(data.get("capabilities", ())),
        last_job_status=data.get("last_job_status"),
        metadata={k:v for k,v in data.items() if k not in (
            "connected","abaqus_version","python_version","gui_available",
            "current_model","current_viewport","workdir","model_count",
            "job_count","capabilities","last_job_status")}
    )
