from .client import AbaqusExecutor


MODEL_INFO_SCRIPT = r'''import json
result = {}
result["models"] = list(mdb.models.keys())
result["parts"] = {}
result["materials"] = {}
result["sections"] = {}
result["steps"] = {}
result["loads"] = {}
result["bcs"] = {}
result["interactions"] = {}
result["assembly_instances"] = {}
for name, model in mdb.models.items():
    result["parts"][name] = list(model.parts.keys())
    result["materials"][name] = list(model.materials.keys())
    result["sections"][name] = list(model.sections.keys())
    result["steps"][name] = list(model.steps.keys())
    result["loads"][name] = list(model.loads.keys())
    result["bcs"][name] = list(model.boundaryConditions.keys())
    result["interactions"][name] = list(model.interactions.keys())
    result["assembly_instances"][name] = list(model.rootAssembly.instances.keys())
print(json.dumps(result))
'''


def get_model_info(executor):
    if not isinstance(executor, AbaqusExecutor):
        raise TypeError("executor must implement AbaqusExecutor")
    return executor.execute(MODEL_INFO_SCRIPT)
