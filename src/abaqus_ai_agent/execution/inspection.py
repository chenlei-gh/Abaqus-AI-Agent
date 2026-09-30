import json


def get_model_info(executor):
    """Read-only model inventory through the executor."""
    code = ("import json\nresult={}\n"
            "result['models']=list(mdb.models.keys())\nresult['parts']=[]\nresult['instances']=[]\n"
            "result['materials']=[]\nresult['sections']=[]\nresult['steps']=[]\n"
            "result['boundary_conditions']=[]\nresult['loads']=[]\nresult['interactions']=[]\n"
            "result['output_requests']=[]\nresult['jobs']=list(mdb.jobs.keys())\n"
            "for _n,_m in mdb.models.items():\n"
            " result['parts'] += list(_m.parts.keys())\n"
            " result['materials'] += list(_m.materials.keys())\n"
            " result['sections'] += list(_m.sections.keys())\n"
            " result['steps'] += list(_m.steps.keys())\n"
            " result['boundary_conditions'] += list(_m.boundaryConditions.keys())\n"
            " result['loads'] += list(_m.loads.keys())\n"
            " result['interactions'] += list(_m.interactions.keys())\n"
            " result['output_requests'] += list(_m.fieldOutputRequests.keys())\n"
            " try: result['instances'] += list(_m.rootAssembly.instances.keys())\n"
            " except: pass\n"
            "print(json.dumps(result))")
    return executor.execute(code)


def snapshot_model(executor):
    return get_model_info(executor)


def runtime_info(executor):
    code = ("import sys, json\nresult={}\n"
            "try:\n from abaqus import getVersion\n result['version']=str(getVersion())\n"
            "except: result['version']='unknown'\n"
            "result['python_version']=sys.version\n"
            "result['gui_available']=bool(globals().get('session'))\n"
            "def _odb_probe():\n try:\n  import odbAccess; return True\n except Exception: return False\n"
            "def _contact_probe():\n"
            " try:\n"
            "  if 'mdb' not in globals() or not mdb.models: return False\n"
            "  return hasattr(next(iter(mdb.models.values())), 'ContactProperty')\n"
            " except Exception: return False\n"
            "result['capabilities']=[]\n"
            "for _name,_ok in (('model_inspection','mdb' in globals()),"
            "('job',hasattr(mdb,'jobs') if 'mdb' in globals() else False),"
            "('odb',_odb_probe()),('viewport','session' in globals()),"
            "('contact',_contact_probe())):\n"
            " if _ok: result['capabilities'].append(_name)\n"
            "print(json.dumps(result))")
    return executor.execute(code)


def viewport_state(executor):
    code = ("import json\nresult={}\n"
            "try:\n"
            " v=session.viewports[session.currentViewportName]\n"
            " result['viewport_name']=session.currentViewportName\n"
            " result['displayed_object']=str(v.displayedObject)\n"
            " try: result['projection']=str(v.view.cameraType)\n except: pass\n"
            "except Exception as e: result['error']=str(e)\n"
            "print(json.dumps(result))")
    return executor.execute(code)


def capture_viewport(executor, path="abaqus_viewport.png"):
    code = ("from abaqusConstants import PNG\n"
            "session.printToFile(fileName=%r, format=PNG, "
            "canvasObjects=(session.viewports[session.currentViewportName],))\n"
            "print(%r)") % (path, path)
    return executor.execute(code)
