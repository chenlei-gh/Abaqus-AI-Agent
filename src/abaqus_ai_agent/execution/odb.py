def inspect_odb(executor, path):
    if hasattr(executor, "inspect_odb"):
        return executor.inspect_odb(path)
    code = ("from odbAccess import openOdb\n"
            "from abaqusConstants import *\n"
            "odb=openOdb(path=%r, readOnly=True)\n"
            "result={'steps':list(odb.steps.keys()),"
            "'instances':list(odb.rootAssembly.instances.keys())}\n"
            "result['step_frames']={k:len(v.frames) for k,v in odb.steps.items()}\n"
            "odb.close()\nprint(result)") % path
    return executor.execute(code)


def _extract_code(path, step, field, component=None, invariant=None,
                  position=None, region=None, frame=-1):
    operations = []
    if position:
        operations.append("fo=fo.getSubset(position=%r)" % position)
    if region:
        operations.append("fo=fo.getSubset(region=%s)" % region)
    if invariant:
        operations.append("fo=fo.getScalarField(invariant=%s)" % invariant)
    elif component:
        operations.append("fo=fo.getScalarField(componentLabel=%r)" % component)
    suffix = "\n".join(operations)
    if suffix:
        suffix += "\n"

    return (
        "from odbAccess import openOdb\n"
        "from abaqusConstants import *\n"
        "odb=openOdb(path=%r, readOnly=True)\n"
        "st=odb.steps[%r]\n"
        "fr=st.frames[%r]\n"
        "fo=fr.fieldOutputs[%r]\n%s"
        "def _coords_for_value(v):\n"
        "    inst=getattr(v, 'instance', None)\n"
        "    if inst is None:\n"
        "        return None\n"
        "    node_label=getattr(v, 'nodeLabel', None)\n"
        "    if node_label is not None:\n"
        "        try:\n"
        "            return tuple(inst.getNodeFromLabel(node_label).coordinates)\n"
        "        except Exception:\n"
        "            pass\n"
        "    elem_label=getattr(v, 'elementLabel', None)\n"
        "    if elem_label is not None:\n"
        "        try:\n"
        "            elem=inst.getElementFromLabel(elem_label)\n"
        "            pts=[]\n"
        "            for label in elem.connectivity:\n"
        "                pts.append(tuple(inst.getNodeFromLabel(label).coordinates))\n"
        "            if pts:\n"
        "                n=float(len(pts))\n"
        "                return tuple(sum(p[i] for p in pts)/n for i in range(3))\n"
        "        except Exception:\n"
        "            pass\n"
        "    return None\n"
        "result=[]\n"
        "for v in fo.values:\n"
        "    result.append({'label':getattr(v,'nodeLabel',"
        "getattr(v,'elementLabel',None)),"
        "'node_label':getattr(v,'nodeLabel',None),"
        "'element_label':getattr(v,'elementLabel',None),"
        "'instance':getattr(getattr(v,'instance',None),'name',None),"
        "'position':str(getattr(v,'position',None)),"
        "'coordinates':_coords_for_value(v),"
        "'data':v.data, 'magnitude':getattr(v,'magnitude',None),"
        "'mises':getattr(v,'mises',None),"
        "'maxPrincipal':getattr(v,'maxPrincipal',None)})\n"
        "result_meta={'step':%r,'frame_index':%r,"
        "'frame_value':getattr(fr,'frameValue',None),"
        "'description':getattr(fr,'description',None),"
        "'field':%r,'component':%r,'invariant':%r,"
        "'position':%r,'count':len(result)}\n"
        "odb.close()\nprint({'meta':result_meta,'values':result})"
    ) % (path, step, frame, field, suffix, step, frame, field,
         component, invariant, position)


def extract_field(executor, path, step, field, component=None,
                  invariant=None, position=None, region=None, frame=-1):
    """Extract deterministic ODB field evidence with frame and location.

    Coordinates are node coordinates for nodal values and element-node
    centroid coordinates for element values. The latter is a locator, not an
    integration-point coordinate.
    """
    code = _extract_code(path, step, field, component=component,
                         invariant=invariant, position=position,
                         region=region, frame=frame)
    return executor.execute(code)


def summarize_numeric(values):
    # Accept both the legacy flat list and the newer {'meta','values'} envelope.
    if isinstance(values, dict):
        values = values.get("values", [])
    nums = []
    for item in values or ():
        data = item.get("data") if isinstance(item, dict) else None
        for value in (data,) if isinstance(data, (int, float)) else (data or ()):
            if isinstance(value, (int, float)):
                nums.append(float(value))
        for key in ("magnitude", "mises", "maxPrincipal"):
            value = item.get(key) if isinstance(item, dict) else None
            if isinstance(value, (int, float)):
                nums.append(float(value))
    if not nums:
        return {"count": 0, "minimum": None, "maximum": None, "average": None}
    return {"count": len(nums), "minimum": min(nums), "maximum": max(nums),
            "average": sum(nums) / len(nums)}



def extract_history(executor, path, step, region, variables):
    """Extract ODB history-output data as bounded, machine-readable evidence."""
    code = (
        "from odbAccess import openOdb\n"
        "odb=openOdb(path=%r, readOnly=True)\n"
        "st=odb.steps[%r]\n"
        "hr=st.historyRegions[%r]\n"
        "wanted=%r\n"
        "result={}\n"
        "for name in wanted:\n"
        "    out=hr.historyOutputs.get(name)\n"
        "    result[name]=list(out.data) if out is not None else None\n"
        "odb.close()\n"
        "print({'step':%r,'region':%r,'variables':result})"
    ) % (path, step, region, tuple(variables), step, region)
    return executor.execute(code)


