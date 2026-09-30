from .client import AbaqusExecutor


def inspect_odb_script(path):
    return r'''from odbAccess import openOdb
import json
odb = openOdb(path=%r, readOnly=True)
out = {"steps": list(odb.steps.keys()), "instances": list(odb.rootAssembly.instances.keys())}
for step_name, step in odb.steps.items():
    out.setdefault("step_frames", {})[step_name] = len(step.frames)
print(json.dumps(out))
odb.close()
''' % path


def inspect_odb(executor, path):
    return executor.execute(inspect_odb_script(path))
