# Abaqus/CAE-side read-only model snapshot. Keep legacy-Python compatible.

def snapshot(mdb):
    result = {"models": {}}
    for model_name, model in mdb.models.items():
        result["models"][model_name] = {
            "parts": list(model.parts.keys()),
            "materials": list(model.materials.keys()),
            "sections": list(model.sections.keys()),
            "steps": list(model.steps.keys()),
            "loads": list(model.loads.keys()),
            "amplitudes": list(model.amplitudes.keys()),
            "predefined_fields": list(model.predefinedFields.keys()),
            "boundary_conditions": list(model.boundaryConditions.keys()),
            "interactions": list(model.interactions.keys()),
            "constraints": list(model.constraints.keys()),
            "assembly_instances": list(model.rootAssembly.instances.keys()),
            "sets": list(model.rootAssembly.sets.keys()),
            "surfaces": list(model.rootAssembly.surfaces.keys()),
            "jobs": list(mdb.jobs.keys()),
        }
    return result