def summarize_history(data):
    """Summarize history evidence without interpreting engineering correctness."""
    if not isinstance(data, dict):
        return {"status": "invalid", "variables": {}}
    variables = data.get("variables", {})
    summary = {}
    for name, series in variables.items():
        values = [float(pair[1]) for pair in (series or ()) if isinstance(pair, (tuple, list)) and len(pair) >= 2]
        summary[name] = {
            "count": len(values),
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
            "last": values[-1] if values else None,
        }
    return {"status": "available", "step": data.get("step"), "region": data.get("region"), "variables": summary}


def extract_contact_field(executor, path, step, field, frame=-1, position=None,
                          region=None):
    """Extract contact-related field output as evidence.

    Missing output is represented explicitly as status='unavailable';
    an empty/zero-valued output is never treated as missing.
    """
    operations = []
    if position:
        operations.append("fo=fo.getSubset(position=%r)" % position)
    if region:
        operations.append("fo=fo.getSubset(region=%s)" % region)
    subset_code = "\\n".join(operations)
    if subset_code:
        subset_code += "\\n"
    code = (
        "from odbAccess import openOdb\\n"
        "odb=openOdb(path=%r, readOnly=True)\\n"
        "st=odb.steps[%r]\\n"
        "fr=st.frames[%r]\\n"
        "requested=%r\\n"
        "available=list(fr.fieldOutputs.keys())\\n"
        "if requested not in fr.fieldOutputs:\\n"
        "    result={'status':'unavailable','reason':'field_output_missing',"
        "'step':%r,'frame_index':%r,'field':requested,'available':available}\\n"
        "else:\\n"
        "    fo=fr.fieldOutputs[requested]\\n"
        "%s"
        "    values=[]\\n"
        "    for v in fo.values:\\n"
        "        values.append({'node_label':getattr(v,'nodeLabel',None),"
        "'element_label':getattr(v,'elementLabel',None),"
        "'instance':getattr(getattr(v,'instance',None),'name',None),"
        "'position':str(getattr(v,'position',None)),"
        "'data':v.data,'magnitude':getattr(v,'magnitude',None),"
        "'mises':getattr(v,'mises',None),"
        "'status':getattr(v,'status',None)})\\n"
        "    result={'status':'available','step':%r,'frame_index':%r,"
        "'frame_value':getattr(fr,'frameValue',None),'field':requested,"
        "'count':len(values),'values':values}\\n"
        "odb.close()\\n"
        "print(result)\\n"
    ) % (path, step, frame, field, step, frame, subset_code, step, frame)
    return executor.execute(code)


def extract_contact_history(executor, path, step, region=None,
                            variables=("CPRESS", "COPEN", "CSTATUS")):
    """Extract contact history outputs with explicit missing-output states."""
    code = (
        "from odbAccess import openOdb\\n"
        "odb=openOdb(path=%r, readOnly=True)\\n"
        "st=odb.steps[%r]\\n"
        "regions=st.historyRegions\\n"
        "requested=%r\\n"
        "region_name=%r\\n"
        "result={}\\n"
        "if region_name:\\n"
        "    if region_name not in regions:\\n"
        "        result={'status':'unavailable','reason':'history_region_missing',"
        "'step':%r,'region':region_name,'variables':{}}\\n"
        "    else:\\n"
        "        hr=regions[region_name]\\n"
        "        result={'status':'available','step':%r,'region':region_name,'variables':{}}\\n"
        "else:\\n"
        "    matches=[]\\n"
        "    for _name,_hr in regions.items():\\n"
        "        if any(_var in _hr.historyOutputs for _var in requested):\\n"
        "            matches.append((_name,_hr))\\n"
        "    if len(matches) == 1:\\n"
        "        region_name,hr=matches[0]\\n"
        "        result={'status':'available','step':%r,'region':region_name,'variables':{}}\\n"
        "    elif len(matches) == 0:\\n"
        "        result={'status':'unavailable','reason':'history_output_missing',"
        "'step':%r,'region':None,'variables':{}}\\n"
        "    else:\\n"
        "        result={'status':'ambiguous','reason':'multiple_history_regions',"
        "'step':%r,'regions':[x[0] for x in matches],'variables':{}}\\n"
        "if result['status'] == 'available':\\n"
        "    for name in requested:\\n"
        "        if name in hr.historyOutputs:\\n"
        "            result['variables'][name]={'status':'available',"
        "'data':list(hr.historyOutputs[name].data)}\\n"
        "        else:\\n"
        "            result['variables'][name]={'status':'unavailable',"
        "'reason':'history_output_missing'}\\n"
        "odb.close()\\n"
        "print(result)\\n"
    ) % (path, step, tuple(variables), region, step, step, step, step, step)
    return executor.execute(code)


def extract_contact_evidence(executor, path, step, fields=("CPRESS", "COPEN", "CSTATUS"),
                             history_variables=("CPRESS", "COPEN", "CSTATUS"),
                             frame=-1, history_region=None, position=None, region=None):
    """Extract field/history contact evidence without judging engineering correctness."""
    field_results = {}
    for field in fields:
        field_results[field] = extract_contact_field(
            executor, path, step, field, frame=frame, position=position, region=region)
    history = extract_contact_history(
        executor, path, step, region=history_region, variables=history_variables)
    return {"step": step, "frame": frame, "fields": field_results, "history": history}
