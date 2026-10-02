def _q(value):
    return repr(value)

def _amplitude(value, defaults):
    value = value or defaults
    if value in ("RAMP", "STEP", "DEFAULT"):
        return value
    return _q(value)

def _step_amplitude(value, default):
    value = value or default
    if value not in ("RAMP", "STEP"):
        raise ValueError("step amplitude must be RAMP or STEP")
    return value

def action_to_script(action):
    p, m, k = action.parameters, action.model_name, action.action_type
    if k == "python":
        return p["code"]
    if k == "material_elastic":
        return "model=mdb.models[%s]; mat=model.materials[%s] if %s in model.materials else model.Material(%s); mat.Elastic(table=((%r,%r),))" % (_q(m), _q(p["name"]), _q(p["name"]), _q(p["name"]), p["youngs_modulus"], p["poisson"])
    if k == "material_density":
        return "model=mdb.models[%s]; mat=model.materials[%s] if %s in model.materials else model.Material(%s); mat.Density(table=((%r,),))" % (_q(m), _q(p["name"]), _q(p["name"]), _q(p["name"]), p["density"])
    if k == "material_plastic":
        return "model=mdb.models[%s]; mat=model.materials[%s] if %s in model.materials else model.Material(%s); mat.Plastic(table=%r)" % (_q(m), _q(p["name"]), _q(p["name"]), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "material_conductivity":
        return "model=mdb.models[%s]; mat=model.materials[%s] if %s in model.materials else model.Material(%s); mat.Conductivity(table=%r)" % (_q(m), _q(p["name"]), _q(p["name"]), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "material_specific_heat":
        return "model=mdb.models[%s]; mat=model.materials[%s] if %s in model.materials else model.Material(%s); mat.SpecificHeat(table=%r)" % (_q(m), _q(p["name"]), _q(p["name"]), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "material_expansion":
        return "model=mdb.models[%s]; mat=model.materials[%s] if %s in model.materials else model.Material(%s); mat.Expansion(table=%r)" % (_q(m), _q(p["name"]), _q(p["name"]), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "solid_section":
        return "mdb.models[%s].HomogeneousSolidSection(name=%s, material=%s, thickness=None)" % (_q(m), _q(p["name"]), _q(p["material"]))
    if k == "section_assignment":
        return "mdb.models[%s].parts[%s].SectionAssignment(region=%s, sectionName=%s)" % (_q(m), _q(p["part"]), p["region_expression"], _q(p["section"]))
    if k == "static_step":
        args = ["name=%s" % _q(p["name"]), "previous=%s" % _q(p.get("previous", "Initial")),
                "nlgeom=%s" % p.get("nlgeom", False), "timePeriod=%r" % p.get("time_period", 1.0),
                "stabilizationMethod=%s" % p.get("stabilization_method", "NONE"),
                "timeIncrementationMethod=%s" % p.get("time_incrementation_method", "AUTOMATIC"),
                "maxNumInc=%d" % int(p.get("max_num_inc", 100)),
                "amplitude=%s" % _step_amplitude(p.get("amplitude"), "RAMP")]
        for key, arg in (("stabilization_magnitude", "stabilizationMagnitude"),
                         ("initial_inc", "initialInc"), ("min_inc", "minInc"), ("max_inc", "maxInc")):
            if p.get(key) is not None: args.append("%s=%r" % (arg, p[key]))
        return "from abaqusConstants import *; mdb.models[%s].StaticStep(%s)" % (_q(m), ", ".join(args))
    if k == "dynamic_explicit_step":
        args = ["name=%s" % _q(p["name"]), "previous=%s" % _q(p.get("previous", "Initial")),
                "timePeriod=%r" % p["time_period"], "nlgeom=%s" % p.get("nlgeom", True),
                "improvedDtMethod=%s" % p.get("improved_dt_method", True)]
        if p.get("max_increment") is not None: args.append("maxIncrement=%r" % p["max_increment"])
        return "from abaqusConstants import *; mdb.models[%s].ExplicitDynamicsStep(%s)" % (_q(m), ", ".join(args))
    if k == "implicit_dynamic_step":
        args = ["name=%s" % _q(p["name"]), "previous=%s" % _q(p.get("previous", "Initial")),
                "timePeriod=%r" % p.get("time_period", 1.0), "nlgeom=%s" % p.get("nlgeom", False),
                "timeIncrementationMethod=%s" % p.get("time_incrementation_method", "AUTOMATIC"),
                "maxNumInc=%d" % int(p.get("max_num_inc", 100)),
                "solutionTechnique=%s" % p.get("solution_technique", "FULL_NEWTON"),
                "reformKernel=%d" % int(p.get("reform_kernel", 8)),
                "amplitude=%s" % _step_amplitude(p.get("amplitude"), "STEP")]
        for key, arg in (("initial_inc", "initialInc"), ("min_inc", "minInc"), ("max_inc", "maxInc")):
            if p.get(key) is not None: args.append("%s=%r" % (arg, p[key]))
        return "from abaqusConstants import *; mdb.models[%s].ImplicitDynamicsStep(%s)" % (_q(m), ", ".join(args))
    if k == "frequency_step":
        return "mdb.models[%s].FrequencyStep(name=%s, previous=%s, numEigen=%d)" % (_q(m), _q(p["name"]), _q(p.get("previous", "Initial")), int(p["num_eigen"]))
    if k == "heat_transfer_step":
        args = ["name=%s" % _q(p["name"]), "previous=%s" % _q(p.get("previous", "Initial")),
                "response=%s" % p.get("response", "TRANSIENT"), "timePeriod=%r" % p.get("time_period", 1.0),
                "timeIncrementationMethod=%s" % p.get("time_incrementation_method", "AUTOMATIC"),
                "maxNumInc=%d" % int(p.get("max_num_inc", 100)), "amplitude=%s" % _amplitude(p.get("amplitude"), "RAMP")]
        for key, arg in (("initial_inc", "initialInc"), ("min_inc", "minInc"), ("max_inc", "maxInc")):
            if p.get(key) is not None: args.append("%s=%r" % (arg, p[key]))
        return "from abaqusConstants import *; mdb.models[%s].HeatTransferStep(%s)" % (_q(m), ", ".join(args))
    if k == "coupled_temp_displacement_step":
        args = ["name=%s" % _q(p["name"]), "previous=%s" % _q(p.get("previous", "Initial")),
                "response=%s" % p.get("response", "TRANSIENT"), "timePeriod=%r" % p.get("time_period", 1.0),
                "nlgeom=%s" % p.get("nlgeom", False), "timeIncrementationMethod=%s" % p.get("time_incrementation_method", "AUTOMATIC"),
                "maxNumInc=%d" % int(p.get("max_num_inc", 100)), "amplitude=%s" % _amplitude(p.get("amplitude"), "RAMP")]
        for key, arg in (("initial_inc", "initialInc"), ("min_inc", "minInc"), ("max_inc", "maxInc")):
            if p.get(key) is not None: args.append("%s=%r" % (arg, p[key]))
        return "from abaqusConstants import *; mdb.models[%s].CoupledTempDisplacementStep(%s)" % (_q(m), ", ".join(args))
    if k == "tabular_amplitude":
        args = ["name=%s" % _q(p["name"]), "data=%r" % (tuple(tuple(x) for x in p["data"]),),
                "timeSpan=%s" % p.get("time_span", "STEP")]
        if p.get("smooth") is not None: args.append("smooth=%r" % p["smooth"])
        return "from abaqusConstants import *; mdb.models[%s].TabularAmplitude(%s)" % (_q(m), ", ".join(args))
    if k == "smooth_step_amplitude":
        return "from abaqusConstants import *; mdb.models[%s].SmoothStepAmplitude(name=%s, data=%r, timeSpan=%s)" % (_q(m), _q(p["name"]), tuple(tuple(x) for x in p["data"]), p.get("time_span", "STEP"))
    if k == "periodic_amplitude":
        return "from abaqusConstants import *; mdb.models[%s].PeriodicAmplitude(name=%s, frequency=%r, start=%r, a_0=%r, data=%r, timeSpan=%s)" % (_q(m), _q(p["name"]), p["frequency"], p["start"], p["a0"], tuple(tuple(x) for x in p["data"]), p.get("time_span", "STEP"))
    if k == "equally_spaced_amplitude":
        args = ["name=%s" % _q(p["name"]), "fixedInterval=%r" % p["fixed_interval"],
                "data=%r" % (tuple(p["data"]),), "begin=%r" % p.get("begin", 0.0),
                "timeSpan=%s" % p.get("time_span", "STEP")]
        if p.get("smooth") is not None: args.append("smooth=%r" % p["smooth"])
        return "from abaqusConstants import *; mdb.models[%s].EquallySpacedAmplitude(%s)" % (_q(m), ", ".join(args))
    if k in ("fixed_bc", "displacement_bc", "symmetry_bc", "temperature_bc", "initial_temperature", "initial_stress"):
        return _bc_script(action)
    if k == "gravity":
        args = ["name=%s" % _q(p["name"]), "createStepName=%s" % _q(p.get("step", "Step-1")),
                "distributionType=UNIFORM", "comp1=%r" % p.get("comp1", 0.0),
                "comp2=%r" % p.get("comp2", 0.0), "comp3=%r" % p.get("comp3", 0.0)]
        if p.get("region_expression"): args.append("region=%s" % p["region_expression"])
        if p.get("amplitude"): args.append("amplitude=%s" % _q(p["amplitude"]))
        return "from abaqusConstants import *; mdb.models[%s].Gravity(%s)" % (_q(m), ", ".join(args))
    if k in ("pressure_load", "concentrated_force", "body_force", "body_heat_flux", "surface_heat_flux"):
        return _load_script(action)
    if k == "assembly_inspect":
        return _assembly_inspection_script(m)
    if k == "instance_translate":
        return "a=mdb.models[%s].rootAssembly; a.instances[%s].translate(vector=%r)" % (_q(m), _q(p["instance"]), tuple(p["vector"]))
    if k == "instance_rotate":
        return "a=mdb.models[%s].rootAssembly; a.instances[%s].rotateAboutAxis(axisPoint=%r, axisDirection=%r, angle=%r)" % (_q(m), _q(p["instance"]), tuple(p["axis_point"]), tuple(p["axis_direction"]), p["angle"])
    if k == "instance_linear_pattern":
        return "a=mdb.models[%s].rootAssembly; a.LinearInstancePattern(instanceList=%r, number1=%d, spacing1=%r, number2=%d, spacing2=%r, direction1=%r, direction2=%r)" % (_q(m), tuple(p["instances"]), int(p["number1"]), p["spacing1"], int(p.get("number2", 1)), p.get("spacing2", 0.0), tuple(p.get("direction1", (1.0,0.0,0.0))), tuple(p.get("direction2", (0.0,1.0,0.0))))
    if k == "export_inp":
        return _export_inp_script(m, p)
    if k == "export_odb_csv":
        return _export_odb_csv_script(p)
    if k == "field_output":
        request = p.get("request", "F-Output-1")
        variables = tuple(p.get("variables", ("S", "U", "RF")))
        step = p.get("step", "Step-1")
        extra = ""
        if p.get("frequency") is not None:
            extra += "; req.setValuesInStep(stepName=_st, frequency=%r)" % p["frequency"]
        if p.get("num_intervals") is not None:
            extra += "; req.setValuesInStep(stepName=_st, numIntervals=%r)" % p["num_intervals"]
        return (
            "import step; model=mdb.models[%s]; "
            "_st=%s; _st=([s for s in model.steps.keys() if s != 'Initial'] or [_st])[0] if _st == 'Initial' else _st; "
            "req=(model.fieldOutputRequests[%s] if %s in model.fieldOutputRequests else None); "
            "req=req or model.FieldOutputRequest(name=%s, createStepName=_st, variables=%r); "
            "req.setValues(variables=%r)%s"
            % (_q(m), _q(step), _q(request), _q(request), _q(request), variables, variables, extra)
        )
    if k == "history_output":
        request = p.get("request", "H-Output-1")
        variables = tuple(p.get("variables", ("ALLIE",)))
        step = p.get("step", "Step-1")
        if not p.get("region_expression"):
            return (
                "import step; model=mdb.models[%s]; "
                "_st=%s; _st=([s for s in model.steps.keys() if s != 'Initial'] or [_st])[0] if _st == 'Initial' else _st; "
                "req=(model.historyOutputRequests[%s] if %s in model.historyOutputRequests else None); "
                "req=req or model.HistoryOutputRequest(name=%s, createStepName=_st, variables=%r); "
                "req.setValues(variables=%r)"
                % (_q(m), _q(step), _q(request), _q(request), _q(request), variables, variables)
            )
        return (
            "import step; model=mdb.models[%s]; "
            "_st=%s; _st=([s for s in model.steps.keys() if s != 'Initial'] or [_st])[0] if _st == 'Initial' else _st; "
            "model.HistoryOutputRequest(name=%s, createStepName=_st, variables=%r, region=%s)"
            % (_q(m), _q(step), _q(request), variables, p["region_expression"])
        )
    if k == "create_job":
        jt = p.get("job_type", "ANALYSIS")
        if jt in ("STANDARD", "EXPLICIT", None):
            jt = "ANALYSIS"
        return "from abaqusConstants import *; mdb.Job(name=%s, model=%s, type=%s)" % (_q(p["name"]), _q(m), jt)
    if k == "submit_job":
        return "from abaqusConstants import ON; mdb.jobs[%s].submit(consistencyChecking=ON)" % _q(p["name"])
    if k == "seed_part":
        return "mdb.models[%s].parts[%s].seedPart(size=%r, deviationFactor=%r, minSizeFactor=%r)" % (_q(m), _q(p["part"]), p["size"], p.get("deviation_factor", .1), p.get("min_size_factor", .1))
    if k == "generate_mesh":
        return "mdb.models[%s].parts[%s].generateMesh()" % (_q(m), _q(p["part"]))
    if k == "local_seed_size":
        return "mdb.models[%s].parts[%s].seedEdgeBySize(edges=%s, size=%r, constraint=%s)" % (_q(m), _q(p["part"]), p["region_expression"], p["size"], p.get("constraint", "FREE"))
    if k == "local_seed_number":
        return "mdb.models[%s].parts[%s].seedEdgeByNumber(edges=%s, number=%d, constraint=%s)" % (_q(m), _q(p["part"]), p["region_expression"], int(p["number"]), p.get("constraint", "FREE"))
    if k == "mesh_controls":
        args = ["regions=%s" % p["region_expression"], "technique=%s" % p.get("technique", "FREE")]
        if p.get("algorithm") is not None: args.append("algorithm=%s" % p["algorithm"])
        if p.get("elem_shape") is not None: args.append("elemShape=%s" % p["elem_shape"])
        return "from abaqusConstants import *; mdb.models[%s].parts[%s].setMeshControls(%s)" % (_q(m), _q(p["part"]), ", ".join(args))
    if k == "element_type":
        code = p.get("elem_code", "C3D8R")
        library = p.get("library", "STANDARD")
        return "from abaqusConstants import *; import mesh; elemType=mesh.ElemType(elemCode=%s, elemLibrary=%s); mdb.models[%s].parts[%s].setElementType(regions=%s, elemTypes=(elemType,))" % (code, library, _q(m), _q(p["part"]), p["region_expression"])
    if k == "inspect_geometry":
        return _geometry_inspection_script(m, p)
    if k == "ignore_entity":
        return "mdb.models[%s].parts[%s].ignoreEntity(entities=%s)" % (_q(m), _q(p["part"]), p["region_expression"])
    if k == "restore_entity":
        return "mdb.models[%s].parts[%s].restoreIgnoredEntity(entities=%s)" % (_q(m), _q(p["part"]), p["region_expression"])
    if k == "repair_geometry":
        return "mdb.models[%s].parts[%s].repairGeometry()" % (_q(m), _q(p["part"]))
    if k == "remove_redundant_entities":
        return "mdb.models[%s].parts[%s].removeRedundantEntities()" % (_q(m), _q(p["part"]))
    if k == "inspect_mesh":
        return _mesh_inspection_script(m, p)
    if k == "mesh_quality":
        return _mesh_quality_script(m, p)
    if k == "tie":
        return ("from abaqusConstants import *\nimport interaction\n"
                "try:\n"
                "    mdb.models[%s].Tie(name=%s, main=%s, secondary=%s, positionToleranceMethod=COMPUTED)\n"
                "except TypeError:\n"
                "    mdb.models[%s].Tie(name=%s, master=%s, slave=%s, positionToleranceMethod=COMPUTED)") % (
                    _q(m), _q(p["name"]), p["master_expression"], p["slave_expression"],
                    _q(m), _q(p["name"]), p["master_expression"], p["slave_expression"],
                )
    if k == "contact_property":
        return _contact_property_script(m, p)
    if k == "contact":
        return _contact_script(m, p)
    raise ValueError("unsupported action type: %s" % k)

def _bc_script(action):
    p, m = action.parameters, action.model_name
    region, name, step = p["region_expression"], p["name"], p.get("step", "Initial")
    if action.action_type == "fixed_bc":
        return "model=mdb.models[%s]; region=%s; model.EncastreBC(name=%s, createStepName=%s, region=region)" % (_q(m), region, _q(name), _q(step))
    if action.action_type == "temperature_bc":
        amp = ", amplitude=%s" % _q(p["amplitude"]) if p.get("amplitude") else ""
        return "model=mdb.models[%s]; region=%s; model.TemperatureBC(name=%s, createStepName=%s, region=region, magnitude=%r%s)" % (_q(m), region, _q(name), _q(step), p["magnitude"], amp)
    if action.action_type == "initial_temperature":
        amp = ", amplitude=%s" % _q(p["amplitude"]) if p.get("amplitude") else ""
        return "from abaqusConstants import *; model=mdb.models[%s]; region=%s; model.Temperature(name=%s, createStepName=%s, region=region, distributionType=UNIFORM, magnitudes=(%r,)%s)" % (_q(m), region, _q(name), _q("Initial"), p["magnitude"], amp)
    if action.action_type == "initial_stress":
        return "from abaqusConstants import *; model=mdb.models[%s]; region=%s; model.Stress(name=%s, region=region, distributionType=UNIFORM, sigma11=%r, sigma22=%r, sigma33=%r, sigma12=%r, sigma13=%r, sigma23=%r)" % (_q(m), region, _q(name), p.get("sigma11",0.0), p.get("sigma22",0.0), p.get("sigma33",0.0), p.get("sigma12",0.0), p.get("sigma13",0.0), p.get("sigma23",0.0))
    if action.action_type == "symmetry_bc":
        method = {"X":"XsymmBC", "Y":"YsymmBC", "Z":"ZsymmBC"}.get(str(p.get("plane", "X")).upper())
        if not method: raise ValueError("symmetry plane must be X, Y or Z")
        return "model=mdb.models[%s]; region=%s; model.%s(name=%s, createStepName=%s, region=region)" % (_q(m), region, method, _q(name), _q(step))
    args = []
    for x in ("u1", "u2", "u3", "ur1", "ur2", "ur3"):
        val = p.get(x)
        if val is not None and val != "UNSET":
            args.append("%s=%r" % (x, val))
        else:
            args.append("%s=UNSET" % x)
    return "from abaqusConstants import *; model=mdb.models[%s]; region=%s; model.DisplacementBC(name=%s, createStepName=%s, region=region, %s)" % (_q(m), region, _q(name), _q(step), ", ".join(args))

def _load_script(action):
    p, m = action.parameters, action.model_name
    region, name, step = p["region_expression"], p["name"], p.get("step", "Step-1")
    if action.action_type == "pressure_load":
        amp = ", amplitude=%s" % _q(p["amplitude"]) if p.get("amplitude") else ""
        return "mdb.models[%s].Pressure(name=%s, createStepName=%s, region=%s, magnitude=%r%s)" % (_q(m), _q(name), _q(step), region, p["magnitude"], amp)
    if action.action_type == "body_heat_flux":
        return "mdb.models[%s].BodyHeatFlux(name=%s, createStepName=%s, region=%s, magnitude=%r)" % (_q(m), _q(name), _q(step), region, p["magnitude"])
    if action.action_type == "surface_heat_flux":
        return "mdb.models[%s].SurfaceHeatFlux(name=%s, createStepName=%s, region=%s, magnitude=%r)" % (_q(m), _q(name), _q(step), region, p["magnitude"])
    if action.action_type == "body_force":
        amp = ", amplitude=%s" % _q(p["amplitude"]) if p.get("amplitude") else ""
        return "mdb.models[%s].BodyForce(name=%s, createStepName=%s, region=%s, comp1=%r, comp2=%r, comp3=%r%s)" % (_q(m), _q(name), _q(step), region, p.get("comp1",0), p.get("comp2",0), p.get("comp3",0), amp)
    if action.action_type == "concentrated_force":
        amp = ", amplitude=%s" % _q(p["amplitude"]) if p.get("amplitude") else ""
        return "mdb.models[%s].ConcentratedForce(name=%s, createStepName=%s, region=%s, cf1=%r,cf2=%r,cf3=%r%s)" % (_q(m), _q(name), _q(step), region, p.get("cf1",0), p.get("cf2",0), p.get("cf3",0), amp)
    if action.action_type == "body_heat_flux":
        return "mdb.models[%s].BodyHeatFlux(name=%s, createStepName=%s, region=%s, magnitude=%r)" % (_q(m), _q(name), _q(step), region, p["magnitude"])
    return "mdb.models[%s].SurfaceHeatFlux(name=%s, createStepName=%s, region=%s, magnitude=%r)" % (_q(m), _q(name), _q(step), region, p["magnitude"])


def _geometry_inspection_script(model, p):
    part = p["part"]
    edge_limit = p.get("min_edge_length")
    face_limit = p.get("min_face_size")
    return """from math import sqrt
model=mdb.models[%r]
part=model.parts[%r]
issues=[]
for i,e in enumerate(part.edges):
    try:
        s=e.getSize()
        if %r is not None and s < %r:
            issues.append({'entity_type':'Edge','index':i,'issue_type':'small_edge','metric':s,'threshold':%r,'point':getattr(e,'pointOn',None)})
    except Exception:
        pass
for i,f in enumerate(part.faces):
    try:
        s=f.getSize()
        if %r is not None and s < %r:
            issues.append({'entity_type':'Face','index':i,'issue_type':'small_face','metric':s,'threshold':%r,'point':getattr(f,'pointOn',None)})
    except Exception:
        pass
valid=True
try:
    check=part.checkGeometry(detailed=True)
    if check is False: valid=False
except Exception:
    pass
print({'part':%r,'valid_geometry':valid,'entity_counts':{'faces':len(part.faces),'edges':len(part.edges),'vertices':len(part.vertices)},'issues':issues})
""" % (model,part,edge_limit,edge_limit,edge_limit,face_limit,face_limit,face_limit,part)

def _mesh_inspection_script(model, p):
    part = p["part"]
    return """model=mdb.models[%r]
part=model.parts[%r]
nodes=list(part.nodes)
elements=list(part.elements)
types={}
for e in elements:
    key=str(getattr(e,'type','UNKNOWN'))
    types[key]=types.get(key,0)+1
warnings=[]
if not nodes: warnings.append('no_nodes')
if not elements: warnings.append('no_elements')
print({'part':%r,'node_count':len(nodes),'element_count':len(elements),'element_types':types,'warnings':warnings})
""" % (model,part)


def _contact_property_script(model, p):
    name = p["name"]
    behavior = p.get("normal_behavior", True)
    tangential = p.get("tangential_behavior")
    lines = ["from abaqusConstants import *", "model=mdb.models[%s]" % _q(model),
             "prop=model.ContactProperty(%s)" % _q(name)]
    if behavior:
        lines.append("prop.NormalBehavior(pressureOverclosure=%s)" %
                     p.get("pressure_overclosure", "HARD"))
    if tangential:
        formulation = str(tangential.get("formulation", "PENALTY")).upper()
        if formulation == "FRICTIONLESS":
            lines.append("prop.TangentialBehavior(formulation=FRICTIONLESS)")
        elif formulation in ("PENALTY", "LAGRANGE", "ROUGH", "EXPONENTIAL_DECAY", "USER_DEFINED"):
            args = ["formulation=%s" % formulation]
            if formulation in ("PENALTY", "LAGRANGE"):
                args.append("table=((%r,),)" % tangential.get("friction", 0.0))
                fraction = tangential.get("fraction", 0.005)
                if fraction is not None:
                    args.append("fraction=%r" % fraction)
            lines.append("prop.TangentialBehavior(%s)" % ", ".join(args))
        else:
            raise ValueError("unsupported contact tangential formulation: %s" % formulation)
    return "; ".join(lines)

def _contact_script(model, p):
    sliding = str(p.get("sliding", "FINITE")).upper()
    sliding_const = "SMALL_SLIDING" if sliding in ("SMALL", "SMALL_SLIDING") else "FINITE"
    return ("from abaqusConstants import *\nimport interaction\nmodel=mdb.models[%s]\n"
            "try:\n"
            "    model.SurfaceToSurfaceContactStd(name=%s, createStepName=%s, main=%s, secondary=%s, sliding=%s, interactionProperty=%s)\n"
            "except TypeError:\n"
            "    model.SurfaceToSurfaceContactStd(name=%s, createStepName=%s, master=%s, slave=%s, sliding=%s, interactionProperty=%s)" %
            (_q(model),
             _q(p["name"]), _q(p.get("step", "Initial")),
             p["master_expression"], p["slave_expression"],
             sliding_const, _q(p["property"]),
             _q(p["name"]), _q(p.get("step", "Initial")),
             p["master_expression"], p["slave_expression"],
             sliding_const, _q(p["property"])))


def _mesh_quality_script(model, p):
    part = p["part"]
    criteria = []
    if p.get("max_aspect_ratio") is not None:
        criteria.append(("ASPECT_RATIO", p["max_aspect_ratio"], "max_aspect_ratio"))
    if p.get("max_angular_deviation") is not None:
        criteria.append(("ANGULAR_DEVIATION", p["max_angular_deviation"], "max_angular_deviation"))
    if p.get("min_angle") is not None:
        criteria.append(("SMALL_ANGLE", p["min_angle"], "min_angle"))
    if p.get("max_angle") is not None:
        criteria.append(("LARGE_ANGLE", p["max_angle"], "max_angle"))
    if p.get("max_geometric_deviation_factor") is not None:
        criteria.append(("GEOM_DEVIATION_FACTOR", p["max_geometric_deviation_factor"], "max_geometric_deviation_factor"))
    analysis_checks = bool(p.get("analysis_checks", True))
    return """from abaqusConstants import *
model=mdb.models[%r]
part=model.parts[%r]
result={'part':%r,'node_count':len(part.nodes),'element_count':len(part.elements),
        'metrics':{},'violations':[],'warnings':[],'evidence':[],
        'status':'unknown','source':'native_abaqus_verifyMeshQuality',
        'failed_element_count':0,'warning_element_count':0}
criteria=%r
for criterion_name, threshold, output_name in criteria:
    try:
        criterion = globals()[criterion_name]
        data=part.verifyMeshQuality(criterion=criterion, threshold=threshold)
        result['metrics'][output_name]=float(data.get('worst', 0.0))
        result['evidence'].append('native_verify:%%s'%%criterion_name)
        failed=len(data.get('failedElements', ()))
        warnings=len(data.get('warningElements', ()))
        result['failed_element_count'] += failed
        result['warning_element_count'] += warnings
        if failed:
            result['violations'].append(output_name)
    except Exception as exc:
        result['warnings'].append('unsupported_quality:%%s:%%s'%%(criterion_name, type(exc).__name__))
if %r:
    try:
        data=part.verifyMeshQuality(criterion=ANALYSIS_CHECKS)
        result['evidence'].append('native_verify:ANALYSIS_CHECKS')
        result['failed_element_count'] += len(data.get('failedElements', ()))
        result['warning_element_count'] += len(data.get('warningElements', ()))
        if data.get('failedElements'):
            result['violations'].append('analysis_checks')
        if data.get('warningElements'):
            result['warnings'].append('analysis_check_warnings')
    except Exception as exc:
        result['warnings'].append('unsupported_quality:ANALYSIS_CHECKS:%%s'%%type(exc).__name__)
if %r is not None:
    result['warnings'].append('min_jacobian_requires_native_analysis_check_or_element_specific_api')
if %r is not None:
    result['warnings'].append('max_skew_not_mapped_to_native_verifyMeshQuality_criterion')
if result['violations']:
    result['status']='fail'
elif result['warnings']:
    result['status']='warning'
elif result['metrics'] or result['evidence']:
    result['status']='pass'
print(result)
""" % (model, part, part, criteria, analysis_checks, p.get("min_jacobian"), p.get("max_skew"))

def _assembly_inspection_script(model):
    return """a=mdb.models[%r].rootAssembly
result={'instances':[],'instance_count':len(a.instances)}
for name, inst in a.instances.items():
    item={'name':name,'partName':getattr(inst,'partName',None)}
    try: item['translation']=tuple(inst.getTranslation())
    except Exception: item['translation']=None
    try: item['rotation']=tuple(inst.getRotation())
    except Exception: item['rotation']=None
    result['instances'].append(item)
print(result)
""" % model


def _export_inp_script(model, p):
    job = p["job_name"]
    output_path = p.get("output_path")
    if not output_path:
        return "from abaqusConstants import *; mdb.jobs[%s].writeInput(consistencyChecking=ON)" % _q(job)
    return """import os, shutil
from abaqusConstants import ON
job=mdb.jobs[%r]
target=os.path.abspath(%r)
directory=os.path.dirname(target)
if directory and not os.path.isdir(directory): os.makedirs(directory)
job.writeInput(consistencyChecking=ON)
generated=os.path.abspath(job.name + '.inp')
if generated != target:
    shutil.copyfile(generated, target)
print({'output_path':target,'exists':os.path.isfile(target)})
""" % (job, output_path)


def _export_odb_csv_script(p):
    return """import csv, os
from odbAccess import openOdb
odb=openOdb(path=%r, readOnly=True)
stepName=%r if %r else list(odb.steps.keys())[-1]
step=odb.steps[stepName]
frame=step.frames[%d]
field=frame.fieldOutputs[%r]
target=os.path.abspath(%r)
directory=os.path.dirname(target)
if directory and not os.path.isdir(directory): os.makedirs(directory)
values=[]
for v in field.values:
    if %r and str(v.position) != %r: continue
    values.append(v)
with open(target, 'wb') as fh:
    writer=csv.writer(fh)
    writer.writerow(['step','frame','frameValue','instance','nodeLabel','elementLabel','integrationPoint','values'])
    for v in values:
        data=getattr(v, 'data', ())
        if not isinstance(data, (tuple,list)): data=(data,)
        if %r is not None: data=(data[int(%r)],)
        writer.writerow([stepName, %d, frame.frameValue, getattr(getattr(v,'instance',None),'name',''),
                         getattr(v,'nodeLabel',''), getattr(v,'elementLabel',''),
                         getattr(v,'integrationPoint',''), repr(tuple(data))])
odb.close()
print({'output_path':target,'rows':len(values),'variable':%r,'step':stepName,'frame':%d})
""" % (p["odb_path"], p.get("step"), p.get("step"), int(p.get("frame",-1)), p.get("variable","U"),
       p["output_path"], p.get("position"), p.get("position"), p.get("component"), p.get("component"),
       int(p.get("frame",-1)), p.get("variable","U"), int(p.get("frame",-1)))
