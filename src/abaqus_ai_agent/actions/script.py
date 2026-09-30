def _q(value):
    return repr(value)

def action_to_script(action):
    p, m, k = action.parameters, action.model_name, action.action_type
    if k == "python":\n        return p["code"]\n    if k == "material_elastic":
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
    if k == "local_seed_size":
        return "mdb.models[%s].parts[%s].seedEdgeBySize(edges=%s, size=%r, constraint=%s)" % (_q(m), _q(p["part"]), p["region_expression"], p["size"], p.get("constraint", "FREE"))
    if k == "local_seed_number":
        return "mdb.models[%s].parts[%s].seedEdgeByNumber(edges=%s, number=%d, constraint=%s)" % (_q(m), _q(p["part"]), p["region_expression"], int(p["number"]), p.get("constraint", "FREE"))
    if k == "mesh_controls":
        args = ["regions=%s" % p["region_expression"], "technique=%s" % p.get("technique", "FREE")]
        if p.get("algorithm") is not None: args.append("algorithm=%s" % p["algorithm"])
        if p.get("elem_shape") is not None: args.append("elemShape=%s" % p["elem_shape"])
        return "mdb.models[%s].parts[%s].setMeshControls(%s)" % (_q(m), _q(p["part"]), ", ".join(args))
    if k == "element_type":
        return "mdb.models[%s].parts[%s].setElementType(regions=%s, elemTypes=%s)" % (_q(m), _q(p["part"]), p["region_expression"], p["elem_types"])
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
    lines = ["model=mdb.models[%s]" % _q(model),
             "prop=model.ContactProperty(%s)" % _q(name)]
    if behavior:
        lines.append("prop.NormalBehavior(pressureOverclosure=%s)" % p.get("pressure_overclosure", "HARD"))
    if tangential:
        lines.append("prop.TangentialBehavior(formulation=%s, table=((%r,),))" %
                     (tangential.get("formulation", "PENALTY"), tangential.get("friction", 0.0)))
    return "; ".join(lines)

def _contact_script(model, p):
    return ("model=mdb.models[%s]; model.SurfaceToSurfaceContactStd("
            "name=%s, createStepName=%s, master=%s, slave=%s, "
            "sliding=%s, interactionProperty=%s)" %
            (_q(model), _q(p["name"]), _q(p.get("step", "Initial")),
             p["master_expression"], p["slave_expression"],
             p.get("sliding", "FINITE"), _q(p["property"])))


def _mesh_quality_script(model, p):
    part = p["part"]
    return """model=mdb.models[%r]
part=model.parts[%r]
result={'part':%r,'node_count':len(part.nodes),'element_count':len(part.elements),'metrics':{},'warnings':[]}
if not part.elements:
    result['warnings'].append('no_elements')
print(result)
""" % (model, part, part)
