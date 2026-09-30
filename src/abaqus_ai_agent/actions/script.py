def _q(value):
    return repr(value)

def action_to_script(action):
    p, m, k = action.parameters, action.model_name, action.action_type
    if k == "material_elastic":
        return "model=mdb.models[%s]; mat=model.Material(%s); mat.Elastic(table=((%r,%r),))" % (_q(m), _q(p["name"]), p["youngs_modulus"], p["poisson"])
    if k == "material_density":
        return "mdb.models[%s].materials[%s].Density(table=((%r,),))" % (_q(m), _q(p["name"]), p["density"])
    if k == "material_plastic":
        return "mdb.models[%s].materials[%s].Plastic(table=%r)" % (_q(m), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "solid_section":
        return "mdb.models[%s].HomogeneousSolidSection(name=%s, material=%s, thickness=None)" % (_q(m), _q(p["name"]), _q(p["material"]))
    if k == "section_assignment":
        return "mdb.models[%s].parts[%s].SectionAssignment(region=%s, sectionName=%s)" % (_q(m), _q(p["part"]), p["region_expression"], _q(p["section"]))
    if k == "static_step":
        return "mdb.models[%s].StaticStep(name=%s, previous=%s, nlgeom=%s)" % (_q(m), _q(p["name"]), _q(p.get("previous", "Initial")), p.get("nlgeom", False))
    if k == "dynamic_explicit_step":
        return "mdb.models[%s].ExplicitDynamicsStep(name=%s, previous=%s, timePeriod=%r)" % (_q(m), _q(p["name"]), _q(p.get("previous", "Initial")), p["time_period"])
    if k == "frequency_step":
        return "mdb.models[%s].FrequencyStep(name=%s, previous=%s, numEigen=%d)" % (_q(m), _q(p["name"]), _q(p.get("previous", "Initial")), int(p["num_eigen"]))
    if k in ("fixed_bc", "displacement_bc", "symmetry_bc"):
        return _bc_script(action)
    if k in ("pressure_load", "concentrated_force", "body_force"):
        return _load_script(action)
    if k == "field_output":
        return "mdb.models[%s].fieldOutputRequests[%s].setValues(variables=%r)" % (_q(m), _q(p.get("request", "F-Output-1")), tuple(p.get("variables", ("S", "U", "RF"))))
    if k == "history_output":
        if not p.get("region_expression"):
            return "mdb.models[%s].historyOutputRequests[%s].setValues(variables=%r)" % (_q(m), _q(p.get("request", "H-Output-1")), tuple(p.get("variables", ("ALLIE",))))
        return "mdb.models[%s].HistoryOutputRequest(name=%s, createStepName=%s, variables=%r, region=%s)" % (_q(m), _q(p.get("request", "AI-History")), _q(p.get("step", "Step-1")), tuple(p.get("variables", ("ALLIE",))), p["region_expression"])
    if k == "create_job":
        return "mdb.Job(name=%s, model=%s, type=%s)" % (_q(p["name"]), _q(m), p.get("job_type", "STANDARD"))
    if k == "submit_job":
        return "mdb.jobs[%s].submit(consistencyChecking=OFF)" % _q(p["name"])
    if k == "seed_part":
        return "mdb.models[%s].parts[%s].seedPart(size=%r, deviationFactor=%r, minSizeFactor=%r)" % (_q(m), _q(p["part"]), p["size"], p.get("deviation_factor", .1), p.get("min_size_factor", .1))
    if k == "generate_mesh":
        return "mdb.models[%s].parts[%s].generateMesh()" % (_q(m), _q(p["part"]))
    if k == "mesh_controls":
        return "# Mesh controls require native region expressions; parameters=%r" % p
    if k == "element_type":
        return "# ElementType selection is model/version-specific; use region=%s elem_code=%r" % (p["region_expression"], p["elem_code"])
    if k == "tie":
        return "mdb.models[%s].Tie(name=%s, master=%s, slave=%s, positionToleranceMethod=COMPUTED)" % (_q(m), _q(p["name"]), p["master_expression"], p["slave_expression"])
    if k == "contact":
        return "# Contact requires model-specific ContactProperty/SurfaceToSurfaceContact definitions; parameters=%r" % p
    raise ValueError("unsupported action type: %s" % k)

def _bc_script(action):
    p, m = action.parameters, action.model_name
    region, name, step = p["region_expression"], p["name"], p.get("step", "Initial")
    if action.action_type == "fixed_bc":
        return "model=mdb.models[%s]; region=%s; model.EncastreBC(name=%s, createStepName=%s, region=region)" % (_q(m), region, _q(name), _q(step))
    if action.action_type == "symmetry_bc":
        method = {"X":"XsymmBC", "Y":"YsymmBC", "Z":"ZsymmBC"}.get(str(p.get("plane", "X")).upper())
        if not method: raise ValueError("symmetry plane must be X, Y or Z")
        return "model=mdb.models[%s]; region=%s; model.%s(name=%s, createStepName=%s, region=region)" % (_q(m), region, method, _q(name), _q(step))
    vals = [p.get(x) for x in ("u1","u2","u3","ur1","ur2","ur3")]
    return "model=mdb.models[%s]; region=%s; model.DisplacementBC(name=%s, createStepName=%s, region=region, u1=%r,u2=%r,u3=%r,ur1=%r,ur2=%r,ur3=%r)" % (_q(m), region, _q(name), _q(step), *vals)

def _load_script(action):
    p, m = action.parameters, action.model_name
    region, name, step = p["region_expression"], p["name"], p.get("step", "Step-1")
    if action.action_type == "pressure_load":
        return "mdb.models[%s].Pressure(name=%s, createStepName=%s, region=%s, magnitude=%r)" % (_q(m), _q(name), _q(step), region, p["magnitude"])
    if action.action_type == "body_force":
        return "mdb.models[%s].BodyForce(name=%s, createStepName=%s, region=%s, comp1=%r, comp2=%r, comp3=%r)" % (_q(m), _q(name), _q(step), region, p.get("comp1",0), p.get("comp2",0), p.get("comp3",0))
    return "mdb.models[%s].ConcentratedForce(name=%s, createStepName=%s, region=%s, cf1=%r,cf2=%r,cf3=%r)" % (_q(m), _q(name), _q(step), region, p.get("cf1",0), p.get("cf2",0), p.get("cf3",0))
