def inspect_odb(executor, path):
    if hasattr(executor, "inspect_odb"):
        return executor.inspect_odb(path)
    code = ("from odbAccess import openOdb\n"
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
