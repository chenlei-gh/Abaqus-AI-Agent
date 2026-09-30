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


def extract_field(executor, path, step, field, component=None,
                  invariant=None, position=None, region=None):
    """Extract ODB field values with optional Abaqus-native subset/invariant."""
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
    code = (
        "from odbAccess import openOdb\n"
        "odb=openOdb(path=%r, readOnly=True)\n"
        "st=odb.steps[%r]\nfr=st.frames[-1]\n"
        "fo=fr.fieldOutputs[%r]\n%s"
        "result=[]\n"
        "for v in fo.values:\n"
        "    result.append({'label':getattr(v,'nodeLabel',"
        "getattr(v,'elementLabel',None)),"
        "'instance':getattr(getattr(v,'instance',None),'name',None),"
        "'position':str(getattr(v,'position',None)),"
        "'data':v.data, 'magnitude':getattr(v,'magnitude',None),"
        "'mises':getattr(v,'mises',None),"
        "'maxPrincipal':getattr(v,'maxPrincipal',None)})\n"
        "odb.close()\nprint(result)"
    ) % (path, step, field, suffix)
    return executor.execute(code)


def summarize_numeric(values):
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
