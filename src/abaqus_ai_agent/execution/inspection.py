import json


def get_model_info(executor):
    """Read-only model inventory through the executor."""
    code = ("import json\nresult={}\n"
            "result['models']=list(mdb.models.keys())\n"
            "result['parts']=[]\nresult['instances']=[]\n"
            "result['materials']=[]\nresult['sections']=[]\nresult['steps']=[]\n"
            "result['boundary_conditions']=[]\nresult['loads']=[]\n"
            "result['interactions']=[]\nresult['output_requests']=[]\n"
            "result['jobs']=list(mdb.jobs.keys())\n"
            "for _n,_m in mdb.models.items():\n"
            " result['parts'] += list(_m.parts.keys())\n"
            " result['materials'] += list(_m.materials.keys())\n"
            " result['sections'] += list(_m.sections.keys())\n"
            " result['steps'] += list(_m.steps.keys())\n"
            " result['boundary_conditions'] += list(_m.boundaryConditions.keys())\n"
            " result['loads'] += list(_m.loads.keys())\n"
            " result['interactions'] += list(_m.interactions.keys())\n"
            " result['output_requests'] += list(_m.fieldOutputRequests.keys())\n"
            "for _a in mdb.models.values():\n"
            " pass\n"
            "print(json.dumps(result))")
    return executor.execute(code)


def snapshot_model(executor):
    return get_model_info(executor)


def runtime_info(executor):
    code = ("import sys, json\n"
            "r={}\n"
            "try: r['version']=str(session.aboutBox().split('\\n')[0])\n"
            "except: r['version']='unknown'\n"
            "r['python_version']=sys.version\n"
            "r['gui_available']=bool(globals().get('session'))\n"
            "r['capabilities']=['model_inspection','job','odb','viewport']\n"
            "print(json.dumps(r))")
    return executor.execute(code)


def viewport_state(executor):
    code = ("import json\n"
            "r={}\n"
            "try:\n"
            " v=session.viewports[session.currentViewportName]\n"
            " r['viewport_name']=session.currentViewportName\n"
            " r['displayed_object']=str(v.displayedObject)\n"
            " r['metadata']={}\n"
            "except Exception as e: r['error']=str(e)\n"
            "print(json.dumps(r))")
    return executor.execute(code)


def capture_viewport(executor, path="abaqus_viewport.png"):
    if hasattr(executor, "capture_viewport"):
        return executor.capture_viewport(path)
    return executor.execute("session.printToFile(fileName=%r, format=PNG, canvasObjects=(session.viewports[session.currentViewportName],))" % path)
