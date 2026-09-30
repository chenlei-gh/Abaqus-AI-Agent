def _q(value):
    return repr(value)


def action_to_script(action):
    p = action.parameters
    m = action.model_name
    kind = action.action_type
    if kind == "material_elastic":
        return "model=mdb.models[%s]; mat=model.Material(%s); mat.Elastic(table=((%r,%r),))" % (_q(m), _q(p["name"]), p["youngs_modulus"], p["poisson"])
    if kind == "material_density":
        return "mdb.models[%s].materials[%s].Density(table=((%r,),))" % (_q(m), _q(p["name"]), p["density"])
    if kind == "solid_section":
        return "mdb.models[%s].HomogeneousSolidSection(name=%s, material=%s, thickness=None)" % (_q(m), _q(p["name"]), _q(p["material"]))
    if kind == "static_step":
        return "mdb.models[%s].StaticStep(name=%s, previous=%s, nlgeom=%s)" % (_q(m), _q(p["name"]), _q(p.get("previous", "Initial")), p.get("nlgeom", False))
    if kind == "fixed_bc":
        return _bc_script(action)
    if kind == "displacement_bc":
        return _bc_script(action)
    if kind == "pressure_load":
        return _load_script(action)
    if kind == "concentrated_force":
        return _load_script(action)
    if kind == "field_output":
        variables = tuple(p.get("variables", ("S", "U", "RF")))
        return "mdb.models[%s].fieldOutputRequests[%s].setValues(variables=%r)" % (_q(m), _q(p.get("request", "F-Output-1")), variables)
    if kind == "create_job":
        return "mdb.Job(name=%s, model=%s)" % (_q(p["name"]), _q(m))
    if kind == "submit_job":
        return "mdb.jobs[%s].submit(consistencyChecking=OFF)" % _q(p["name"])
    if kind == "mesh_controls":
        return "# mesh_controls requires native region expressions; parameters=%r" % p
    if kind == "section_assignment":
        return "mdb.models[%s].parts[%s].SectionAssignment(region=%s, sectionName=%s)" % (_q(m), _q(p["part"]), p["region_expression"], _q(p["section"]))
    if kind == "tie":
        return "mdb.models[%s].Tie(name=%s, master=%s, slave=%s, positionToleranceMethod=COMPUTED)" % (_q(m), _q(p["name"]), p["master_expression"], p["slave_expression"])
    raise ValueError("unsupported action type: %s" % kind)


def _bc_script(action):
    p, m = action.parameters, action.model_name
    region = p["region_expression"]
    name, step = p["name"], p.get("step", "Initial")
    if action.action_type == "fixed_bc":
        return "model=mdb.models[%s]; region=%s; model.EncastreBC(name=%s, createStepName=%s, region=region)" % (_q(m), region, _q(name), _q(step))
    vals = (p.get("u1"), p.get("u2"), p.get("u3"), p.get("ur1"), p.get("ur2"), p.get("ur3"))
    return "model=mdb.models[%s]; region=%s; model.DisplacementBC(name=%s, createStepName=%s, region=region, u1=%r,u2=%r,u3=%r,ur1=%r,ur2=%r,ur3=%r)" % (_q(m), region, _q(name), _q(step), vals[0], vals[1], vals[2], vals[3], vals[4], vals[5])


def _load_script(action):
    p, m = action.parameters, action.model_name
    region = p["region_expression"]
    name, step = p["name"], p.get("step", "Step-1")
    if action.action_type == "pressure_load":
        return "mdb.models[%s].Pressure(name=%s, createStepName=%s, region=%s, magnitude=%r)" % (_q(m), _q(name), _q(step), region, p["magnitude"])
    return "mdb.models[%s].ConcentratedForce(name=%s, createStepName=%s, region=%s, cf1=%r,cf2=%r,cf3=%r)" % (_q(m), _q(name), _q(step), region, p.get("cf1", 0.0), p.get("cf2", 0.0), p.get("cf3", 0.0))
