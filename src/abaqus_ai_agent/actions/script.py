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
        return "model=mdb.models[%s]; mat=model.Material(%s); mat.Elastic(table=((%r,%r),))" % (_q(m), _q(p["name"]), p["youngs_modulus"], p["poisson"])
    if k == "material_density":
        return "mdb.models[%s].materials[%s].Density(table=((%r,),))" % (_q(m), _q(p["name"]), p["density"])
    if k == "material_plastic":
        return "mdb.models[%s].materials[%s].Plastic(table=%r)" % (_q(m), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "material_conductivity":
        return "mdb.models[%s].materials[%s].Conductivity(table=%r)" % (_q(m), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "material_specific_heat":
        return "mdb.models[%s].materials[%s].SpecificHeat(table=%r)" % (_q(m), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
    if k == "material_expansion":
        return "mdb.models[%s].materials[%s].Expansion(table=%r)" % (_q(m), _q(p["name"]), tuple(tuple(x) for x in p["table"]))
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
        step = p.get("step", "Initial")
        return "model=mdb.models[%s]; req=(model.fieldOutputRequests[%s] if %s in model.fieldOutputRequests else None); req=req or model.FieldOutputRequest(name=%s, createStepName=%s, variables=%r); req.setValues(variables=%r)" % (_q(m), _q(request), _q(request), _q(step), variables, variables)
    if k == "history_output":
        request = p.get("request", "H-Output-1")
        variables = tuple(p.get("variables", ("ALLIE",)))
        step = p.get("step", "Step-1")
        if not p.get("region_expression"):
            return "model=mdb.models[%s]; req=(model.historyOutputRequests[%s] if %s in model.historyOutputRequests else None); req=req or model.HistoryOutputRequest(name=%s, createStepName=%s, variables=%r); req.setValues(variables=%r)" % (_q(m), _q(request), _q(request), _q(step), variables, variables)
        return "model=mdb.models[%s]; model.HistoryOutputRequest(name=%s, createStepName=%s, variables=%r, region=%s)" % (_q(m), _q(request), _q(step), variables, p["region_expression"])
    if k == "create_job":
        return "mdb.Job(name=%s, model=%s, type=%s)" % (_q(p["name"]), _q(m), p.get("job_type", "STANDARD"))
    if k == "submit_job":
        return "from abaqusConstants import ON; mdb.jobs[%s].submit(consistencyChecking=ON)" % _q(p["name"])
    if k == "seed_part":
        return "mdb.models[%s].parts[%s].seedPart(size=%r, deviationFactor=%r, minSizeFactor=%r)" % (_q(m), _q(p["part"]), p["size"], p.get("deviation_factor", .1), p.get("min_size_factor", .1))
    if k == "generate_mesh":
        return "mdb.models[%s].parts[%s].generateMesh()" % (_q(m), _q(p["part"]))
    if k == "bias_seed_size":
        return "mdb.models[%s].parts[%s].seedEdgeByBias(edges=%s, biasMethod=DOUBLE, end1Edges=%s, end2Edges=%s, ratio=%r, constraint=%s)" % (
            _q(m), _q(p["part"]), p["region_expression"], p["end1"], p["end2"], p["size"], p.get("constraint", "FREE"))
    if k == "bias_seed_number":
        return "mdb.models[%s].parts[%s].seedEdgeByBias(edges=%s, biasMethod=DOUBLE, end1Edges=%s, end2Edges=%s, number=%d, constraint=%s)" % (
            _q(m), _q(p["part"]), p["region_expression"], p["end1"], p["end2"], int(p["number"]), p.get("constraint", "FREE"))
    if k == "sweep_path":
        sense = p.get("sense", "FORWARD")
        if sense not in ("FORWARD", "REVERSE"):
            raise ValueError("sweep path sense must be FORWARD or REVERSE")
        return "from abaqusConstants import *; mdb.models[%s].parts[%s].setSweepPath(region=%s, edge=%s, sense=%s)" % (
            _q(m), _q(p["part"]), p["region_expression"], p["edge_expression"], sense)
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
    if k == "verify_mesh_quality":
        return _mesh_verify_script(m, p)
    if k == "tie":
        return "mdb.models[%s].Tie(name=%s, master=%s, slave=%s, positionToleranceMethod=COMPUTED)" % (_q(m), _q(p["name"]), p["master_expression"], p["slave_expression"])
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
    vals = [p.get(x) for x in ("u1","u2","u3","ur1","ur2","ur3")]
    return "model=mdb.models[%s]; region=%s; model.DisplacementBC(name=%s, createStepName=%s, region=region, u1=%r,u2=%r,u3=%r,ur1=%r,ur2=%r,ur3=%r)" % (_q(m), region, _q(name), _q(step), *vals)

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
            lines.append("prop.TangentialBehavior(%s)" % ", ".join(args))
        else:
            raise ValueError("unsupported contact tangential formulation: %s" % formulation)
    return "; ".join(lines)

def _contact_script(model, p):
    return ("from abaqusConstants import *; model=mdb.models[%s]; model.SurfaceToSurfaceContactStd("
            "name=%s, createStepName=%s, main=%s, secondary=%s, "
            "sliding=%s, interactionProperty=%s)" %
            (_q(model), _q(p["name"]), _q(p.get("step", "Initial")),
             p["master_expression"], p["slave_expression"],
             p.get("sliding", "FINITE"), _q(p["property"])))


def _mesh_quality_script(model, p):
    part = p["part"]
    max_ar = p.get("max_aspect_ratio")
    min_angle = p.get("min_angle")
    max_angle = p.get("max_angle")
    max_skew = p.get("max_skew")
    min_jac = p.get("min_jacobian")
    return """from math import sqrt, acos, pi
model=mdb.models[%r]
part=model.parts[%r]
nodes={n.label:tuple(n.coordinates) for n in part.nodes}
elements=list(part.elements)
result={'part':%r,'node_count':len(nodes),'element_count':len(elements),
        'metrics':{},'violations':[],'warnings':[],'evidence':[],'status':'unknown','source':'unsupported'}

def dist(a,b):
    return sqrt(sum((a[i]-b[i])**2 for i in range(3)))

def angle(a,b,c):
    ab=[a[i]-b[i] for i in range(3)]
    cb=[c[i]-b[i] for i in range(3)]
    la=sqrt(sum(x*x for x in ab)); lc=sqrt(sum(x*x for x in cb))
    if la == 0.0 or lc == 0.0: return None
    x=max(-1.0,min(1.0,sum(ab[i]*cb[i] for i in range(3))/(la*lc)))
    return acos(x)*180.0/pi

aspects=[]; angles=[]; skews=[]; unsupported=set()
for e in elements:
    typ=str(getattr(e,'type','')).upper()
    conn=tuple(getattr(e,'connectivity',()))
    pts=[nodes.get(label) for label in conn]
    if not pts or any(x is None for x in pts):
        unsupported.add('missing_node_coordinates'); continue
    if typ.startswith(('C3','CPS3','CPE3','S3','STRI3','CAX3')):
        edge_pairs=((0,1),(1,2),(2,0))
        vertex_triplets=((1,0,2),(0,1,2),(0,2,1))
    elif typ.startswith(('C4','CPS4','CPE4','S4','S4R','SC4','SC8','CPS8','CPE8')):
        edge_pairs=((0,1),(1,2),(2,3),(3,0))
        vertex_triplets=((3,0,1),(0,1,2),(1,2,3),(2,3,0))
    else:
        unsupported.add('element_type:'+typ); continue
    lengths=[dist(pts[i],pts[j]) for i,j in edge_pairs]
    positive=[x for x in lengths if x > 0.0]
    if not positive:
        unsupported.add('zero_edge'); continue
    aspects.append(max(positive)/min(positive))
    for a,b,c in vertex_triplets:
        q=angle(pts[a],pts[b],pts[c])
        if q is not None: angles.append(q)
    if len(lengths) == 4:
        # A conservative skew proxy: deviation of adjacent-edge dot products
        local=[]
        for i in range(4):
            a=pts[i]; b=pts[(i+1)%4]; c=pts[(i+2)%4]
            ab=[b[j]-a[j] for j in range(3)]
            bc=[c[j]-b[j] for j in range(3)]
            lab=sqrt(sum(x*x for x in ab)); lbc=sqrt(sum(x*x for x in bc))
            if lab and lbc:
                local.append(abs(sum(ab[j]*bc[j] for j in range(3))/(lab*lbc)))
        if local: skews.append(max(local))

if aspects:
    result['metrics']['max_aspect_ratio']=max(aspects)
    result['metrics']['avg_aspect_ratio']=sum(aspects)/len(aspects)
if angles:
    result['metrics']['min_angle']=min(angles)
    result['metrics']['max_angle']=max(angles)
if skews:
    result['metrics']['max_skew']=max(skews)
if %r is not None and aspects and max(aspects) > %r:
    result['violations'].append('max_aspect_ratio')
if %r is not None and angles and min(angles) < %r:
    result['violations'].append('min_angle')
if %r is not None and angles and max(angles) > %r:
    result['violations'].append('max_angle')
if %r is not None and skews and max(skews) > %r:
    result['violations'].append('max_skew')
if %r is not None:
    result['warnings'].append('min_jacobian_unsupported_without_element_shape_api')
if unsupported:
    result['warnings'].extend(['unsupported_quality:'+x for x in sorted(unsupported)])
if not elements:
    result['warnings'].append('no_elements')
if result['violations']:
    result['status']='fail'
elif result['warnings']:
    result['status']='warning'
elif result['metrics']:
    result['status']='pass'
if result['metrics']:
    result['source']='computed_quality'
result['evidence']=['part:%s'%part, 'elements:%d'%len(elements)]
print(result)
""" % (model, part, part, max_ar, max_ar, min_angle, min_angle,
       max_angle, max_angle, max_skew, max_skew, min_jac)


def _mesh_verify_script(model, p):
    part = p["part"]
    criterion = p.get("criterion", "ANALYSIS_CHECKS")
    allowed = ("ANALYSIS_CHECKS", "ASPECT_RATIO", "SHAPE_FACTOR", "ANGLE", "GEOMETRIC_DEVIATION_FACTOR",
               "MINIMUM_ANGLE", "MAXIMUM_ANGLE", "STABLE_TIME_INCREMENT", "SHORTEST_EDGE", "LONGEST_EDGE")
    if criterion not in allowed:
        raise ValueError("unsupported Abaqus mesh verification criterion: %s" % criterion)
    create_set = p.get("create_set")
    set_arg = ", createSet=%s" % _q(create_set) if create_set else ""
    return """from abaqusConstants import *
model=mdb.models[%r]
part=model.parts[%r]
poor=part.verifyMeshQuality(criterion=%s%s)
labels=[]
for element in poor:
    try: labels.append(int(element.label))
    except Exception: pass
print({'part':%r,'criterion':%r,'poor_element_count':len(labels),'poor_element_labels':labels,'status':'fail' if labels else 'pass','source':'abaqus_native_verify'})
""" % (model, part, criterion, set_arg, part, criterion)


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
